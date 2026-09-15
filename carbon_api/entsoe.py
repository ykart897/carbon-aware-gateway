"""Optional ENTSO-E generation-mix estimates. Production MW is integrated to MWh.
Consumption and imports are excluded; errors return unavailable data for labeled fallback."""

import time
import threading
import gzip
import logging
import math
import re
from urllib.parse import urlencode
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET

from config import ENTSOE_API_KEY as ENTSOE_TOKEN, REGIONS

ENTSOE_BASE = "https://web-api.tp.entsoe.eu/api"

# Bolge → ENTSO-E bidding zone EIC kodu
ZONE_CODES = {
    "DE": "10Y1001A1001A83F",  # Germany
    "IE": "10YIE-1001A00010",  # Ireland
    "FR": "10YFR-RTE------C",  # France
    "PL": "10YPL-AREA-----S",  # Poland
}

# Emisyon faktorleri gCO2eq/kWh — IPCC AR5 + EEA 2023
# Kaynak: https://www.ipcc.ch/site/assets/uploads/2018/02/ipcc_wg3_ar5_annex-iii.pdf
EMISSION_FACTORS = {
    "B01": ("Biomass", 230),
    "B02": ("Fossil Brown coal/Lignite", 1054),
    "B03": ("Fossil Coal-derived gas", 490),
    "B04": ("Fossil Gas", 490),
    "B05": ("Fossil Hard coal", 820),
    "B06": ("Fossil Oil", 650),
    "B07": ("Fossil Oil shale", 700),
    "B08": ("Fossil Peat", 960),
    "B09": ("Geothermal", 38),
    "B10": ("Hydro Pumped Storage", 30),
    "B11": ("Hydro Run-of-river", 24),
    "B12": ("Hydro Water Reservoir", 24),
    "B13": ("Marine", 17),
    "B14": ("Nuclear", 12),
    "B15": ("Other renewable", 50),
    "B16": ("Solar", 41),
    "B17": ("Waste", 330),
    "B18": ("Wind Offshore", 12),
    "B19": ("Wind Onshore", 11),
    "B20": ("Other", 300),
}

# Tip bazli yenilenebilir yuzdesi
RENEWABLE_TYPES = {"B09", "B10", "B11", "B12", "B13", "B15", "B16", "B18", "B19"}

# Cache: her bolge icin 15 dk gecerli
_cache_lock = threading.Lock()
_cache: dict = {}
CACHE_TTL = 900  # 15 dakika


def _cache_get(region: str):
    with _cache_lock:
        e = _cache.get(region)
        if e and (time.time() - e["ts"]) < CACHE_TTL:
            return e
    return None


def _cache_set(region: str, data: dict):
    with _cache_lock:
        _cache[region] = {**data, "ts": time.time()}


def _entsoe_request(params: dict) -> str:
    """ENTSO-E API'ye istek gonder, XML string dondur."""
    base_params = {"securityToken": ENTSOE_TOKEN}
    all_params = {**base_params, **params}
    query = urlencode(all_params)
    url = f"{ENTSOE_BASE}?{query}"

    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/xml",
            "Accept-Encoding": "gzip",
            "User-Agent": "CarbonGateway/3.0 COMP4206",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read()
        if resp.info().get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8")


def _duration_hours(value):
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match:
        raise ValueError("Unsupported resolution")
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    duration = hours + minutes / 60 + seconds / 3600
    if duration <= 0:
        raise ValueError("Resolution must be positive")
    return duration


