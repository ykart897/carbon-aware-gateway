import random
import time


def main(params):
    latency_ms = float(params["base_latency"]) + random.uniform(-5, 10)
    cold_start = random.random() < 0.12
    if cold_start:
        latency_ms += random.uniform(80, 200)

    time.sleep(max(latency_ms, 1) / 1000)
    return {
        "region": params["region"],
        "carbon_intensity": round(
            float(params["base_carbon"]) + random.uniform(-20, 20), 1
        ),
        "latency_ms": round(latency_ms, 2),
        "cold_start": cold_start,
        "energy_source": params["energy_source"],
        "action": params.get("action", "unknown"),
        "timestamp": time.time(),
        "success": True,
    }
