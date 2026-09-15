# Reproducible offline experiments

From the project root:

```sh
python experiments/run_experiments.py --seed 42 --samples 50 --output-dir experiments/output
python experiments/generate_report.py --input experiments/output/experiment_results.json --output-dir experiments/output
python experiments/generate_plots.py --input experiments/output/experiment_results.json --output-dir experiments/output/figures
```

The runner writes only `experiment_results.json` (schema 3). The report command
reads that file and writes `phase2_report.html` and `paper_numbers.json`, also
schema 3. The plotting command reads the same input. Reordering report and plot
commands does not change the source or paper schema.

Each sample supplies one snapshot, action and invocation seed to every strategy
and function type. The scheduler and simulated latency model are shared with the
application. The runner always uses simulation, has no waiting or real backend
calls, and neither initializes nor writes the application database. It does not
use API credentials even if they exist in the environment.

Comparisons use SciPy's paired `ttest_rel`, with carbon-aware minus the comparator
as the signed difference. Fewer than two pairs or numerically constant paired
differences produce `null` statistics with a reason. Hourly observations from the
repeating CSV profile are correlated; these exploratory, unadjusted p-values are
not evidence of independent real-world measurements.

Carbon savings are estimates based on the configured energy assumption and each
snapshot's four-region average. Suggested future savings are separate unrealized
estimates. The normal profile need not trigger the unchanged 400 gCO2/kWh
threshold; a controlled high-carbon scheduler test verifies that behavior.

Forecast comparison uses a fixed UTC history and a six-observation holdout.
`model_used` distinguishes Prophet from exponential smoothing. For exact
reproduction, use the same dependencies, CSV files and energy configuration.
The default configuration uses 0.001 kWh per invocation; no energy is
measured by the simulation.

`results/` contains historical output from the old implementation. Its claims
must not be used to describe current behavior. The former `results_template.html`
is also historical; the new report renderer does not use it.
