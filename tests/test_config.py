"""Validate configuration in a fresh process, independently of module caches."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = (
    "HOST",
    "PORT",
    "ENTSOE_API_KEY",
    "ELECTRICITY_MAPS_API_KEY",
    "USE_LIVE_API",
    "OPENWHISK_REAL",
    "OPENWHISK_HOST",
    "OPENWHISK_AUTH",
    "DATABASE_PATH",
    "ENERGY_KWH_PER_REQUEST",
)


class ConfigurationTests(unittest.TestCase):
    def load(self, dotenv="", environment=None):
        with TemporaryDirectory() as directory:
            config = Path(directory) / "config.py"
            config.write_text(
                (ROOT / "config.py").read_text(encoding="utf-8"), encoding="utf-8"
            )
            config.with_name(".env").write_text(dotenv, encoding="utf-8")
            env = {
                key: value for key, value in os.environ.items() if key not in SETTINGS
            }
            env.update(environment or {})
            return subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import importlib.util,json,sys; "
                    "spec=importlib.util.spec_from_file_location('isolated_config',sys.argv[1]); "
                    "c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c); "
                    "print(json.dumps({k:getattr(c,k) for k in "
                    "('HOST','PORT','ENTSOE_API_KEY','USE_LIVE_API','OPENWHISK_REAL','ENERGY_KWH_PER_REQUEST')}))",
                    str(config),
                ],
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
            )

    def test_keyless_defaults(self):
        result = self.load()
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertEqual(
            values,
            {
                "HOST": "127.0.0.1",
                "PORT": 8000,
                "ENTSOE_API_KEY": "",
                "USE_LIVE_API": False,
                "OPENWHISK_REAL": False,
                "ENERGY_KWH_PER_REQUEST": 0.001,
            },
        )

    def test_environment_overrides_dotenv(self):
        result = self.load(
            "HOST=0.0.0.0\nPORT=8123\nENTSOE_API_KEY=file-token\n",
            {"HOST": "127.0.0.1", "ENTSOE_API_KEY": "environment-token"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertEqual(values["HOST"], "127.0.0.1")
        self.assertEqual(values["PORT"], 8123)
        self.assertEqual(values["ENTSOE_API_KEY"], "environment-token")

    def test_invalid_energy_fails_at_startup(self):
        for energy in ("0", "-1", "nan", "inf"):
            with self.subTest(energy=energy):
                result = self.load(environment={"ENERGY_KWH_PER_REQUEST": energy})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("must be finite and positive", result.stderr)
