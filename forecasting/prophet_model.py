"""Optional Prophet point forecasts with an explicitly named smoothing fallback."""

import logging
from datetime import datetime, timedelta, timezone

from carbon_api.service import get_history
from config import REGIONS
from forecasting.arima import _mae, _rmse, arima_forecast, forecast_times

PROPHET_OPTIONS = {
    "yearly_seasonality": False,
    "weekly_seasonality": False,
    "daily_seasonality": True,
    "seasonality_mode": "additive",
    "changepoint_prior_scale": 0.05,
    "interval_width": 0.80,
    "uncertainty_samples": 0,
}


def _exp_smoothing_series(series, steps, alpha=0.3):
    if not series:
        return [0.0] * steps
    level = series[0]
    for value in series[1:]:
        level = alpha * value + (1 - alpha) * level
    return [round(max(level, 0), 1)] * steps


def _exp_smoothing_fallback(series, steps, error=None):
    mae = rmse = None
    if len(series) >= 12:
        predicted = _exp_smoothing_series(series[:-6], 6)
        mae, rmse = _mae(series[-6:], predicted), _rmse(series[-6:], predicted)
    return {
        "forecasts": _exp_smoothing_series(series, steps),
        "lower_bound": None,
        "upper_bound": None,
        "mae": mae,
        "rmse": rmse,
        "changepoints": 0,
        "method": "exponential_smoothing",
        "model_used": "exponential_smoothing",
        "fallback_reason": error or "prophet_unavailable",
        "interval_method": None,
    }


def prophet_forecast(series: list, steps: int = 6, *, last_observation=None) -> dict:
    if len(series) < 6:
        return _exp_smoothing_fallback(series, steps, "insufficient_history")
    try:
        from prophet import Prophet
        import pandas as pd
    except ImportError:
        return _exp_smoothing_fallback(series, steps)
    last = last_observation or datetime.now(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    )
    if isinstance(last, str):
        last = datetime.fromisoformat(last)
    if last.tzinfo is None:
        raise ValueError("last_observation must be timezone-aware")
    # Prophet expects naive ds values; these values represent UTC.
    last = last.astimezone(timezone.utc).replace(tzinfo=None)
    dates = [last - timedelta(hours=len(series) - i - 1) for i in range(len(series))]
    try:
        frame = pd.DataFrame({"ds": dates, "y": series})
        mae = rmse = None
        if len(series) >= 12:
            evaluation = Prophet(**PROPHET_OPTIONS)
            evaluation.fit(frame.iloc[:-6], seed=42)
            prediction = evaluation.predict(frame.iloc[-6:][["ds"]])
            values = list(prediction["yhat"].clip(lower=0).round(1))
            mae, rmse = _mae(series[-6:], values), _rmse(series[-6:], values)
        model = Prophet(**PROPHET_OPTIONS)
        model.fit(frame, seed=42)
        future = pd.DataFrame(
            {"ds": [last + timedelta(hours=i + 1) for i in range(steps)]}
        )
        prediction = model.predict(future)
        deltas = model.params["delta"].mean(axis=0)
        changepoints = sum(abs(float(delta)) > 0.01 for delta in deltas)
        return {
            "forecasts": list(prediction["yhat"].clip(lower=0).round(1)),
            "lower_bound": None,
            "upper_bound": None,
            "mae": mae,
            "rmse": rmse,
            "changepoints": changepoints,
            "method": "Prophet (daily seasonality)",
            "model_used": "prophet",
            "fallback_reason": None,
            "interval_method": None,
        }
    except (ValueError, RuntimeError, OSError) as exc:
        logging.getLogger(__name__).warning(
            "forecast_model_failed",
            extra={"model": "prophet", "error_type": type(exc).__name__},
        )
        return _exp_smoothing_fallback(series, steps, type(exc).__name__)


def get_prophet_forecast(region: str, steps: int = 6) -> dict:
    history = get_history(region, 48)
    series = [h["carbon_intensity"] for h in history]
    prophet = prophet_forecast(series, steps, last_observation=history[-1]["timestamp"])
    arima = arima_forecast(series, steps)
    p_mae, a_mae = prophet["mae"], arima["mae"]
    best = None
    if p_mae is not None and a_mae is not None:
        best = (
            "tie"
            if p_mae == a_mae
            else prophet["model_used"]
            if p_mae < a_mae
            else arima["model_used"]
        )
    timestamps = forecast_times(history, steps)
    return {
        "region": region,
        "steps": steps,
        "forecast_timestamps": timestamps,
        "forecast_hours": [datetime.fromisoformat(t).hour for t in timestamps],
        "last_observation_at": history[-1]["timestamp"],
        "data_source": history[-1]["source"],
        "prophet": prophet,
        "arima": arima,
        "best_model": best,
        "comparison_basis": "last six observations held out from the sample profile",
    }


def get_all_prophet_forecasts(steps: int = 6) -> dict:
    return {r: get_prophet_forecast(r, steps) for r in REGIONS}
