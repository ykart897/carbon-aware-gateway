from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from carbon_api import service
from forecasting import arima, prophet_model


class HistoryTests(unittest.TestCase):
    def test_midnight_and_hourly_profile_fallback(self):
        now = datetime(2026, 9, 16, 0, 35, tzinfo=timezone.utc)
        with patch.object(service, "_WEEKLY_DATA", []):
            history = service.get_history("DE", 3, now=now)
        self.assertEqual([h["hour"] for h in history], [21, 22, 23])
        self.assertEqual(history[-1]["timestamp"], "2026-09-15T23:00:00+00:00")
        self.assertEqual(
            [h["carbon_intensity"] for h in history],
            [service._HOURLY_DATA[h]["DE"] for h in (21, 22, 23)],
        )
        self.assertEqual(
            arima.forecast_times(history, 2),
            ["2026-09-16T00:00:00+00:00", "2026-09-16T01:00:00+00:00"],
        )

    def test_forecast_uses_last_observation(self):
        history = service.get_history(
            "IE", now=datetime(2026, 9, 16, tzinfo=timezone.utc)
        )
        with patch.object(arima, "get_history", return_value=history):
            result = arima.get_forecast("IE", 2)
        self.assertEqual(result["forecast_hours"], [0, 1])
        self.assertEqual(result["last_observation_at"], history[-1]["timestamp"])
        self.assertIn("sample profile", result["data_source"])


class ArimaTests(unittest.TestCase):
    def test_empty_short_and_constant(self):
        for series, expected in (([], 0), ([25], 25), ([42] * 48, 42)):
            with self.subTest(series=series):
                result = arima.arima_forecast(series, 24)
                self.assertEqual(result["forecasts"], [expected] * 24)
                if len(series) == 48:
                    self.assertEqual(result["mae"], 0)

    def test_second_difference_reintegrates_twice(self):
        series = [float(i * i) for i in range(48)]
        result = arima.arima_forecast(series, 3)
        self.assertFalse(result["stationary"])
        self.assertEqual(result["forecasts"], [2304, 2401, 2500])
        self.assertEqual(result["method"], "ARIMA(2,2,1)")

    def test_seed_does_not_change_point_forecast_and_evaluation_is_not_recursive(self):
        series = [20 + (i % 7) ** 2 for i in range(48)]
        with patch.object(arima, "_predict", wraps=arima._predict) as predict:
            first = arima.arima_forecast(series, seed=1)
        self.assertEqual(predict.call_count, 2)
        self.assertEqual(first, arima.arima_forecast(series, seed=999))


class ProphetTests(unittest.TestCase):
    def test_empty_short_and_constant_fallback(self):
        for series, expected in (([], 0), ([25], 25), ([42] * 48, 42)):
            result = prophet_model._exp_smoothing_fallback(series, 24)
            self.assertEqual(result["forecasts"], [expected] * 24)
            self.assertEqual(result["model_used"], "exponential_smoothing")
            self.assertIsNone(result["lower_bound"])
            if len(series) == 48:
                self.assertEqual(result["mae"], 0)

    def test_zero_mae_and_fallback_name_in_comparison(self):
        history = service.get_history(
            "IE", now=datetime(2026, 9, 16, tzinfo=timezone.utc)
        )
        fallback = prophet_model._exp_smoothing_fallback([42] * 48, 6)
        with (
            patch.object(prophet_model, "get_history", return_value=history),
            patch.object(prophet_model, "prophet_forecast", return_value=fallback),
            patch.object(
                prophet_model,
                "arima_forecast",
                return_value={"mae": 10, "model_used": "ARIMA(2,1,1)"},
            ),
        ):
            result = prophet_model.get_prophet_forecast("IE")
        self.assertEqual(result["best_model"], "exponential_smoothing")

    def test_missing_prophet_is_explicit(self):
        with patch.dict("sys.modules", {"prophet": None}):
            result = prophet_model.prophet_forecast([42] * 48)
        self.assertEqual(result["model_used"], "exponential_smoothing")
        self.assertEqual(result["fallback_reason"], "prophet_unavailable")
