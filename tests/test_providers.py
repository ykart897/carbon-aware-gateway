import io
import json
import unittest
from unittest.mock import patch

from carbon_api import entsoe, service


class ProviderTests(unittest.TestCase):
    def test_em_zero_is_valid(self):
        with patch(
            "urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps({"carbonIntensity": 0}).encode()),
        ):
            self.assertEqual(service._fetch_em("DE"), 0)

    def test_em_invalid_or_unavailable_is_not_a_measurement(self):
        for body in (
            b"bad json",
            b"{}",
            b"[]",
            b'{"carbonIntensity": -1}',
            b'{"carbonIntensity": "NaN"}',
        ):
            with (
                self.subTest(body=body),
                patch("urllib.request.urlopen", return_value=io.BytesIO(body)),
            ):
                self.assertIsNone(service._fetch_em("DE"))
        with (
            patch("urllib.request.urlopen", side_effect=TimeoutError("private token")),
            self.assertLogs("carbon_api.service", level="WARNING") as captured,
        ):
            self.assertIsNone(service._fetch_em("DE"))
        self.assertNotIn("private token", str(captured.output))

    def test_entsoe_failure_does_not_expose_exception_details(self):
        with (
            patch.object(entsoe, "ENTSOE_TOKEN", "test"),
            patch.object(entsoe, "_cache_get", return_value=None),
            patch.object(
                entsoe, "_entsoe_request", side_effect=TimeoutError("private token")
            ),
            self.assertLogs("carbon_api.entsoe", level="WARNING") as captured,
        ):
            result = entsoe.get_carbon_intensity("DE")
        self.assertIsNone(result["carbon_intensity"])
        self.assertNotIn("private token", json.dumps(result) + str(captured.output))
