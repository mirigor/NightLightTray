"""Тесты win-nightlight-cli без изменения ночного света Windows"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nightlight import (
    LatestRequest,
    NightLightError,
    find_wnl,
    parse_active,
    parse_strength,
    process_error,
    strength_to_kelvin,
)


class ParseStrengthTests(unittest.TestCase):
    def test_status_with_other_fields(self):
        self.assertEqual(
            parse_strength("active: yes\r\ncolor temperature: 2260K\r\nschedule: off\r\n"), 80
        )

    def test_endpoints(self):
        self.assertEqual(parse_strength("color temperature: 6500K"), 0)
        self.assertEqual(parse_strength("color temperature: 1200K"), 100)

    def test_round_trip_all_percentages(self):
        for value in range(101):
            with self.subTest(value=value):
                self.assertEqual(
                    parse_strength("color temperature: {}K".format(strength_to_kelvin(value))),
                    value,
                )

    def test_problem_values(self):
        self.assertEqual(strength_to_kelvin(56), 3532)
        self.assertEqual(strength_to_kelvin(68), 2896)

    def test_non_slider_temperature_rounds_to_nearest(self):
        self.assertEqual(parse_strength("color temperature: 3400K"), 58)

    def test_invalid_temperature_or_response(self):
        for output in (
            "color temperature: 1199K",
            "color temperature: 6501K",
            "68%",
            "color temperature: -1200K",
            "error: unavailable",
            "color temperature: 3400K\ncolor temperature: 3500K",
        ):
            with self.subTest(output=output), self.assertRaises(NightLightError):
                parse_strength(output)

    def test_windows_default_is_not_fabricated(self):
        with self.assertRaisesRegex(NightLightError, "не сохранила числовую"):
            parse_strength("color temperature: Windows default")

    def test_invalid_strength_is_rejected(self):
        for value in (-1, 101, 56.0, True, "68", None):
            with self.subTest(value=value), self.assertRaises(NightLightError):
                strength_to_kelvin(value)


class ParseActiveTests(unittest.TestCase):
    def test_actual_state_is_not_schedule(self):
        self.assertTrue(parse_active("active:            yes\r\nschedule: off\r\n"))
        self.assertFalse(parse_active("active:            no\nschedule: on\n"))

    def test_missing_invalid_and_duplicate_state_are_rejected(self):
        for output in (
            "schedule: off",
            "active: on",
            "active: maybe",
            "active:",
            "active: yes\nactive: no",
            "active: yes\nactive: yes",
        ):
            with self.subTest(output=output), self.assertRaises(NightLightError):
                parse_active(output)


class LookupAndErrorTests(unittest.TestCase):
    def test_missing_command(self):
        with patch.dict(os.environ, {"NIGHTLIGHT_WNL": "Z:/missing/wnl.exe"}):
            self.assertIsNone(find_wnl())

    def test_unicode_path_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="Ночной свет ") as folder:
            command = Path(folder) / "wnl.exe"
            command.touch()
            with patch.dict(os.environ, {"NIGHTLIGHT_WNL": str(command)}):
                self.assertEqual(find_wnl(), str(command.resolve()))

    def test_bundled_command_is_found_without_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "tools").mkdir()
            command = root / "tools" / "wnl.exe"
            command.touch()
            with (
                patch.dict(os.environ, {"NIGHTLIGHT_WNL": ""}),
                patch("nightlight.application_directory", return_value=root),
            ):
                self.assertEqual(find_wnl(), str(command.resolve()))

    def test_old_cmd_is_not_used(self):
        with tempfile.TemporaryDirectory() as folder:
            command = Path(folder) / "nightlight.cmd"
            command.touch()
            with patch.dict(os.environ, {"NIGHTLIGHT_WNL": str(command)}):
                self.assertIsNone(find_wnl())

    def test_timeout_message(self):
        self.assertIn("вовремя", process_error(-1, "", timed_out=True))

    def test_execution_error_uses_stderr(self):
        self.assertIn("permission denied", process_error(1, "permission denied"))


class LatestRequestTests(unittest.TestCase):
    def test_fast_changes_are_coalesced(self):
        queue = LatestRequest()
        queue.submit(10)
        queue.submit(44)
        final_generation = queue.submit(80)
        self.assertEqual(queue.take(), (80, final_generation))
        self.assertIsNone(queue.take())

    def test_stale_result_is_rejected(self):
        queue = LatestRequest()
        old = queue.submit(20)
        new = queue.submit(70)
        self.assertFalse(queue.current(old))
        self.assertTrue(queue.current(new))


if __name__ == "__main__":
    unittest.main()
