"""Run in the disposable verification container with a read-only source mount."""

from pathlib import Path
import shutil
import subprocess
import sys


def main():
    source = Path("/source")
    target = Path("/work")
    # Explicit publication inputs prevent local environments/data entering the test copy.
    for name in (
        "carbon_api",
        "forecasting",
        "gateway",
        "optimizer",
        "scheduler",
        "openwhisk",
        "static",
        "tests",
        "data",
        "scripts",
    ):
        shutil.copytree(
            source / name, target / name, ignore=shutil.ignore_patterns("__pycache__")
        )
    (target / "experiments").mkdir()
    for path in (source / "experiments").glob("*.py"):
        shutil.copy2(path, target / "experiments" / path.name)
    for pattern in (
        "*.py",
        "requirements*",
        "pyproject.toml",
        "dashboard.html",
        ".gitignore",
    ):
        for path in source.glob(pattern):
            shutil.copy2(path, target / path.name)

    def run(*args):
        print("RUN:", " ".join(args), flush=True)
        subprocess.run(args, cwd=target, check=True)

    run(
        sys.executable,
        "-m",
        "pip",
        "install",
        "--quiet",
        "-r",
        "requirements-core.lock",
    )
    run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q")
    run(sys.executable, "tests/smoke_server.py")
    run(
        sys.executable,
        "-m",
        "pip",
        "install",
        "--quiet",
        "-r",
        "requirements-full.lock",
    )
    run(sys.executable, "-m", "pip", "check")
    run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q")
    run(sys.executable, "-m", "ruff", "check", ".")
    run(
        sys.executable,
        "-c",
        "from forecasting.prophet_model import get_prophet_forecast; "
        "assert get_prophet_forecast('IE')['prophet']['model_used']=='prophet'; print('Actual Prophet passed')",
    )
    run(
        sys.executable,
        "experiments/run_experiments.py",
        "--seed",
        "42",
        "--samples",
        "8",
        "--output-dir",
        "output",
    )
    run(
        sys.executable,
        "experiments/generate_report.py",
        "--input",
        "output/experiment_results.json",
        "--output-dir",
        "output",
    )
    run(
        sys.executable,
        "experiments/generate_plots.py",
        "--input",
        "output/experiment_results.json",
        "--output-dir",
        "output/figures",
    )
    print("LINUX VERIFICATION PASSED", flush=True)


if __name__ == "__main__":
    main()
