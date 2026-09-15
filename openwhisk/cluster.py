"""
openwhisk/cluster.py — OpenWhisk bölge simülasyonu + gerçek wsk entegrasyonu

İki mod:
  USE_REAL_OW=False  →  Python simülasyonu (her ortamda çalışır, R2 planı)
  USE_REAL_OW=True   →  Gerçek wsk action invoke (deploy.sh çalıştırıldıktan sonra)

Ortam değişkeni: OPENWHISK_REAL=true  (varsayılan: false)
"""

import time
import random
import threading
import subprocess
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

from config import (
    OPENWHISK_REAL as USE_REAL_OW,
    OPENWHISK_HOST as OW_HOST,
    OPENWHISK_AUTH as OW_AUTH,
)

REGIONS = {
    "DE": {
        "label": "Germany (Frankfurt)",
        "base_latency": 18,
        "cold_start_p": 0.12,
        "cold_start_ms": (80, 250),
        "capacity": 50,
        "energy_source": "Mixed",
        "renewable_pct": 45,
    },
    "IE": {
        "label": "Ireland (Dublin)",
        "base_latency": 48,
        "cold_start_p": 0.08,
        "cold_start_ms": (60, 180),
        "capacity": 40,
        "energy_source": "Wind dominant",
        "renewable_pct": 72,
    },
    "FR": {
        "label": "France (Paris)",
        "base_latency": 22,
        "cold_start_p": 0.10,
        "cold_start_ms": (70, 200),
        "capacity": 45,
        "energy_source": "Nuclear + Wind",
        "renewable_pct": 78,
    },
    "PL": {
        "label": "Poland (Warsaw)",
        "base_latency": 32,
        "cold_start_p": 0.15,
        "cold_start_ms": (100, 300),
        "capacity": 30,
        "energy_source": "Coal dominant",
        "renewable_pct": 18,
    },
}

_state = {
    r: {"active": 0, "total": 0, "errors": 0, "capacity_exceeded": 0} for r in REGIONS
}
_lock = threading.Lock()


@dataclass
class InvocationResult:
    region: str
    region_label: str
    action_name: str
    function_type: str
    latency_ms: float
    cold_start: bool
    success: bool
    energy_source: str
    renewable_pct: int
    backend: str = "simulation"
    invoked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    error: Optional[str] = None


