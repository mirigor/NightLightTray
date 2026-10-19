"""Проверки очереди QProcess без запуска настоящего Night Light"""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from nightlight import NightLightClient
from tray import TrayController


class FakeProcess(QObject):
    """Управляемый процесс для проверки порядка ответов и ошибок"""

    finished = Signal(int, int)
    errorOccurred = Signal(int)
    NotRunning = 0
    Running = 1
    SeparateChannels = 0
    FailedToStart = 1
    ProcessState = SimpleNamespace(NotRunning=0)
    ProcessError = SimpleNamespace(FailedToStart=1)
    ProcessChannelMode = SimpleNamespace(SeparateChannels=0)
    ExitStatus = SimpleNamespace(NormalExit=0, CrashExit=1)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.arguments = None
        self._state = self.NotRunning
        self._stdout = b""
        self._stderr = b""

    def setProcessChannelMode(self, _mode):
        pass

    def start(self, _command, arguments):
        self.arguments = arguments
        self._state = self.Running

    def state(self):
        return self._state

    def readAllStandardOutput(self):
        return self._stdout

    def readAllStandardError(self):
        return self._stderr

    def finish(self, exit_code=0, stdout=b"", stderr=b"", exit_status=0):
        self._stdout = stdout
        self._stderr = stderr
        self._state = self.NotRunning
        self.finished.emit(exit_code, exit_status)

    def kill(self):
        self.finish(-1)

    def waitForFinished(self, _timeout):
        return self._state == self.NotRunning


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.patcher = patch("nightlight.QProcess", FakeProcess)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = NightLightClient(command="fake.exe")
        self.addCleanup(self.client.close)
        self.values = []
        self.states = []
        self.errors = []
        self.client.status_ready.connect(
            lambda generation, value, active: self.values.append((generation, value))
        )
        self.client.status_ready.connect(
            lambda generation, value, active: self.states.append((generation, active))
        )
        self.client.operation_error.connect(
            lambda generation, message: self.errors.append((generation, message))
        )

    def test_refresh_during_write_is_not_lost(self):
        self.client.set_strength(70, 1)
        writing = self.client._process
        self.client.read_strength(2)
        writing.finish()
        reading = self.client._process
        self.assertEqual(reading.arguments, ["status"])
        reading.finish(stdout=b"active: yes\ncolor temperature: 2790K\n")
        self.assertEqual(self.values, [(2, 70)])

    def test_failed_write_reads_actual_value(self):
        self.client.set_strength(80, 1)
        self.client._process.finish(1, stderr=b"failed")
        self.assertEqual(len(self.errors), 1)
        self.assertEqual(self.client._process.arguments, ["status"])
        self.client._process.finish(stdout=b"active: yes\ncolor temperature: 2949K\n")
        self.assertEqual(self.values, [(1, 67)])

    def test_fast_writes_keep_only_latest_pending_value(self):
        self.client.set_strength(10, 1)
        first = self.client._process
        self.client.set_strength(20, 2)
        self.client.set_strength(90, 3)
        first.finish()
        latest = self.client._process
        self.assertEqual(latest.arguments, ["temp", "1730"])
        latest.finish()
        self.client._process.finish(stdout=b"active: yes\ncolor temperature: 1730K\n")
        self.assertEqual(self.values, [(3, 90)])

    def test_timeout_reports_timeout_not_start_error(self):
        self.client.read_strength(1)
        self.client._on_timeout()
        self.assertEqual(len(self.errors), 1)
        self.assertIn("вовремя", self.errors[0][1])

    def test_start_failure_stops_process(self):
        self.client.read_strength(1)
        process = self.client._process
        process._state = process.NotRunning
        process.errorOccurred.emit(process.FailedToStart)
        self.assertIsNone(self.client._process)
        self.assertIn("Не удалось запустить", self.errors[0][1])

    def test_stale_read_does_not_publish(self):
        self.client.read_strength(1)
        reading = self.client._process
        self.client.set_strength(68, 2)
        reading.finish(stdout=b"active: yes\ncolor temperature: 3532K\n")
        self.assertEqual(self.values, [])
        self.assertEqual(self.client._process.arguments, ["temp", "2896"])
        self.client._process.finish()
        self.client._process.finish(stdout=b"active: yes\ncolor temperature: 2896K\n")
        self.assertEqual(self.values, [(2, 68)])

    def test_readback_mismatch_reports_real_value(self):
        self.client.set_strength(68, 1)
        self.client._process.finish()
        self.client._process.finish(stdout=b"active: yes\ncolor temperature: 3532K\n")
        self.assertEqual(self.values, [(1, 56)])
        self.assertIn("56% вместо выбранных 68%", self.errors[0][1])

    def test_status_publishes_active_state_with_strength(self):
        self.client.read_strength(1)
        self.client._process.finish(stdout=b"active: no\ncolor temperature: 2896K\nschedule: on\n")
        self.assertEqual(self.values, [(1, 68)])
        self.assertEqual(self.states, [(1, False)])
        self.assertEqual(self.errors, [])

    def test_active_temperature_change_does_not_toggle_night_light(self):
        self.client.set_strength(68, 1)
        self.assertEqual(self.client._process.arguments, ["temp", "2896"])
        self.client._process.finish()
        self.assertEqual(self.client._process.arguments, ["status"])
        self.client._process.finish(stdout=b"active: yes\ncolor temperature: 2896K\n")
        self.assertIsNone(self.client._process)
        self.assertEqual(self.values, [(1, 68)])
        self.assertEqual(self.states, [(1, True)])
        self.assertEqual(self.errors, [])

    def test_temperature_change_does_not_turn_on_inactive_night_light(self):
        self.client.set_strength(68, 1)
        self.client._process.finish()
        self.client._process.finish(stdout=b"active: no\ncolor temperature: 2896K\n")
        self.assertEqual(self.values, [(1, 68)])
        self.assertEqual(self.states, [(1, False)])
        self.assertIsNone(self.client._process)

    def test_unchanged_temperature_still_reaches_cli_for_native_refresh(self):
        self.client.read_strength(1)
        self.client._process.finish(stdout=b"active: yes\ncolor temperature: 2896K\n")
        self.client.set_strength(68, 2)
        self.assertEqual(self.client._process.arguments, ["temp", "2896"])
        self.client._process.finish()
        self.assertEqual(self.client._process.arguments, ["status"])
        self.client._process.finish(stdout=b"active: yes\ncolor temperature: 2896K\n")
        self.assertEqual(self.values, [(1, 68), (2, 68)])
        self.assertIsNone(self.client._process)

    def test_malformed_active_state_does_not_publish_partial_status(self):
        self.client.read_strength(1)
        self.client._process.finish(stdout=b"active: maybe\ncolor temperature: 2896K\n")
        self.assertEqual(self.values, [])
        self.assertEqual(self.states, [])
        self.assertIn("состояние включения", self.errors[0][1])

    def test_failed_verification_can_be_retried_without_another_write(self):
        self.client.set_strength(68, 1)
        self.client._process.finish()
        self.client._on_timeout()
        self.assertEqual(self.values, [])
        self.assertIsNone(self.client._process)
        self.assertIn("вовремя", self.errors[0][1])
        self.client.read_strength(2)
        self.assertEqual(self.client._process.arguments, ["status"])
        self.client._process.finish(stdout=b"active: no\ncolor temperature: 2896K\n")
        self.assertEqual(self.values, [(2, 68)])
        self.assertEqual(self.states, [(2, False)])

    def test_failed_write_and_read_leave_popup_unconfirmed(self):
        with patch("tray.QSystemTrayIcon"):
            controller = TrayController(self.client)
            controller.logger = Mock()
            self.addCleanup(controller.close)
            controller.popup.refresh()
            self.client._process.finish(stdout=b"active: yes\ncolor temperature: 3532K\n")
            controller.popup.slider.setValue(68)
            controller.popup.flush_changes()
            self.client._process.finish(1, stderr=b"write failed")
            self.client._process.finish(1, stderr=b"read failed")
            self.assertEqual(controller.popup.value_label.text(), "68% ?")
            self.assertIn("Значение не подтверждено", controller.popup.status.text())
            self.assertFalse(controller.popup.slider.isEnabled())
            controller.popup.retry.click()
            self.assertEqual(self.client._process.arguments, ["status"])
            self.client._process.finish(stdout=b"active: no\ncolor temperature: 3532K\n")
            self.assertEqual(controller.popup.value_label.text(), "56%")
            self.assertIs(controller.popup.indicator.active, False)

    def test_missing_command_does_not_launch_process(self):
        self.client.command = None
        self.client.read_strength(1)
        self.client.set_strength(68, 2)
        self.assertIsNone(self.client._process)
        self.assertIsNone(self.client._pending_sets.pending)
        self.assertEqual(len(self.errors), 2)

    def test_invalid_value_does_not_launch_process(self):
        self.client.set_strength(101, 3)
        self.assertIsNone(self.client._process)
        self.assertEqual(self.errors[0][0], 3)

    def test_old_process_signal_does_not_complete_new_process(self):
        self.client.set_strength(56, 1)
        first = self.client._process
        self.client.set_strength(68, 2)
        first.finish()
        latest = self.client._process
        first.finish(1, stderr=b"late error")
        self.assertIs(self.client._process, latest)
        self.assertEqual(self.errors, [])
        latest.finish()
        self.client._process.finish(stdout=b"active: yes\ncolor temperature: 2896K\n")
        self.assertEqual(self.values, [(2, 68)])

    def test_old_write_failure_does_not_override_latest_request(self):
        self.client.set_strength(56, 1)
        first = self.client._process
        self.client.set_strength(68, 2)
        first.finish(1, stderr=b"failed")
        self.assertEqual(self.errors, [])
        self.assertEqual(self.client._process.arguments, ["temp", "2896"])
        self.client._process.finish()
        self.client._process.finish(stdout=b"active: yes\ncolor temperature: 2896K\n")
        self.assertEqual(self.values, [(2, 68)])

    def test_crash_with_zero_exit_code_is_not_success(self):
        self.client.read_strength(1)
        self.client._process.finish(
            stdout=b"active: yes\ncolor temperature: 2896K\n", exit_status=1
        )
        self.assertEqual(self.values, [])
        self.assertIn("неожиданно", self.errors[0][1])

    def test_close_cancels_pending_work_and_ignores_late_signals(self):
        self.client.read_strength(1)
        process = self.client._process
        self.client.set_strength(68, 2)
        self.client.close()
        self.client.read_strength(3)
        self.client.set_strength(56, 4)
        process.finish(stdout=b"active: yes\ncolor temperature: 2896K\n")
        self.assertIsNone(self.client._process)
        self.assertIsNone(self.client._pending_sets.pending)
        self.assertFalse(self.client._timer.isActive())
        self.assertEqual(process.state(), process.NotRunning)
        self.assertEqual(self.values, [])
        self.assertEqual(self.errors, [])

    def test_finish_pending_keeps_latest_write_and_its_verification(self):
        drained = []
        self.client.drained.connect(lambda: drained.append(True))
        self.client.set_strength(56, 1)
        first = self.client._process
        self.client.set_strength(68, 2)
        self.client.finish_pending()
        self.client.set_strength(80, 3)
        first.finish()
        self.assertEqual(self.client._process.arguments, ["temp", "2896"])
        self.client._process.finish()
        self.assertEqual(drained, [])
        self.client._process.finish(stdout=b"active: yes\ncolor temperature: 2896K\n")
        self.assertEqual(drained, [True])
        self.assertEqual(self.values, [(2, 68)])

    def test_finish_without_write_does_not_wait_for_regular_read(self):
        drained = []
        self.client.drained.connect(lambda: drained.append(True))
        self.client.read_strength(1)
        self.client.finish_pending()
        self.assertEqual(drained, [True])

    def test_exit_flushes_debounce_and_waits_for_actual_value(self):
        with patch("tray.QSystemTrayIcon"), patch("tray.QCoreApplication.quit") as quit_app:
            controller = TrayController(self.client)
            self.addCleanup(controller.close)
            controller.popup.slider.setValue(56)
            controller.popup.slider.setValue(68)
            controller.request_exit()
            self.assertFalse(controller.popup._debounce.isActive())
            self.assertEqual(self.client._process.arguments, ["temp", "2896"])
            quit_app.assert_not_called()
            self.client._process.finish()
            quit_app.assert_not_called()
            self.client._process.finish(stdout=b"active: yes\ncolor temperature: 2896K\n")
            quit_app.assert_called_once()
            self.assertFalse(controller._exit_timer.isActive())
            controller.request_exit()
            quit_app.assert_called_once()

    def test_exit_reports_failed_write_after_reading_actual_value(self):
        with (
            patch("tray.QSystemTrayIcon"),
            patch("tray.QCoreApplication.quit") as quit_app,
            patch("tray.QMessageBox.warning") as warning,
        ):
            controller = TrayController(self.client)
            controller.logger = Mock()
            self.addCleanup(controller.close)
            controller.popup.slider.setValue(68)
            controller.request_exit()
            self.client._process.finish(1, stderr=b"failed")
            quit_app.assert_not_called()
            self.client._process.finish(stdout=b"active: yes\ncolor temperature: 3532K\n")
            warning.assert_called_once()
            quit_app.assert_called_once()
            self.assertEqual(controller.popup.slider.value(), 56)

    def test_exit_deadline_stops_stuck_process_and_reports_error(self):
        with (
            patch("tray.QSystemTrayIcon"),
            patch("tray.QCoreApplication.quit") as quit_app,
            patch("tray.QMessageBox.warning") as warning,
        ):
            controller = TrayController(self.client)
            controller.logger = Mock()
            self.addCleanup(controller.close)
            controller.popup.slider.setValue(68)
            controller.request_exit()
            controller._exit_timed_out()
            self.assertIsNone(self.client._process)
            self.assertFalse(controller._exit_timer.isActive())
            warning.assert_called_once()
            quit_app.assert_called_once()


if __name__ == "__main__":
    unittest.main()
