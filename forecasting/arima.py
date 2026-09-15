"""Lightweight deterministic ARIMA approximation with a heuristic differencing order.
Point forecasts and held-out error evaluation are separate; no calibrated intervals."""

import math
from carbon_api.service import get_history
from datetime import datetime, timedelta


# ── İstatistik yardımcıları ───────────────────────────────────────
def _diff(s):
    return [s[i] - s[i - 1] for i in range(1, len(s))]


def _mean(s):
    return sum(s) / len(s) if s else 0.0


def _std(s):
    if len(s) < 2:
        return 0.0
    m = _mean(s)
    return math.sqrt(sum((x - m) ** 2 for x in s) / (len(s) - 1))


def _mae(a, p):
    n = min(len(a), len(p))
    return round(sum(abs(a[i] - p[i]) for i in range(n)) / n, 3) if n else None


def _rmse(a, p):
    n = min(len(a), len(p))
    return (
        round(math.sqrt(sum((a[i] - p[i]) ** 2 for i in range(n)) / n), 3)
        if n
        else None
    )


# ── Stationarity kontrolü (basit ADF proxy) ───────────────────────
def _is_stationary(s, threshold=0.05) -> bool:
    """
    Basit otokorelasyon-tabanlı stationarity testi.
    Lag-1 otokorelasyonu düşükse (|r1| < 0.8) durağan kabul edilir.
    Gerçek ADF için statsmodels gerekir — burada lightweight proxy.
    """
    if len(s) < 4:
        return True
    m = _mean(s)
    var = sum((x - m) ** 2 for x in s)
    if var == 0:
        return True
    r1 = sum((s[i] - m) * (s[i - 1] - m) for i in range(1, len(s))) / var
    return abs(r1) < 0.8


# ── MA(1) theta tahmini (iteratif yaklaşım) ───────────────────────
def _estimate_theta(residuals, max_iter=20) -> float:
    """
    Hannan-Rissanen ile MA(1) katsayısı tahmini.
    Başarısız olursa -0.3 varsayılan döner.
    """
    if len(residuals) < 4:
        return -0.3
    try:
        theta = -0.3  # başlangıç
        for _ in range(max_iter):
            eps = [0.0] * len(residuals)
            for t in range(1, len(residuals)):
                eps[t] = residuals[t] - theta * eps[t - 1]
            # theta güncelle: OLS adımı
            num = sum(eps[t - 1] * residuals[t] for t in range(1, len(residuals)))
            den = sum(eps[t - 1] ** 2 for t in range(1, len(residuals)))
            if den == 0:
                break
            new_theta = num / den
            if abs(new_theta - theta) < 1e-6:
                break
            theta = max(-0.99, min(0.99, new_theta))  # invertibility
        return round(theta, 4)
    except Exception:
        return -0.3


# ── Moving average (baseline karşılaştırma için) ──────────────────
def moving_average(series, steps=6, window=6):
    ext = list(series)
    out = []
    for _ in range(steps):
        out.append(round(_mean(ext[-window:]), 1))
        ext.append(out[-1])
    return out


# ── ARIMA(2,1,1) ─────────────────────────────────────────────────
def _predict(series, steps=6):
    """Point prediction with first or second differencing; short series use the last value."""

    # Yeterli veri yoksa son değeri tekrar et
    if len(series) < 4:
        fc = [round(series[-1], 1) if series else 0.0] * steps
        return {
            "forecasts": fc,
            "mae": None,
            "rmse": None,
            "phi1": 0.0,
            "phi2": 0.0,
            "theta": -0.3,
            "stationary": True,
        }

    # Stationarity kontrolü; gerekirse 2. fark al
    d1 = _diff(series)
    last_delta = d1[-1]
    stationary = _is_stationary(d1)
    if not stationary:
        d1 = _diff(d1)  # I(2) — nadir ama güvenlik için

    n = len(d1)
    m = _mean(d1)
    var = sum((x - m) ** 2 for x in d1) / n if n > 0 else 1.0

    # AR(2) — Yule-Walker
    if n > 2 and var > 0:
        r1 = sum((d1[i] - m) * (d1[i - 1] - m) for i in range(1, n)) / (n * var)
        r2 = sum((d1[i] - m) * (d1[i - 2] - m) for i in range(2, n)) / (n * var)
    else:
        r1 = r2 = 0.0

    dn = 1 - r1**2 or 1.0
    phi1 = (r1 * (1 - r2)) / dn
    phi2 = (r2 - r1**2) / dn

    # Stationarity sınırı (AR polinom kökleri birim çember dışında olmalı)
    phi1 = max(-1.8, min(1.8, phi1))
    phi2 = max(-0.9, min(0.9, phi2))

    # MA(1) — iteratif tahmin
    residuals = [0.0, 0.0] + [
        d1[i] - (m + phi1 * (d1[i - 1] - m) + phi2 * (d1[i - 2] - m))
        for i in range(2, n)
    ]
    theta = _estimate_theta(residuals)

    # Tahmin
    de = list(d1)
    re = list(residuals)
    last = series[-1]
    fc = []

    for _ in range(steps):
        ar_term = m + phi1 * (de[-1] - m) + phi2 * ((de[-2] if len(de) >= 2 else m) - m)
        ma_term = theta * (re[-1] if re else 0.0)
        pd = ar_term + ma_term
        if not stationary:
            last_delta += pd
            po = max(0.0, last + last_delta)
        else:
            po = max(0.0, last + pd)
        fc.append(round(po, 1))
        de.append(pd)
        re.append(0.0)
        last = po

    return {
        "forecasts": fc,
        "mae": None,
        "rmse": None,
        "phi1": round(phi1, 4),
        "phi2": round(phi2, 4),
        "theta": round(theta, 4),
        "stationary": stationary,
        "method": "ARIMA(2,1,1)" if stationary else "ARIMA(2,2,1)",
    }


# ── Public API ───────────────────────────────────────────────────
def arima_forecast(series, steps=6, seed=None):
    """Deterministic point forecast; seed is retained for API compatibility."""
    result = _predict(series, steps)
    result.setdefault("method", "last_value")
    result["model_used"] = result["method"]
    if len(series) >= 12:
        predicted = _predict(series[:-6], 6)["forecasts"]
        result["mae"] = _mae(series[-6:], predicted)
        result["rmse"] = _rmse(series[-6:], predicted)
    return result


def forecast_times(history, steps):
    last = datetime.fromisoformat(history[-1]["timestamp"])
    return [(last + timedelta(hours=i + 1)).isoformat() for i in range(steps)]


def get_forecast(region: str, steps: int = 6, seed: int = 42) -> dict:
    history = get_history(region, 48)
    series = [h["carbon_intensity"] for h in history]
    ar = arima_forecast(series, steps, seed=seed)
    timestamps = forecast_times(history, steps)
    return {
        "region": region,
        "method": ar["method"],
        "model_used": ar["model_used"],
        "steps": steps,
        "forecast_timestamps": timestamps,
        "forecast_hours": [datetime.fromisoformat(t).hour for t in timestamps],
        "last_observation_at": history[-1]["timestamp"],
        "data_source": history[-1]["source"],
        "arima_forecast": ar["forecasts"],
        "ma_forecast": moving_average(series, steps),
        "metrics": {"mae": ar["mae"], "rmse": ar["rmse"]},
        "model_params": {
            key: ar[key] for key in ("phi1", "phi2", "theta", "stationary")
        },
    }


def get_all_forecasts(steps: int = 6, seed: int = 42) -> dict:
    from config import REGIONS

    return {r: get_forecast(r, steps, seed=seed) for r in REGIONS}
