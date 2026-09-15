"""Weighted sum, Pareto front and epsilon selection on one supplied snapshot."""

from dataclasses import dataclass
from typing import List
from gateway.metrics import calculate

ALPHA = 0.7  # karbon ağırlığı
BETA = 0.3  # gecikme ağırlığı
SLA_MS = 150  # ε-constraint latency SLA (ms)


@dataclass
class Sol:
    region: str
    label: str
    carbon: float
    latency: float
    cn: float
    ln: float
    score: float
    rank: int = 0
    dominated: bool = False


def _norm(v, lo, hi):
    return (v - lo) / (hi - lo) if hi != lo else 0.0


def _dominates(a: Sol, b: Sol) -> bool:
    return (
        a.carbon <= b.carbon
        and a.latency <= b.latency
        and (a.carbon < b.carbon or a.latency < b.latency)
    )


def _compute_pareto(sols: List[Sol]) -> List[Sol]:
    """
    Pareto dominance hesapla; rank ve dominated flag'lerini set et.
    Döndürülen liste tüm çözümleri içerir (yalnızca front değil).
    """
    for s in sols:
        s.dominated = False
        s.rank = 0

    for s in sols:
        s.dominated = any(_dominates(o, s) for o in sols if o is not s)

    # Rank-1 = Pareto front (non-dominated)
    front = [s for s in sols if not s.dominated]
    for s in front:
        s.rank = 1

    return front


def optimize(snap: dict, method: str = "weighted_sum", sla: float = SLA_MS) -> dict:
    regs = snap["regions"]
    cv = {r: regs[r]["carbon_intensity"] for r in regs}
    lv = {r: regs[r]["latency_ms"] for r in regs}

    cmin, cmax = min(cv.values()), max(cv.values())
    lmin, lmax = min(lv.values()), max(lv.values())

    sols = [
        Sol(
            region=r,
            label=regs[r]["label"],
            carbon=cv[r],
            latency=lv[r],
            cn=round(_norm(cv[r], cmin, cmax), 4),
            ln=round(_norm(lv[r], lmin, lmax), 4),
            score=round(
                ALPHA * _norm(cv[r], cmin, cmax) + BETA * _norm(lv[r], lmin, lmax), 4
            ),
        )
        for r in regs
    ]

    # Pareto analizi — tek seferlik
    front = _compute_pareto(sols)

    if method == "weighted_sum":
        sel = min(sols, key=lambda s: s.score)

    elif method == "pareto":
        # Yalnızca front içinden en iyi weighted-sum seç
        sel = (
            min(front, key=lambda s: s.score)
            if front
            else min(sols, key=lambda s: s.score)
        )

    elif method == "epsilon":
        feasible = [s for s in sols if s.latency <= sla]
        sel = (
            min(feasible, key=lambda s: s.carbon)
            if feasible
            else min(sols, key=lambda s: s.latency)
        )
    else:
        raise ValueError("Unknown optimization method")

    return {
        "method": method,
        "selected_region": sel.region,
        "region_label": sel.label,
        "carbon_intensity": sel.carbon,
        "latency_ms": sel.latency,
        "carbon_score": sel.score,
        **calculate(snap, sel.region),
        "snapshot_hour": snap["hour"],
        "all_solutions": [
            {
                "region": s.region,
                "label": s.label,
                "carbon": s.carbon,
                "latency": s.latency,
                "carbon_norm": s.cn,
                "latency_norm": s.ln,
                "score": s.score,
                "pareto_rank": s.rank,
                "dominated": s.dominated,
            }
            for s in sols
        ],
        "pareto_front": [
            {"region": s.region, "carbon": s.carbon, "latency": s.latency}
            for s in sols
            if not s.dominated
        ],
        "sla_ms": sla if method == "epsilon" else None,
        "sla_satisfied": sel.latency <= sla if method == "epsilon" else None,
        "sla_basis": "estimated_base_latency" if method == "epsilon" else None,
    }
