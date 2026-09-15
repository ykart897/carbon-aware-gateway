"""SQLite persistence; legacy rows are retained outside current success metrics."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3

from config import DATABASE_PATH, REGIONS
from gateway.metrics import METRIC_VERSION

DB = DATABASE_PATH


@contextmanager
def connection():
    conn = sqlite3.connect(DB, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init():
    with connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS routing_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, action TEXT, function_type TEXT, scheduler TEXT,
            opt_method TEXT, selected_region TEXT, region_label TEXT,
            carbon_intensity REAL, latency_ms REAL, carbon_score REAL,
            exec_mode TEXT, cold_start INTEGER DEFAULT 0, renewable_pct REAL,
            carbon_saved_g REAL, success INTEGER DEFAULT 1
        )""")
        existing = {
            row["name"] for row in conn.execute("PRAGMA table_info(routing_log)")
        }
        columns = {
            "renewable_pct": "REAL",
            "carbon_saved_g": "REAL",
            "exec_mode": "TEXT",
            "cold_start": "INTEGER DEFAULT 0",
            "metric_version": "INTEGER",
            "baseline_carbon": "REAL",
            "energy_kwh_per_request": "REAL",
            "backend": "TEXT",
            "data_source": "TEXT",
            "deferral_recommendation": "TEXT",
            "sla_satisfied": "INTEGER",
            "error": "TEXT",
        }
        for name, sql_type in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE routing_log ADD COLUMN {name} {sql_type}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_routing_log_scheduler ON routing_log(scheduler)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS rr_state (id INTEGER PRIMARY KEY, counter INTEGER DEFAULT 0)"
        )


def next_region():
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS rr_state (id INTEGER PRIMARY KEY, counter INTEGER DEFAULT 0)"
        )
        conn.execute("INSERT OR IGNORE INTO rr_state (id, counter) VALUES (1, 0)")
        index = conn.execute("SELECT counter FROM rr_state WHERE id=1").fetchone()[0]
        conn.execute(
            "UPDATE rr_state SET counter=? WHERE id=1", ((index + 1) % len(REGIONS),)
        )
        return REGIONS[index % len(REGIONS)]


def log(result):
    decision, invocation = result["decision"], result["invocation"]
    if decision["selected_region"] != invocation["region"]:
        raise ValueError("Decision and invocation regions differ")
    recommendation = result["deferral_recommendation"]
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": result["action"],
        "function_type": result["function_type"],
        "scheduler": result["scheduler"],
        "opt_method": result["method"],
        "selected_region": invocation["region"],
        "region_label": decision["region_label"],
        "carbon_intensity": decision["carbon_intensity"],
        "latency_ms": invocation["latency_ms"],
        "carbon_score": decision.get("carbon_score"),
        "exec_mode": result["exec_mode"],
        "cold_start": int(invocation["cold_start"]),
        "renewable_pct": invocation["renewable_pct"],
        "carbon_saved_g": result["carbon_saved_g"] if invocation["success"] else None,
        "success": int(invocation["success"]),
        "metric_version": result["metric_version"],
        "baseline_carbon": result["baseline_carbon"],
        "energy_kwh_per_request": result["energy_kwh_per_request"],
        "backend": result["backend"],
        "data_source": result["data_source"],
        "deferral_recommendation": json.dumps(recommendation)
        if recommendation
        else None,
        "sla_satisfied": result["sla_satisfied"],
        "error": invocation["error"],
    }
    with connection() as conn:
        conn.execute(
            f"INSERT INTO routing_log ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
            tuple(row.values()),
        )


def get_logs(limit=60):
    with connection() as conn:
        rows = conn.execute(
            """SELECT timestamp, action, function_type, scheduler,
            selected_region AS region, region_label AS label, carbon_intensity AS carbon,
            latency_ms, exec_mode, cold_start, carbon_saved_g, success, metric_version,
            baseline_carbon, energy_kwh_per_request, backend, data_source,
            deferral_recommendation, sla_satisfied, error
            FROM routing_log ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    results = [dict(row) for row in rows]
    for row in results:
        row["deferral_recommendation"] = (
            json.loads(row["deferral_recommendation"])
            if row["deferral_recommendation"]
            else None
        )
    return results


def get_stats():
    valid = f"metric_version={METRIC_VERSION} AND success=1"
    aggregates = f"""COUNT(*) AS requests,
        SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) AS successful_requests,
        SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) AS failed_requests,
        AVG(CASE WHEN {valid} THEN carbon_intensity END) AS avg_carbon,
        AVG(CASE WHEN {valid} THEN latency_ms END) AS avg_latency,
        COALESCE(SUM(CASE WHEN {valid} THEN carbon_saved_g END), 0) AS total_saved"""
    with connection() as conn:
        by_region = [
            dict(row)
            for row in conn.execute(
                f"SELECT selected_region AS region, region_label AS label, {aggregates} FROM routing_log GROUP BY selected_region, region_label"
            )
        ]
        by_scheduler = [
            dict(row)
            for row in conn.execute(
                f"SELECT scheduler, {aggregates} FROM routing_log GROUP BY scheduler"
            )
        ]
        totals = dict(conn.execute(f"SELECT {aggregates} FROM routing_log").fetchone())
        counts = dict(
            conn.execute(
                """SELECT
            COUNT(CASE WHEN deferral_recommendation IS NOT NULL THEN 1 END) AS recommendation_count,
            COUNT(CASE WHEN metric_version IS NULL OR metric_version != ? THEN 1 END) AS legacy_requests,
            COUNT(CASE WHEN cold_start=1 THEN 1 END) AS cold_start_count,
            COUNT(CASE WHEN exec_mode='deferred' THEN 1 END) AS deferred_count
            FROM routing_log""",
                (METRIC_VERSION,),
            ).fetchone()
        )
    totals["total_requests"] = totals.pop("requests")
    totals["total_saved_g"] = round(totals.pop("total_saved"), 5)
    for key in ("successful_requests", "failed_requests"):
        totals[key] = totals[key] or 0
    totals.update(counts)
    return {
        "metric_version": METRIC_VERSION,
        "metric_kind": "estimated",
        "by_region": by_region,
        "by_scheduler": by_scheduler,
        "totals": totals,
    }
