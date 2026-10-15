"""Проверка ожидания трея без перезапуска оболочки Windows"""

import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from main import TrayStartup, main


class TrayStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.elapsed = Mock()
        self.elapsed.elapsed.return_value = 0
        with patch("main.QElapsedTimer", return_value=self.elapsed):
            self.startup = TrayStartup()
        self.startup._timer.setInterval(10)
        self.addCleanup(self.startup.stop)
        self.ready = []
        self.failed = []
        self.startup.ready.connect(lambda: self.ready.append(True))
        self.startup.unavailable.connect(lambda: self.failed.append(True))

    def test_available_tray_starts_once_without_background_checks(self):
        with patch("main.QSystemTrayIcon.isSystemTrayAvailable", return_value=True) as available:
            self.startup.start()
            self.startup.start()
            self.startup._check()
            self.assertEqual(self.ready, [True])
            self.assertEqual(self.failed, [])
            self.assertFalse(self.startup._timer.isActive())
            available.assert_called_once()

    def test_timer_waits_then_starts_when_tray_appears(self):
        with patch(
            "main.QSystemTrayIcon.isSystemTrayAvailable", side_effect=[False, False, True]
        ) as available:
            self.startup.start()
            self.assertTrue(self.startup._timer.isActive())
            self.assertEqual(self.ready, [])
            QTest.qWait(80)
            self.assertEqual(self.ready, [True])
            self.assertEqual(self.failed, [])
            self.assertEqual(available.call_count, 3)
            self.assertFalse(self.startup._timer.isActive())

    def test_missing_tray_reports_error_only_after_deadline(self):
        with patch("main.QSystemTrayIcon.isSystemTrayAvailable", return_value=False):
            self.startup.start()
            self.elapsed.elapsed.return_value = 59999
            self.startup._check()
            self.assertEqual(self.failed, [])
            self.elapsed.elapsed.return_value = 60000
            self.startup._check()
            self.startup._check()
            self.assertEqual(self.failed, [True])
            self.assertEqual(self.ready, [])
            self.assertFalse(self.startup._timer.isActive())

    def test_ready_tray_at_deadline_still_starts_normally(self):
        with patch("main.QSystemTrayIcon.isSystemTrayAvailable", return_value=False):
            self.startup.start()
        self.elapsed.elapsed.return_value = 60000
        with patch("main.QSystemTrayIcon.isSystemTrayAvailable", return_value=True):
            self.startup._check()
        self.assertEqual(self.ready, [True])
        self.assertEqual(self.failed, [])

    def test_shutdown_cancels_pending_checks(self):
        with patch("main.QSystemTrayIcon.isSystemTrayAvailable", return_value=False) as available:
            self.startup.start()
            self.startup.stop()
            QTest.qWait(40)
            self.startup._check()
            available.assert_called_once()
            self.assertEqual(self.ready, [])
            self.assertEqual(self.failed, [])

    def test_second_instance_does_not_start_another_wait_or_controller(self):
        with (
            patch("main.QApplication", return_value=self.app),
            patch("main.SingleInstance") as single,
            patch("main.QSystemTrayIcon.isSystemTrayAvailable") as available,
            patch("main.TrayController") as controller,
            patch("main.configure_logging") as logging,
        ):
            single.return_value.acquire.return_value = False
            self.assertEqual(main(), 0)
            available.assert_not_called()
            controller.assert_not_called()
            logging.assert_not_called()
            single.return_value.close.assert_called_once()

    def test_controller_and_activation_wait_for_tray(self):
        single = Mock()
        single.acquire.return_value = True
        activation = []

        def make_single(callback):
            activation.append(callback)
            return single

        with (
            patch("main.QApplication", return_value=self.app),
            patch("main.SingleInstance", side_effect=make_single),
            patch("main.configure_logging"),
            patch("main.NightLightClient"),
            patch("main.TrayController") as controller,
            patch("main.QSystemTrayIcon.isSystemTrayAvailable", return_value=False) as available,
            patch("main.TRAY_STARTUP_RETRY_MS", 10),
        ):

            def run_events():
                QTest.qWait(40)
                controller.assert_not_called()
                single.acquire.assert_called_once()
                activation[0]()
                available.return_value = True
                QTest.qWait(40)
                return 0

            with patch.object(QApplication, "exec", side_effect=run_events):
                self.assertEqual(main(), 0)
            controller.assert_called_once()
            controller.return_value.start.assert_called_once()
            controller.return_value.show_popup.assert_called_once()
            single.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
