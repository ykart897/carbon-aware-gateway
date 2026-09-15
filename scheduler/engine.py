"""Immediate routing with separate, unrealized deferral recommendations."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from carbon_api.service import get_current
from config import REGIONS
from forecasting.arima import get_all_forecasts
from gateway.database import next_region
from gateway.metrics import calculate
from openwhisk.cluster import invoke
from optimizer.pareto import optimize

DEFER_THRESHOLD = 400


def _recommend(decision, forecasts, now):
    best = decision["carbon_intensity"]
    recommendation = None
    for region, forecast in forecasts.items():
        for i, value in enumerate(forecast["arima_forecast"]):
            timestamps = forecast.get("forecast_timestamps")
            if timestamps and datetime.fromisoformat(timestamps[i]) <= now:
                continue
            if value < best:
                best = value
                at = (
                    timestamps[i]
                    if timestamps
                    else (
                        now.replace(minute=0, second=0, microsecond=0)
                        + timedelta(hours=i + 1)
                    ).isoformat()
                )
                recommendation = {
                    "region": region,
                    "scheduled_at": at,
                    "predicted_carbon": value,
                    "current_carbon": decision["carbon_intensity"],
                    "threshold": DEFER_THRESHOLD,
                    "status": "recommendation_only",
                    "data_source": forecast.get("data_source", "unknown"),
                    "model_used": forecast.get("model_used", "ARIMA approximation"),
                }
    return recommendation


def route_request(
    action,
    params,
    function_type="standard",
    scheduler="carbon_aware",
    method="weighted_sum",
    *,
    snapshot=None,
    forecasts=None,
    now=None,
    invoker=None,
    rr_region=None,
):
    snap = snapshot if snapshot is not None else get_current()
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    if scheduler == "carbon_aware":
        decision = optimize(snap, method)
        region = decision["selected_region"]
    else:
        if scheduler == "round_robin":
            region = rr_region if rr_region is not None else next_region()
        elif scheduler == "latency_only":
            region = min(REGIONS, key=lambda r: snap["regions"][r]["latency_ms"])
        else:
            raise ValueError("Unknown scheduler")
        data = snap["regions"][region]
        decision = {
            "selected_region": region,
            "region_label": data["label"],
            "carbon_intensity": data["carbon_intensity"],
            "latency_ms": data["latency_ms"],
            "carbon_score": None,
            "pareto_front": [],
            "all_solutions": [],
            "sla_ms": None,
            "sla_satisfied": None,
            "sla_basis": None,
        }
    recommendation = None
    if (
        scheduler == "carbon_aware"
        and function_type == "delay_tolerant"
        and decision["carbon_intensity"] > DEFER_THRESHOLD
    ):
        forecast_data = (
            forecasts if forecasts is not None else get_all_forecasts(steps=6)
        )
        recommendation = _recommend(decision, forecast_data, now)
    result = (invoker or invoke)(region, action, params, function_type)
    metrics = calculate(snap, region, result.success)
    decision.update(metrics)
    source = snap["regions"][region].get("source", snap.get("source", "unknown"))
    return {
        "scheduler": scheduler,
        "method": method if scheduler == "carbon_aware" else scheduler,
        "function_type": function_type,
        "action": action,
        "exec_mode": "immediate",
        "defer_info": None,
        "deferral_recommendation": recommendation,
        "decision": decision,
        "invocation": asdict(result),
        "backend": result.backend,
        "data_source": source,
        "snapshot_timestamp": snap.get("timestamp"),
        "sla_satisfied": decision["sla_satisfied"],
        **metrics,
    }


def carbon_aware(
    action, params, function_type="standard", method="weighted_sum", **kwargs
):
    return route_request(
        action, params, function_type, "carbon_aware", method, **kwargs
    )


def round_robin(action, params, function_type="standard", **kwargs):
    return route_request(action, params, function_type, "round_robin", **kwargs)


def latency_only(action, params, function_type="standard", **kwargs):
    return route_request(action, params, function_type, "latency_only", **kwargs)
