"""Carbon snapshots from optional live providers or repeating sample CSV profiles.
CSV files have unverified provenance and do not represent current measurements."""

import csv
import os
import time
import threading
import logging
import math
from datetime import datetime, timedelta, timezone

from openwhisk.cluster import REGIONS as CLUSTER_REGIONS
from config import REGIONS
from carbon_api.entsoe import get_carbon_intensity as entsoe_get

from config import (
    ENTSOE_API_KEY as ENTSOE_TOKEN,
    ELECTRICITY_MAPS_API_KEY as EM_KEY,
    USE_LIVE_API as USE_EM_API,
)

CACHE_TTL = 300

_DIR = os.path.dirname(__file__)
_HOURLY = os.path.join(_DIR, "..", "data", "carbon_hourly.csv")
_WEEKLY = os.path.join(_DIR, "..", "data", "carbon_weekly.csv")


# CSV yukle
def _load_hourly():
    d = {}
    with open(_HOURLY, newline="") as f:
        for row in csv.DictReader(f):
            h = int(row["hour"])
            d[h] = {r: float(row[r]) for r in REGIONS}
    return d


def _load_weekly():
    rows = []
    if os.path.exists(_WEEKLY):
        with open(_WEEKLY, newline="") as f:
            for row in csv.DictReader(f):
                rows.append(
                    {
                        "hour": int(row["hour"]),
                        "day": int(row["day"]),
                        **{r: float(row[r]) for r in REGIONS},
                    }
                )
    return rows


_HOURLY_DATA = _load_hourly()
_WEEKLY_DATA = _load_weekly()

# Cache
_lock = threading.Lock()
_cache = {}


def _cache_get(region):
    with _lock:
        e = _cache.get(region)
        if e and (time.time() - e["ts"]) < CACHE_TTL:
            return e
    return None


def _cache_set(region, val, src, extra=None):
    with _lock:
        _cache[region] = {
            "value": val,
            "source": src,
            "extra": extra or {},
            "ts": time.time(),
        }


# ElectricityMaps (ikincil)
def _fetch_em(zone):
    try:
        import json
        import urllib.request
        from datetime import timezone

        now = datetime.now(timezone.utc)
        url = (
            f"https://api.electricitymaps.com/v4/carbon-intensity/past"
            f"?zone={zone}&datetime={now.strftime('%Y-%m-%dT%H:00Z')}"
        )
        req = urllib.request.Request(url, headers={"auth-token": EM_KEY})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read())
            val = data.get("carbonIntensity")
            if val is None:
                val = data.get("data", {}).get("carbonIntensity")
            value = float(val)
            if not math.isfinite(value) or value < 0:
                raise ValueError("Invalid carbon intensity")
            return value
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        logging.getLogger(__name__).warning(
            "carbon_provider_failed",
            extra={
                "provider": "electricitymaps",
                "region": zone,
                "error_type": type(exc).__name__,
            },
        )
        return None


# CSV fallback
def _csv_value(region, at=None):
    at = at if at is not None else datetime.now(timezone.utc)
    if _WEEKLY_DATA:
        for row in _WEEKLY_DATA:
            if row["hour"] == at.hour and row["day"] == at.weekday():
                return row[region], "CSV repeated weekly sample profile"
    return _HOURLY_DATA[at.hour][region], "CSV repeated hourly sample profile"


# Ana fonksiyon
def get_current() -> dict:
    hour = datetime.now(timezone.utc).hour
    regions = {}

    for r in REGIONS:
        cached = _cache_get(r)
        if cached:
            intensity = cached["value"]
            source = cached["source"]
            extra = cached.get("extra", {})
        else:
            intensity = None
            extra = {}

            # 1. ENTSO-E (gercek veri)
            if ENTSOE_TOKEN:
                res = entsoe_get(r)
                if res["carbon_intensity"] is not None:
                    intensity = res["carbon_intensity"]
                    source = res["source"]
                    extra = {
                        "renewable_pct": res["renewable_pct"],
                        "total_mwh": res["total_mwh"],
                        "breakdown": res.get("breakdown", {}),
                        "period": res.get("period", ""),
                    }

            # 2. ElectricityMaps
            if intensity is None and USE_EM_API and EM_KEY:
                val = _fetch_em(r)
                if val is not None:
                    intensity = val
                    source = "ElectricityMaps Live API"

            # 3. CSV fallback
            if intensity is None:
                intensity, source = _csv_value(r)

            _cache_set(r, intensity, source, extra)

        meta = CLUSTER_REGIONS[r]
        regions[r] = {
            "carbon_intensity": intensity,
            "label": meta["label"],
            "latency_ms": meta["base_latency"],
            "energy_source": meta["energy_source"],
            "renewable_pct": extra.get("renewable_pct", meta["renewable_pct"]),
            "source": source,
            "entsoe_detail": extra,  # bos dict ise CSV modu
        }

    # data_mode: token varsa ve tum bolgelerde entsoe_detail doluysa "real"
    has_token = bool(ENTSOE_TOKEN)
    real_count = sum(
        1
        for v in regions.values()
        if v.get("entsoe_detail") and v["entsoe_detail"].get("total_mwh", 0) > 0
    )
    em_count = sum(1 for v in regions.values() if "ElectricityMaps Live" in v["source"])
    live_total = real_count + em_count
    overall_src = (
        "ENTSO-E generation-mix estimate"
        if real_count == 4
        else f"Mixed ({live_total}/4 live)"
        if live_total > 0
        else "CSV repeated sample profile"
    )
    data_mode = "real" if real_count == 4 else ("mixed" if live_total > 0 else "csv")

    return {
        "hour": hour,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": overall_src,
        "data_mode": data_mode,
        "entsoe_active": has_token,
        "regions": regions,
    }


def get_history(region: str, hours: int = 48, *, now=None) -> list:
    """Completed UTC hours sampled from a repeating profile, not measured history."""
    if region not in REGIONS:
        raise ValueError("Unknown region")
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    end = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    result = []
    for offset in range(-hours, 0):
        at = end + timedelta(hours=offset)
        value, source = _csv_value(region, at)
        result.append(
            {
                "hour": at.hour,
                "offset": offset,
                "timestamp": at.isoformat(),
                "carbon_intensity": value,
                "source": source,
            }
        )
    return result
