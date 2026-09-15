import json
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from experiments.generate_report import generate
from experiments.run_experiments import paired_test, run
from forecasting.prophet_model import _exp_smoothing_fallback


@unittest.skipUnless(find_spec("scipy"), "Install requirements-experiments.txt")
class ExperimentTests(unittest.TestCase):
    def run_offline(self, seed=42):
        with (
            patch(
                "sqlite3.connect",
                side_effect=AssertionError("Database must not be touched"),
            ),
            patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("Network must not be used"),
            ),
            patch(
                "openwhisk.cluster.invoke",
                side_effect=AssertionError("Real backend must not be used"),
            ),
            patch(
                "experiments.run_experiments.prophet_forecast",
                side_effect=lambda series, steps, **kwargs: _exp_smoothing_fallback(
                    series, steps
                ),
            ),
        ):
            return run(seed=seed, samples=4)

    def test_seed_reproducibility_and_isolation(self):
        first = self.run_offline()
        self.assertEqual(first, self.run_offline())
        self.assertNotEqual(first["workloads"], self.run_offline(77)["workloads"])
        self.assertEqual(len(first["invocations"]), 36)
        json.dumps(first, allow_nan=False)

    def test_shared_workload_metrics_and_no_fake_deferral(self):
        data = self.run_offline()
        for row in data["invocations"]:
            snapshot = data["workloads"][row["sample_id"]]["snapshot"]
            baseline = (
                sum(r["carbon_intensity"] for r in snapshot["regions"].values()) / 4
            )
            self.assertEqual(row["baseline_carbon"], baseline)
            self.assertEqual(
                row["decision"]["selected_region"], row["invocation"]["region"]
            )
            self.assertEqual(row["exec_mode"], "immediate")
            self.assertIsNone(row["defer_info"])
            self.assertEqual(row["backend"], "simulation")
            self.assertEqual(
                row["carbon_saved_g"],
                round(
                    (baseline - row["decision"]["carbon_intensity"])
                    * row["energy_kwh_per_request"],
                    5,
                ),
            )
        for comparison in data["comparisons"]:
            self.assertEqual(comparison["n"], 4)

    def test_undefined_paired_statistics(self):
        for first, second, reason in (
            ([], [], "fewer_than_two_pairs"),
            ([1], [2], "fewer_than_two_pairs"),
            ([1, 1], [2, 2], "constant_paired_differences"),
        ):
            result = paired_test(first, second)
            self.assertEqual(result["reason"], reason)
            self.assertIsNone(result["t_statistic"])
            self.assertIsNone(result["p_value"])
        from scipy.stats import ttest_rel

        expected = ttest_rel([1, 3, 7], [2, 2, 2])
        actual = paired_test([1, 3, 7], [2, 2, 2])
        self.assertEqual(actual["p_value"], float(expected.pvalue))

    def test_report_uses_one_schema_and_does_not_modify_source(self):
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "experiment_results.json"
            data = self.run_offline()
            data["meta"]["limitations"] = '<script>alert("x")</script>'
            source.write_text(json.dumps(data), encoding="utf-8")
            before = source.read_bytes()
            paper = generate(source, directory)
            first = (directory / "paper_numbers.json").read_bytes()
            generate(source, directory)
            self.assertEqual(first, (directory / "paper_numbers.json").read_bytes())
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(paper["schema_version"], 3)
            self.assertNotIn("<script>", (directory / "phase2_report.html").read_text())
            self.assertEqual(
                paper["forecasting"]["DE"]["prophet"]["model_used"],
                "exponential_smoothing",
            )
