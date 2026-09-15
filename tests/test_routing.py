import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from gateway import database
from openwhisk import cluster
from optimizer.pareto import optimize
from scheduler.engine import carbon_aware, round_robin, latency_only


def snapshot(carbons=(500, 800, 700, 900), latencies=(18, 48, 22, 32)):
    return {
        "hour": 23,
        "timestamp": "2026-09-15T23:00:00+00:00",
        "source": "test",
        "regions": {
            r: {
                "carbon_intensity": c,
                "latency_ms": latency,
                "label": r,
                "source": "controlled",
            }
            for r, c, latency in zip(("DE", "IE", "FR", "PL"), carbons, latencies)
        },
    }


def invoke(region, action, params, function_type):
    return cluster.InvocationResult(
        region, region, action, function_type, 25, False, True, "test", 50
    )


class RoutingTests(unittest.TestCase):
    def test_recommendation_does_not_change_execution(self):
        invoker = Mock(side_effect=invoke)
        result = carbon_aware(
            "test",
            {},
            "delay_tolerant",
            snapshot=snapshot(),
            forecasts={
                "IE": {
                    "arima_forecast": [600, 100],
                    "data_source": "CSV sample profile",
                    "model_used": "ARIMA(2,1,1)",
                }
            },
            now=datetime(2026, 9, 15, 23, tzinfo=timezone.utc),
            invoker=invoker,
        )
        invoker.assert_called_once_with("DE", "test", {}, "delay_tolerant")
        self.assertEqual(result["decision"]["selected_region"], "DE")
        self.assertEqual(result["invocation"]["region"], "DE")
        self.assertEqual(result["exec_mode"], "immediate")
        self.assertIsNone(result["defer_info"])
        self.assertEqual(result["deferral_recommendation"]["region"], "IE")
        self.assertEqual(
            result["deferral_recommendation"]["data_source"], "CSV sample profile"
        )
        self.assertEqual(
            result["deferral_recommendation"]["model_used"], "ARIMA(2,1,1)"
        )
        self.assertEqual(
            result["deferral_recommendation"]["scheduled_at"],
            "2026-09-16T01:00:00+00:00",
        )
        self.assertEqual(result["carbon_saved_g"], 0.225)

    def test_all_schedulers_share_metrics_and_snapshot(self):
        snap = snapshot()
        for scheduler, kwargs in (
            (carbon_aware, {}),
            (round_robin, {"rr_region": "DE"}),
            (latency_only, {}),
        ):
            with (
                self.subTest(scheduler=scheduler.__name__),
                patch("scheduler.engine.get_current", side_effect=AssertionError),
            ):
                result = scheduler("test", {}, snapshot=snap, invoker=invoke, **kwargs)
                self.assertEqual(result["baseline_carbon"], 725)
                self.assertEqual(
                    result["decision"]["carbon_saved_g"], result["carbon_saved_g"]
                )
                self.assertEqual(result["data_source"], "controlled")

    def test_failed_invocation_has_no_savings(self):
        def fail(*args):
            result = invoke(*args)
            result.success = False
            return result

        result = carbon_aware("test", {}, snapshot=snapshot(), invoker=fail)
        self.assertIsNone(result["carbon_saved_g"])
        self.assertIsNone(result["decision"]["carbon_saved_g"])

    def test_negative_savings_are_preserved(self):
        result = round_robin(
            "test", {}, snapshot=snapshot(), rr_region="PL", invoker=invoke
        )
        self.assertEqual(result["carbon_saved_g"], -0.175)

    def test_threshold_400_is_preserved(self):
        with patch("scheduler.engine.get_all_forecasts", side_effect=AssertionError):
            result = carbon_aware(
                "test",
                {},
                "delay_tolerant",
                snapshot=snapshot((400, 800, 700, 900)),
                invoker=invoke,
            )
        self.assertIsNone(result["deferral_recommendation"])


