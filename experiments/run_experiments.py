"""Paired, offline experiments using the application's routing and latency models."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from carbon_api.service import get_history
from config import REGIONS
from forecasting.arima import arima_forecast, forecast_times
from forecasting.prophet_model import prophet_forecast
from openwhisk.cluster import REGIONS as CLUSTERS, InvocationResult, simulate_latency
from optimizer.pareto import optimize
from scheduler.engine import route_request

SCHEMA_VERSION = 3
SCHEDULERS = ("carbon_aware", "round_robin", "latency_only")
FUNCTION_TYPES = ("standard", "latency_sensitive", "delay_tolerant")
DEFAULT_OUTPUT = Path(__file__).parent / "output"
START = datetime(2026, 1, 5, tzinfo=timezone.utc)


def paired_test(first, second):
    import numpy as np
    from scipy import stats

    if len(first) != len(second):
        raise ValueError("Paired samples must have equal length")
    difference = np.asarray(first, dtype=float) - np.asarray(second, dtype=float)
    result = {
        "n": len(first),
        "test": "scipy.stats.ttest_rel",
        "t_statistic": None,
        "p_value": None,
        "mean_difference": float(difference.mean()) if len(first) else None,
        "reason": None,
    }
    if len(first) < 2:
        result["reason"] = "fewer_than_two_pairs"
    elif not np.isfinite(difference).all():
        raise ValueError("Non-finite paired data")
    elif np.allclose(difference, difference[0], rtol=1e-12, atol=1e-12):
        result["reason"] = "constant_paired_differences"
    else:
        test = stats.ttest_rel(first, second, nan_policy="raise")
        result.update(t_statistic=float(test.statistic), p_value=float(test.pvalue))
    return result


def summarize(rows):
    import numpy as np

    groups = []
    for scheduler in SCHEDULERS:
        for function_type in FUNCTION_TYPES:
            selected = [
                row
                for row in rows
                if row["scheduler"] == scheduler
                and row["function_type"] == function_type
            ]
            successful = [row for row in selected if row["invocation"]["success"]]
            groups.append(
                {
                    "scheduler": scheduler,
                    "function_type": function_type,
                    "requests": len(selected),
                    "successful": len(successful),
                    "mean_carbon": float(
                        np.mean([r["decision"]["carbon_intensity"] for r in successful])
                    )
                    if successful
                    else None,
                    "mean_latency_ms": float(
                        np.mean([r["invocation"]["latency_ms"] for r in successful])
                    )
                    if successful
                    else None,
                    "estimated_saved_g": round(
                        sum(r["carbon_saved_g"] for r in successful), 5
                    ),
                    "recommendations": sum(
                        r["deferral_recommendation"] is not None for r in selected
                    ),
                }
            )
    return groups


def run(seed=42, samples=50):
    if samples < 1:
        raise ValueError("samples must be positive")
    rng = random.Random(seed)
    workloads, rows = [], []
    for index in range(samples):
        now = START + timedelta(hours=index)
        history = {
            region: get_history(region, 48, now=now + timedelta(hours=1))
            for region in REGIONS
        }
        snapshot = {
            "hour": now.hour,
            "timestamp": now.isoformat(),
            "source": "CSV repeated sample profile",
            "regions": {
                region: {
                    "label": CLUSTERS[region]["label"],
                    "carbon_intensity": history[region][-1]["carbon_intensity"],
                    "latency_ms": CLUSTERS[region]["base_latency"],
                    "source": history[region][-1]["source"],
                }
                for region in REGIONS
            },
        }
        forecasts = {}
        for region in REGIONS:
            forecast = arima_forecast(
                [r["carbon_intensity"] for r in history[region]], 6
            )
            forecasts[region] = {
                "arima_forecast": forecast["forecasts"],
                "forecast_timestamps": forecast_times(history[region], 6),
                "data_source": history[region][-1]["source"],
                "model_used": forecast["model_used"],
            }
        invocation_seed = rng.randrange(2**63)
        action = rng.choice(("image_resize", "data_export", "api_sync", "db_backup"))
        workloads.append(
            {
                "sample_id": index,
                "snapshot": snapshot,
                "action": action,
                "invocation_seed": invocation_seed,
            }
        )
        for function_type in FUNCTION_TYPES:
            for scheduler in SCHEDULERS:

                def invoke(region, action, params, ft):
                    latency, cold = simulate_latency(
                        region, ft, random.Random(invocation_seed)
                    )
                    cfg = CLUSTERS[region]
                    return InvocationResult(
                        region,
                        cfg["label"],
                        action,
                        ft,
                        latency,
                        cold,
                        True,
                        cfg["energy_source"],
                        cfg["renewable_pct"],
                        backend="simulation",
                        invoked_at=now.isoformat(),
                    )

                result = route_request(
                    action,
                    {"sample_id": index},
                    function_type,
                    scheduler,
                    snapshot=snapshot,
                    forecasts=forecasts,
                    now=now,
                    invoker=invoke,
                    rr_region=REGIONS[index % len(REGIONS)],
                )
                recommendation = result["deferral_recommendation"]
                result["unrealized_recommendation_savings_g"] = (
                    round(
                        (
                            recommendation["current_carbon"]
                            - recommendation["predicted_carbon"]
                        )
                        * result["energy_kwh_per_request"],
                        5,
                    )
                    if recommendation
                    else None
                )
                rows.append({"sample_id": index, **result})
    comparisons = []
    for ft in FUNCTION_TYPES:
        for other in SCHEDULERS[1:]:
            for metric in ("carbon", "latency"):

                def values(scheduler):
                    selected = [
                        r
                        for r in rows
                        if r["function_type"] == ft and r["scheduler"] == scheduler
                    ]
                    return [
                        r["decision"]["carbon_intensity"]
                        if metric == "carbon"
                        else r["invocation"]["latency_ms"]
                        for r in selected
                    ]

                comparisons.append(
                    {
                        "function_type": ft,
                        "first": "carbon_aware",
                        "second": other,
                        "metric": metric,
                        **paired_test(values("carbon_aware"), values(other)),
                    }
                )
    forecasting = {}
    for region in REGIONS:
        history = get_history(region, 48, now=START)
        series = [h["carbon_intensity"] for h in history]
        forecasting[region] = {
            "arima": arima_forecast(series, 6),
            "prophet": prophet_forecast(
                series, 6, last_observation=history[-1]["timestamp"]
            ),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "seed": seed,
            "samples": samples,
            "backend": "simulation",
            "start_utc": START.isoformat(),
            "data_source": "CSV repeated sample profile",
            "paired_design": "same workload, snapshot and random draws across strategies",
            "limitations": "Synthetic profile; simulated latency; correlated hourly samples; exploratory unadjusted paired p-values; no measured energy or realized deferral savings.",
        },
        "workloads": workloads,
        "invocations": rows,
        "summary": summarize(rows),
        "comparisons": comparisons,
        "forecasting": forecasting,
        "pareto_example": optimize(workloads[0]["snapshot"], "pareto"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--samples",
        type=int,
        default=50,
        help="paired workloads per function type and scheduler",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    result = run(args.seed, args.samples)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "experiment_results.json"
    path.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
