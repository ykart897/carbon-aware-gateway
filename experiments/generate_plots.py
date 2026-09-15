"""Generate static figures solely from schema-3 experiment output."""

import argparse
import json
from pathlib import Path

DEFAULT_OUTPUT = Path(__file__).parent / "output"


def generate(input_path, output_dir):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if data.get("schema_version") != 3:
        raise ValueError("Expected experiment schema 3")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 5), layout="constrained")
    for solution in data["pareto_example"]["all_solutions"]:
        ax.scatter(
            solution["latency"],
            solution["carbon"],
            color="#999" if solution["dominated"] else "#059669",
        )
        ax.annotate(
            solution["region"],
            (solution["latency"], solution["carbon"]),
            xytext=(5, 5),
            textcoords="offset points",
        )
    ax.set(
        xlabel="Estimated base latency (ms)",
        ylabel="Sample carbon intensity (gCO2/kWh)",
        title="First workload: Pareto analysis",
    )
    fig.savefig(output_dir / "fig1_pareto_front.png", dpi=160)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    rows = data["summary"]
    labels = [
        r["scheduler"].replace("_", " ") + " / " + r["function_type"].replace("_", " ")
        for r in rows
    ]
    for ax, field, title in zip(
        axes,
        ("mean_carbon", "mean_latency_ms"),
        ("Mean sample carbon (gCO2/kWh)", "Mean simulated latency (ms)"),
    ):
        ax.barh(labels, [r[field] or 0 for r in rows], color="#059669")
        ax.set_title(title)
    fig.savefig(output_dir / "fig2_scheduler_comparison.png", dpi=160)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 5), layout="constrained")
    labels, values = [], []
    for region, models in data["forecasting"].items():
        for result in models.values():
            if result["mae"] is not None:
                labels.append(region + " / " + result["model_used"])
                values.append(result["mae"])
    ax.barh(labels, values, color="#2563eb")
    ax.set(
        xlabel="Held-out MAE (gCO2/kWh)",
        title="Forecast error on repeating sample profile",
    )
    fig.savefig(output_dir / "fig3_forecasting_mae.png", dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=DEFAULT_OUTPUT / "experiment_results.json"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT / "figures")
    args = parser.parse_args()
    generate(args.input, args.output_dir)
    print(args.output_dir)


if __name__ == "__main__":
    main()