def _parse_generation_xml(xml_text: str) -> dict:
    """Integrate generation power into MWh; exclude consumption time series.

    A01 contains each interval. A03 holds a point's power until the next
    position or period end. Incomplete or unsupported data is not a valid mix.
    """
    root = ET.fromstring(xml_text)
    prefix = root.tag.split("}")[0] + "}" if "}" in root.tag else ""

    def text(element, tag):
        return element.findtext(prefix + tag, default="").strip()

    result = {}
    coverage = {}
    for series in root.iter(prefix + "TimeSeries"):
        if text(series, "outBiddingZone_Domain.mRID"):
            continue
        if not text(series, "inBiddingZone_Domain.mRID"):
            raise ValueError("Generation domain missing")
        if text(series, "businessType") != "A01":
            raise ValueError("Expected production series")
        psr = series.findtext(f"{prefix}MktPSRType/{prefix}psrType", default="").strip()
        if psr not in EMISSION_FACTORS:
            raise ValueError("Unsupported production type")
        unit = text(series, "quantity_Measure_Unit.name")
        curve = text(series, "curveType")
        if unit not in ("MAW", "MWH") or curve not in ("A01", "A03"):
            raise ValueError("Unsupported unit or curve type")
        if unit == "MWH" and curve == "A03":
            raise ValueError("Variable-block energy is ambiguous")
        for period in series.findall(prefix + "Period"):
            interval = period.find(prefix + "timeInterval")
            if interval is None:
                raise ValueError("Period time interval missing")
            start = datetime.fromisoformat(
                text(interval, "start").replace("Z", "+00:00")
            )
            end = datetime.fromisoformat(text(interval, "end").replace("Z", "+00:00"))
            if start.tzinfo is None or end.tzinfo is None:
                raise ValueError("Period must have a timezone")
            hours = _duration_hours(text(period, "resolution"))
            count = (end - start).total_seconds() / (3600 * hours)
            if count <= 0 or not math.isclose(count, round(count)):
                raise ValueError("Period does not align with resolution")
            count = round(count)
            points = {}
            for point in period.findall(prefix + "Point"):
                position = int(text(point, "position"))
                value = float(text(point, "quantity"))
                if position in points or not 1 <= position <= count:
                    raise ValueError("Invalid point position")
                if not math.isfinite(value) or value < 0:
                    raise ValueError("Invalid generation quantity")
                points[position] = value
            positions = sorted(points)
            if not positions or positions[0] != 1:
                raise ValueError("Missing initial point")
            if curve == "A01" and positions != list(range(1, count + 1)):
                raise ValueError("Incomplete fixed-interval series")
            for i, position in enumerate(positions):
                following = positions[i + 1] if i + 1 < len(positions) else count + 1
                duration = hours * (following - position)
                value = points[position]
                result[psr] = result.get(psr, 0) + (
                    value * duration if unit == "MAW" else value
                )
            window = (start.astimezone(timezone.utc), end.astimezone(timezone.utc))
            windows = coverage.setdefault(psr, [])
            if any(window[0] < old[1] and old[0] < window[1] for old in windows):
                raise ValueError("Overlapping generation periods")
            windows.append(window)

    # Compare total covered time boundaries across production types. Different
    # resolutions are valid, but partial mixes would bias the weighted average.
    def merged(windows):
        intervals = []
        for start, end in sorted(windows):
            if intervals and intervals[-1][1] == start:
                intervals[-1] = (intervals[-1][0], end)
            else:
                intervals.append((start, end))
        return intervals

    windows = [merged(value) for value in coverage.values()]
    if windows and any(value != windows[0] for value in windows[1:]):
        raise ValueError("Production types cover different intervals")
    return result


def _calc_carbon(generation: dict) -> dict:
    """
    Uretim tipi → karbon yogunlugu hesapla.
    """
    total_mwh = 0.0
    total_co2g = 0.0
    renewable_mwh = 0.0
    breakdown = {}

    for psr, mwh in generation.items():
        if mwh <= 0:
            continue
        ef = EMISSION_FACTORS.get(psr)
        if ef is None:
            continue
        name, factor = ef
        co2g = mwh * 1000 * factor
        total_mwh += mwh
        total_co2g += co2g
        if psr in RENEWABLE_TYPES:
            renewable_mwh += mwh
        breakdown[name] = {
            "mwh": round(mwh, 1),
            "factor": factor,
            "co2g": round(co2g, 1),
        }

    if total_mwh <= 0:
        return {
            "carbon_intensity": None,
            "breakdown": breakdown,
            "renewable_pct": 0,
            "total_mwh": 0,
        }

    return {
        "carbon_intensity": round(total_co2g / (total_mwh * 1000), 1),
        "renewable_pct": round(100 * renewable_mwh / total_mwh, 1),
        "total_mwh": round(total_mwh, 6),
        "estimate_basis": "generation_mix_emission_factors",
        "includes_imports": False,
        "breakdown": breakdown,
    }