def _invoke_real_ow(region: str, action_name: str, params: dict) -> InvocationResult:
    cfg = REGIONS[region]
    started = time.perf_counter()
    error = None
    cold_start = False
    try:
        if not OW_AUTH:
            raise ValueError("OpenWhisk credentials are missing")
        payload = {**params, "action": action_name}
        with TemporaryDirectory(prefix="carbon-invoke-") as temp:
            param_file = Path(temp) / "params.json"
            param_file.write_text(json.dumps(payload), encoding="utf-8")
            proc = subprocess.run(
                [
                    "wsk",
                    "action",
                    "invoke",
                    f"carbon-worker-{region}",
                    "--param-file",
                    str(param_file),
                    "--blocking",
                    "--result",
                    "--apihost",
                    OW_HOST,
                    "--auth",
                    OW_AUTH,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        if proc.returncode != 0:
            raise RuntimeError("OpenWhisk invocation failed")
        data = json.loads(proc.stdout)
        if (
            not isinstance(data, dict)
            or data.get("success") is not True
            or data.get("error")
        ):
            raise ValueError("Invalid or failed action response")
        if data.get("region") != region:
            raise ValueError("Action returned a different region")
        cold_start = data.get("cold_start") is True
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as exc:
        error = "OpenWhisk invocation failed: " + type(exc).__name__
        logging.getLogger(__name__).warning(
            "openwhisk_invocation_failed",
            extra={"region": region, "error_type": type(exc).__name__},
        )
    with _lock:
        _state[region]["errors" if error else "total"] += 1
    return InvocationResult(
        region=region,
        region_label=cfg["label"],
        action_name=action_name,
        function_type=params.get("function_type", "standard"),
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        cold_start=cold_start,
        success=error is None,
        energy_source=cfg["energy_source"],
        renewable_pct=cfg["renewable_pct"],
        backend="openwhisk-real",
        error=error,
    )


def simulate_latency(region, function_type, rng):
    """Shared simulation model; injected RNG supports paired experiments."""
    cfg = REGIONS[region]
    base = cfg["base_latency"]
    jitter_draw, cold_draw, start_draw = rng.random(), rng.random(), rng.random()
    low, high = {"latency_sensitive": (-3, 5), "delay_tolerant": (0, base * 0.8)}.get(
        function_type, (-5, 12)
    )
    latency = base + low + (high - low) * jitter_draw
    cold = cold_draw < cfg["cold_start_p"]
    if cold:
        low, high = cfg["cold_start_ms"]
        latency += low + (high - low) * start_draw
    return round(max(latency, 1), 2), cold


def _invoke_simulated(region: str, action_name: str, params: dict) -> InvocationResult:
    """Python simülasyonu — her ortamda çalışır."""
    cfg = REGIONS[region]

    with _lock:
        if _state[region]["active"] >= cfg["capacity"]:
            _state[region]["errors"] += 1
            _state[region]["capacity_exceeded"] += 1
            return InvocationResult(
                region=region,
                region_label=cfg["label"],
                action_name=action_name,
                function_type=params.get("function_type", "standard"),
                latency_ms=0,
                cold_start=False,
                success=False,
                energy_source=cfg["energy_source"],
                renewable_pct=cfg["renewable_pct"],
                backend="simulation",
                error="Capacity exceeded",
            )
        _state[region]["active"] += 1

    try:
        ft = params.get("function_type", "standard")
        latency, cold_start = simulate_latency(region, ft, random)
        time.sleep(latency / 1000)

        with _lock:
            _state[region]["total"] += 1
        return InvocationResult(
            region=region,
            region_label=cfg["label"],
            action_name=action_name,
            function_type=ft,
            latency_ms=latency,
            cold_start=cold_start,
            success=True,
            energy_source=cfg["energy_source"],
            renewable_pct=cfg["renewable_pct"],
            backend="simulation",
        )

    except Exception as e:
        with _lock:
            _state[region]["errors"] += 1
        return InvocationResult(
            region=region,
            region_label=cfg["label"],
            action_name=action_name,
            function_type=params.get("function_type", "standard"),
            latency_ms=0,
            cold_start=False,
            success=False,
            energy_source=cfg["energy_source"],
            renewable_pct=cfg["renewable_pct"],
            backend="simulation",
            error=str(e),
        )
    finally:
        with _lock:
            _state[region]["active"] = max(0, _state[region]["active"] - 1)


def invoke(
    region: str, action_name: str, params: dict, function_type: str = "standard"
) -> InvocationResult:
    """
    Bölgeye fonksiyon invoke eder.
    OPENWHISK_REAL=true ise gerçek wsk, değilse simülasyon.
    """
    params = dict(params)
    params["function_type"] = function_type
    if USE_REAL_OW:
        return _invoke_real_ow(region, action_name, params)
    return _invoke_simulated(region, action_name, params)


def cluster_status() -> dict:
    with _lock:
        return {
            r: {
                "label": REGIONS[r]["label"],
                "active": _state[r]["active"],
                "capacity": REGIONS[r]["capacity"],
                "total": _state[r]["total"],
                "errors": _state[r]["errors"],
                "capacity_exceeded": _state[r]["capacity_exceeded"],
                "energy_source": REGIONS[r]["energy_source"],
                "renewable_pct": REGIONS[r]["renewable_pct"],
                "backend": "openwhisk-real" if USE_REAL_OW else "simulation",
            }
            for r in REGIONS
        }