class OptimizerTests(unittest.TestCase):
    def test_no_feasible_sla_selects_fastest(self):
        result = optimize(snapshot((800, 100, 500, 900)), "epsilon", sla=1)
        self.assertEqual(result["selected_region"], "DE")
        self.assertFalse(result["sla_satisfied"])
        self.assertEqual(result["sla_basis"], "estimated_base_latency")

    def test_feasible_sla_selects_lowest_carbon(self):
        result = optimize(snapshot((800, 100, 500, 900)), "epsilon", sla=25)
        self.assertEqual(result["selected_region"], "FR")
        self.assertTrue(result["sla_satisfied"])

    def test_ties_and_dominance(self):
        equal = optimize(snapshot((100,) * 4, (20,) * 4), "pareto")
        self.assertEqual(len(equal["pareto_front"]), 4)
        self.assertEqual(equal["selected_region"], "DE")
        dominant = optimize(snapshot((100, 200, 300, 400), (10, 20, 30, 40)), "pareto")
        self.assertEqual([s["region"] for s in dominant["pareto_front"]], ["DE"])


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "test.db"
        self.patcher = patch.object(database, "DB", self.db)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        database.init()

    def test_legacy_and_failures_excluded_from_success_metrics(self):
        with database.connection() as conn:
            conn.execute(
                "INSERT INTO routing_log (success, carbon_saved_g) VALUES (1, 999)"
            )
        good = carbon_aware("test", {}, snapshot=snapshot(), invoker=invoke)
        database.log(good)
        bad = copy.deepcopy(good)
        bad["invocation"]["success"] = False
        database.log(bad)
        totals = database.get_stats()["totals"]
        self.assertEqual(totals["total_requests"], 3)
        self.assertEqual(totals["successful_requests"], 2)
        self.assertEqual(totals["failed_requests"], 1)
        self.assertEqual(totals["legacy_requests"], 1)
        self.assertEqual(totals["total_saved_g"], good["carbon_saved_g"])
        rows = database.get_logs()
        self.assertIsNone(rows[0]["carbon_saved_g"])
        self.assertEqual(rows[1]["baseline_carbon"], good["baseline_carbon"])
        self.assertEqual(rows[1]["region"], good["invocation"]["region"])

    def test_migration_preserves_old_rows(self):
        with database.connection() as conn:
            conn.execute("DROP TABLE routing_log")
            conn.execute("""CREATE TABLE routing_log (id INTEGER PRIMARY KEY,
                         scheduler TEXT, action TEXT, carbon_saved_g REAL)""")
            conn.execute(
                "INSERT INTO routing_log VALUES (1, 'round_robin', 'old', 999)"
            )
        database.init()
        with database.connection() as conn:
            row = conn.execute("SELECT * FROM routing_log").fetchone()
            self.assertEqual(row["action"], "old")
            self.assertIsNone(row["metric_version"])

    def test_round_robin_atomic_across_threads(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            regions = list(pool.map(lambda _: database.next_region(), range(40)))
        self.assertEqual(
            {r: regions.count(r) for r in set(regions)},
            {r: 10 for r in ("DE", "IE", "FR", "PL")},
        )

    def test_database_failure_is_not_silent(self):
        with patch.object(database, "DB", Path(self.temp.name) / "missing" / "db"):
            with self.assertRaises(sqlite3.OperationalError):
                database.next_region()


class OpenWhiskTests(unittest.TestCase):
    def test_parameters_backend_and_total_latency(self):
        def run(command, **kwargs):
            payload = json.loads(
                Path(command[command.index("--param-file") + 1]).read_text()
            )
            self.assertEqual(
                payload,
                {
                    "message": "hello",
                    "count": 2,
                    "function_type": "standard",
                    "action": "test",
                },
            )
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"success": True, "region": "DE", "latency_ms": 999}),
            )

        with (
            patch.object(cluster, "OW_AUTH", "test"),
            patch.object(cluster, "USE_REAL_OW", True),
            patch.object(cluster.subprocess, "run", side_effect=run),
            patch.object(cluster.time, "perf_counter", side_effect=[1, 1.125]),
        ):
            result = cluster.invoke("DE", "test", {"message": "hello", "count": 2})
        self.assertTrue(result.success)
        self.assertEqual(result.backend, "openwhisk-real")
        self.assertEqual(result.latency_ms, 125)

    def test_errors_never_fall_back_to_simulation(self):
        failures = [
            subprocess.TimeoutExpired("secret", 15),
            SimpleNamespace(returncode=1, stdout="", stderr="secret"),
            SimpleNamespace(returncode=0, stdout="not JSON"),
            SimpleNamespace(returncode=0, stdout='{"success": false}'),
            SimpleNamespace(returncode=0, stdout='{"success": true, "region": "IE"}'),
        ]
        for failure in failures:
            kwargs = (
                {"side_effect": failure}
                if isinstance(failure, Exception)
                else {"return_value": failure}
            )
            with (
                self.subTest(failure=failure),
                patch.object(cluster, "OW_AUTH", "test"),
                patch.object(cluster.subprocess, "run", **kwargs),
                patch.object(cluster, "_invoke_simulated", side_effect=AssertionError),
            ):
                result = cluster._invoke_real_ow("DE", "test", {})
                self.assertFalse(result.success)
                self.assertEqual(result.backend, "openwhisk-real")
                self.assertNotIn("secret", result.error)
