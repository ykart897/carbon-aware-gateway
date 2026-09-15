"""Estimated emissions relative to uniform round-robin on the same snapshot."""

from config import ENERGY_KWH_PER_REQUEST, REGIONS

METRIC_VERSION = 2


def calculate(snapshot, region, success=True, energy_kwh=ENERGY_KWH_PER_REQUEST):
    baseline = sum(snapshot["regions"][r]["carbon_intensity"] for r in REGIONS) / len(
        REGIONS
    )
    carbon = snapshot["regions"][region]["carbon_intensity"]
    return {
        "metric_version": METRIC_VERSION,
        "metric_kind": "estimated",
        "energy_kwh_per_request": energy_kwh,
        "baseline_carbon": baseline,
        "carbon_saved_g": round((baseline - carbon) * energy_kwh, 5)
        if success
        else None,
    }