def get_carbon_intensity(region: str) -> dict:
    """
    ENTSO-E'den gercek karbon yogunlugunu hesaplar.
    Basarisiz olursa None dondurur (CSV fallback tetiklenir).

    Donen dict:
      carbon_intensity : float | None
      renewable_pct    : float
      total_mwh        : float
      breakdown        : dict
      source           : str
      cached           : bool
    """
    if not ENTSOE_TOKEN:
        return {
            "carbon_intensity": None,
            "source": "ENTSO-E (no token)",
            "renewable_pct": 0,
            "breakdown": {},
            "total_mwh": 0,
            "cached": False,
        }

    cached = _cache_get(region)
    if cached:
        return {**cached, "cached": True}

    zone = ZONE_CODES.get(region)
    if not zone:
        return {
            "carbon_intensity": None,
            "source": "ENTSO-E (unknown region)",
            "renewable_pct": 0,
            "breakdown": {},
            "total_mwh": 0,
            "cached": False,
        }

    now = datetime.now(timezone.utc)
    # Son tamamlanan saati al (15 dk gecikme icin 1 saat geri git)
    start = (now - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    end = (now - timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    fmt = "%Y%m%d%H%M"

    params = {
        "documentType": "A75",  # ActualGenerationPerProductionType
        "processType": "A16",  # Realised
        "in_Domain": zone,
        "periodStart": start.strftime(fmt),
        "periodEnd": end.strftime(fmt),
    }

    try:
        xml_text = _entsoe_request(params)
        generation = _parse_generation_xml(xml_text)

        if not generation:
            return {
                "carbon_intensity": None,
                "source": "ENTSO-E (empty response — try different time window)",
                "renewable_pct": 0,
                "breakdown": {},
                "total_mwh": 0,
                "cached": False,
            }

        result = _calc_carbon(generation)
        result["source"] = "ENTSO-E generation-mix estimate"
        result["zone"] = zone
        result["period"] = f"{start.strftime('%H:%M')} — {end.strftime('%H:%M')} UTC"
        result["cached"] = False

        if result["carbon_intensity"] is not None:
            _cache_set(region, result)

        return result

    except urllib.error.HTTPError as e:
        logging.getLogger(__name__).warning(
            "carbon_provider_failed",
            extra={"provider": "entsoe", "region": region, "http_status": e.code},
        )
        msg = {
            401: "ENTSO-E: Gecersiz token — transparency.entsoe.eu'den yeni token alin",
            403: "ENTSO-E: Erisim reddedildi — token dogru ama bu endpoint icin izin yok",
            429: "ENTSO-E: Rate limit — 15 dk bekleyin",
            503: "ENTSO-E: Servis gecici olarak kullanilamiyor",
        }.get(e.code, f"ENTSO-E HTTP {e.code}")
        return {
            "carbon_intensity": None,
            "source": msg,
            "renewable_pct": 0,
            "breakdown": {},
            "total_mwh": 0,
            "cached": False,
        }

    except (OSError, ValueError, ET.ParseError) as e:
        logging.getLogger(__name__).warning(
            "carbon_provider_failed",
            extra={
                "provider": "entsoe",
                "region": region,
                "error_type": type(e).__name__,
            },
        )
        return {
            "carbon_intensity": None,
            "source": f"ENTSO-E unavailable ({type(e).__name__})",
            "renewable_pct": 0,
            "breakdown": {},
            "total_mwh": 0,
            "cached": False,
        }


def get_all_regions() -> dict:
    """4 bolge icin paralel ENTSO-E sorgusu."""
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = {r: ex.submit(get_carbon_intensity, r) for r in REGIONS}
        return {r: f.result() for r, f in futures.items()}
