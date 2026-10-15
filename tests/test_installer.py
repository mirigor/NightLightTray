"""Проверки обслуживания установщика без изменения настоящего автозапуска"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication

from autostart import SHORTCUT_MARKER, remove_installed_autostart
from main import installer_operation


class InstallerOperationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.lock = Mock()
        self.lock.tryLock.return_value = True

    def operation(self, arguments):
        errors = QLockFile.LockError
        with (
            patch("main.QLockFile", return_value=self.lock) as constructor,
            patch("main.data_directory", return_value=Path("test-data")),
        ):
            constructor.LockError = errors
            return installer_operation(arguments)

    def test_check_does_not_change_autostart_or_start_gui(self):
        with (
            patch("main.remove_installed_autostart") as cleanup,
            patch("main.TrayController") as controller,
        ):
            self.assertEqual(self.operation(["--installer-check"]), 0)
            cleanup.assert_not_called()
            controller.assert_not_called()
            self.lock.unlock.assert_called_once()

    def test_running_gui_blocks_cleanup(self):
        self.lock.tryLock.return_value = False
        self.lock.error.return_value = QLockFile.LockError.LockFailedError
        with patch("main.remove_installed_autostart") as cleanup:
            self.assertEqual(self.operation(["--uninstall-cleanup"]), 3)
            cleanup.assert_not_called()
            self.lock.unlock.assert_not_called()

    def test_lock_error_is_not_reported_as_running_gui(self):
        self.lock.tryLock.return_value = False
        self.lock.error.return_value = QLockFile.LockError.PermissionError
        self.assertEqual(self.operation(["--installer-check"]), 1)

    def test_cleanup_failure_unlocks_and_reports_error(self):
        with patch("main.remove_installed_autostart", side_effect=OSError("ошибка")):
            self.assertEqual(self.operation(["--uninstall-cleanup"]), 1)
            self.lock.unlock.assert_called_once()

    def test_unknown_arguments_have_no_effect(self):
        self.assertEqual(self.operation(["--uninstall-cleanup", "extra"]), 2)
        self.lock.tryLock.assert_not_called()


class InstalledAutostartTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="NightLightTray-installer-")
        self.addCleanup(self.folder.cleanup)
        self.shortcut = Path(self.folder.name) / "NightLightTray.lnk"
        self.shortcut.touch()
        self.data = {"description": SHORTCUT_MARKER, "target": sys.executable, "arguments": ""}

    def cleanup_shortcut(self):
        with (
            patch("autostart.sys.frozen", True, create=True),
            patch("autostart.startup_script_path", return_value=self.shortcut),
            patch("autostart.read_shortcut", return_value=self.data),
        ):
            remove_installed_autostart()

    def test_own_shortcut_to_this_exe_is_removed(self):
        self.cleanup_shortcut()
        self.assertFalse(self.shortcut.exists())

    def test_shortcut_to_another_copy_is_preserved(self):
        self.data["target"] = str(Path(self.folder.name) / "another.exe")
        self.cleanup_shortcut()
        self.assertTrue(self.shortcut.exists())

    def test_foreign_shortcut_is_preserved(self):
        self.data["description"] = "Чужой ярлык"
        self.cleanup_shortcut()
        self.assertTrue(self.shortcut.exists())

    def test_source_launch_is_not_allowed_to_remove_installed_shortcut(self):
        with patch("autostart.sys.frozen", False, create=True):
            with self.assertRaises(OSError):
                remove_installed_autostart()
        self.assertTrue(self.shortcut.exists())

    def test_shortcut_with_other_arguments_is_preserved(self):
        self.data["arguments"] = "other.py"
        self.cleanup_shortcut()
        self.assertTrue(self.shortcut.exists())


if __name__ == "__main__":
    unittest.main()
