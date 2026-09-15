"""Exercise deployment control flow with fake external commands, never Docker."""

import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = (
    str(Path("C:/Program Files/Git/bin/bash.exe"))
    if os.name == "nt"
    else shutil.which("bash")
)


@unittest.skipUnless(BASH and Path(BASH).exists(), "Bash is unavailable")
class DeploymentTests(unittest.TestCase):
    def exercise(self, exists="true", running="true", ready="true"):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            commands = {
                "docker": """echo "docker $*" >> "$CALL_LOG"
if [[ "$1 $2" == 'container inspect' ]]; then [[ "$EXISTS" == true ]];
elif [[ "$1" == inspect ]]; then echo "$RUNNING";
elif [[ "$1" == run ]]; then echo fake-container;
else exit 95; fi""",
                "curl": """echo "curl" >> "$CALL_LOG"
if [[ "$READY" == true ]]; then echo '{"version":"test"}'; else exit 7; fi""",
                "wsk": """echo "wsk $*" >> "$CALL_LOG"
if [[ "$*" == *'property set'* || "$*" == *'--web true'* ]]; then exit 96; fi
echo '{"success":true}' """,
                "sleep": "exit 0",
            }
            for name, content in commands.items():
                path = directory / name
                path.write_text(
                    "#!/usr/bin/env bash\n" + content + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                path.chmod(0o755)
            log = directory / "calls"
            env = {
                **os.environ,
                "CALL_LOG": log.as_posix(),
                "EXISTS": exists,
                "RUNNING": running,
                "READY": ready,
                "OPENWHISK_AUTH": "test-only",
            }
            result = subprocess.run(
                [
                    BASH,
                    "-c",
                    'export PATH="$(cd "$1" && pwd):$PATH"; bash "$2"',
                    "test",
                    directory.as_posix(),
                    (ROOT / "openwhisk/deploy.sh").as_posix(),
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            calls = log.read_text() if log.exists() else ""
            self.assertNotIn("docker rm", calls)
            self.assertNotIn("property set", calls)
            return result, calls

    def test_existing_running_container_is_reused(self):
        result, calls = self.exercise()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("docker run", calls)
        self.assertEqual(calls.count("action update"), 4)
        self.assertEqual(calls.count("carbon_worker.py"), 4)

    def test_existing_stopped_container_fails(self):
        result, calls = self.exercise(running="false")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("action update", calls)
        self.assertNotIn("docker run", calls)

    def test_unready_service_fails_without_deploying(self):
        result, calls = self.exercise(ready="false")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("action update", calls)

    def test_new_container_binds_only_loopback(self):
        result, calls = self.exercise(exists="false")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-p 127.0.0.1:3233:3233", calls)
