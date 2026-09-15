"""Render HTML and a single paper-summary schema from experiment JSON."""

import argparse
import html
import json
from pathlib import Path

DEFAULT_OUTPUT = Path(__file__).parent / "output"


def generate(input_path, output_dir):
    data = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if data.get("schema_version") != 3:
        raise ValueError(
            "Expected experiment schema 3; historical results are unsupported"
        )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paper = {
        "schema_version": 3,
        "experiment_setup": data["meta"],
        "scheduler_summary": data["summary"],
        "paired_comparisons": data["comparisons"],
        "forecasting": {
            region: {
                key: {
                    field: result.get(field)
                    for field in ("model_used", "mae", "rmse", "fallback_reason")
                }
                for key, result in models.items()
            }
            for region, models in data["forecasting"].items()
        },
    }
    (output_dir / "paper_numbers.json").write_text(
        json.dumps(paper, indent=2, allow_nan=False), encoding="utf-8"
    )

    def table(rows):
        if not rows:
            return "<p>No data.</p>"
        keys = list(rows[0])
        header = "".join(
            "<th>" + html.escape(key.replace("_", " ")) + "</th>" for key in keys
        )
        body = "".join(
            "<tr>"
            + "".join(
                "<td>"
                + html.escape(
                    str(row.get(key)) if row.get(key) is not None else "undefined"
                )
                + "</td>"
                for key in keys
            )
            + "</tr>"
            for row in rows
        )
        return (
            '<div class="scroll"><table><thead><tr>'
            + header
            + "</tr></thead><tbody>"
            + body
            + "</tbody></table></div>"
        )

    forecasts = [
        {"region": region, "requested_model": key, **result}
        for region, models in paper["forecasting"].items()
        for key, result in models.items()
    ]
    document = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Carbon Gateway experiment report</title>
<style>body{font:15px system-ui;margin:24px;color:#16312c;background:#f8fafc}main{max-width:1200px;margin:auto}h1,h2{color:#065f46}.scroll{overflow:auto}table{border-collapse:collapse;background:white;width:100%}th,td{padding:9px;border:1px solid #ddd;text-align:left}p{line-height:1.6}pre{white-space:pre-wrap}</style>
<main><h1>Carbon Gateway: paired simulation experiment</h1>"""
    document += "<p>" + html.escape(data["meta"]["limitations"]) + "</p>"
    document += "<p>Estimated savings use the four-region average from each invocation's snapshot. Recommendations are unrealized and excluded from those totals.</p>"
    document += (
        "<h2>Setup</h2><pre>"
        + html.escape(json.dumps(data["meta"], indent=2))
        + "</pre>"
    )
    document += "<h2>Scheduler results</h2>" + table(data["summary"])
    document += (
        "<h2>Paired comparisons</h2><p>Difference = carbon-aware minus comparator. Constant differences have undefined t-statistics and p-values.</p>"
        + table(data["comparisons"])
    )
    document += (
        "<h2>Forecast evaluation</h2><p>Last six observations held out. The actual model used is reported, including any fallback.</p>"
        + table(forecasts)
    )
    document += "</main></html>"
    (output_dir / "phase2_report.html").write_text(document, encoding="utf-8")
    return paper


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=DEFAULT_OUTPUT / "experiment_results.json"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    generate(args.input, args.output_dir)
    print(args.output_dir / "phase2_report.html")


if __name__ == "__main__":
    main()
