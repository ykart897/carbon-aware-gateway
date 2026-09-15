from pathlib import Path
import unittest

from carbon_api.entsoe import _calc_carbon, _parse_generation_xml

FIXTURES = Path(__file__).parent / "fixtures"


class GenerationXmlTests(unittest.TestCase):
    def test_hourly_and_quarter_hour_power_have_same_energy(self):
        for name in ("generation_hourly.xml", "generation_quarter_hour.xml"):
            with self.subTest(name=name):
                generation = _parse_generation_xml((FIXTURES / name).read_text())
                self.assertEqual(generation, {"B16": 100, "B05": 100})
                result = _calc_carbon(generation)
                self.assertEqual(result["total_mwh"], 200)
                self.assertEqual(result["carbon_intensity"], 430.5)
                self.assertEqual(result["renewable_pct"], 50)
                self.assertEqual(result["breakdown"]["Solar"]["co2g"], 4100000)
                self.assertEqual(
                    result["estimate_basis"], "generation_mix_emission_factors"
                )

    def test_energy_unit_is_not_multiplied_by_duration(self):
        xml = (FIXTURES / "generation_hourly.xml").read_text()
        xml = (
            xml.replace("MAW", "MWH")
            .replace("PT60M", "PT30M")
            .replace("00:00Z", "23:30Z")
            .replace("2026-09-16", "2026-09-15")
        )
        self.assertEqual(_parse_generation_xml(xml), {"B16": 100, "B05": 100})

    def test_missing_fixed_points_and_invalid_values_are_rejected(self):
        xml = (FIXTURES / "generation_hourly.xml").read_text()
        variants = [
            xml.replace("MAW", "KWH"),
            xml.replace("PT60M", "PT15M"),
            xml.replace("PT60M", "PT0M"),
            xml.replace("<quantity>100", "<quantity>NaN"),
            xml.replace("<quantity>100", "<quantity>-1"),
            xml.replace("<position>1", "<position>2"),
            xml.replace("B16", "UNKNOWN"),
        ]
        for variant in variants:
            with self.subTest(xml=variant), self.assertRaises(ValueError):
                _parse_generation_xml(variant)

    def test_mismatched_coverage_is_rejected(self):
        xml = (FIXTURES / "generation_hourly.xml").read_text()
        xml = xml.replace("2026-09-15T23:00Z", "2026-09-15T22:00Z", 1).replace(
            "PT60M", "PT2H", 1
        )
        with self.assertRaisesRegex(ValueError, "different intervals"):
            _parse_generation_xml(xml)

    def test_sub_mwh_generation_is_valid(self):
        result = _calc_carbon({"B16": 0.1})
        self.assertEqual(result["total_mwh"], 0.1)
        self.assertEqual(result["carbon_intensity"], 41)
