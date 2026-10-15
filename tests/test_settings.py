"""Проверка галочки автозапуска без изменения настроек настоящего пользователя"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from settings import SettingsMenu


class SettingsMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.menu = SettingsMenu()
        self.addCleanup(self.menu.deleteLater)
        self.errors = []
        self.menu.operation_error.connect(self.errors.append)

    def test_opening_submenu_reads_external_changes_without_writing(self):
        with (
            patch("settings.is_enabled", side_effect=[False, True]),
            patch("settings.set_enabled") as write,
        ):
            self.menu.aboutToShow.emit()
            self.assertFalse(self.menu.autostart.isChecked())
            self.assertTrue(self.menu.autostart.isEnabled())
            self.menu.aboutToShow.emit()
            self.assertTrue(self.menu.autostart.isChecked())
            write.assert_not_called()

    def test_click_enables_and_disables_autostart_immediately(self):
        state = {"enabled": False}

        def write(enabled):
            state["enabled"] = enabled

        with (
            patch("settings.is_enabled", side_effect=lambda: state["enabled"]),
            patch("settings.set_enabled", side_effect=write) as save,
        ):
            self.menu.refresh()
            self.menu.autostart.trigger()
            save.assert_called_with(True)
            self.assertTrue(state["enabled"])
            self.assertTrue(self.menu.autostart.isChecked())
            self.menu.autostart.trigger()
            save.assert_called_with(False)
            self.assertFalse(state["enabled"])
            self.assertFalse(self.menu.autostart.isChecked())
            self.assertEqual(save.call_count, 2)
            self.assertEqual(self.errors, [])

    @unittest.skipUnless(os.name == "nt", "Ярлыки автозапуска доступны только на Windows")
    def test_click_creates_and_removes_real_shortcut_in_isolated_folder(self):
        with tempfile.TemporaryDirectory(prefix="NightLightTray настройки ") as folder:
            shortcut = Path(folder) / "NightLightTray.lnk"
            with patch("autostart.startup_script_path", return_value=shortcut):
                self.menu.refresh()
                self.menu.autostart.trigger()
                self.assertTrue(shortcut.is_file())
                self.assertTrue(self.menu.autostart.isChecked())
                self.menu.autostart.trigger()
                self.assertFalse(shortcut.exists())
                self.assertFalse(self.menu.autostart.isChecked())
                self.assertEqual(self.errors, [])

    def test_failed_change_restores_actual_checkmark(self):
        for enabled in (False, True):
            with (
                self.subTest(enabled=enabled),
                patch("settings.is_enabled", return_value=enabled),
                patch("settings.set_enabled", side_effect=OSError("Нет доступа")),
            ):
                self.menu.refresh()
                self.menu.autostart.trigger()
                self.assertEqual(self.menu.autostart.isChecked(), enabled)
                self.assertTrue(self.menu.autostart.isEnabled())
                self.assertIn("Не удалось изменить автозапуск", self.errors[-1])

    def test_partial_failure_reads_actual_setting_instead_of_assuming_rollback(self):
        with (
            patch("settings.is_enabled", side_effect=[False, True]),
            patch("settings.set_enabled", side_effect=OSError("Ошибка удаления старого файла")),
        ):
            self.menu.refresh()
            self.menu.autostart.trigger()
            self.assertTrue(self.menu.autostart.isChecked())
            self.assertEqual(len(self.errors), 1)

    def test_read_error_disables_toggle_and_next_open_recovers(self):
        with (
            patch("settings.is_enabled", side_effect=[OSError("Нет доступа"), True]),
            patch("settings.set_enabled") as write,
        ):
            self.menu.aboutToShow.emit()
            self.assertFalse(self.menu.autostart.isEnabled())
            self.menu._set_autostart(True)
            write.assert_not_called()
            self.assertIn("Не удалось проверить автозапуск", self.errors[0])
            self.menu.aboutToShow.emit()
            self.assertTrue(self.menu.autostart.isEnabled())
            self.assertTrue(self.menu.autostart.isChecked())

    def test_failed_readback_restores_last_known_state_and_disables_toggle(self):
        with (
            patch("settings.is_enabled", side_effect=[False, OSError("Нет доступа")]),
            patch("settings.set_enabled"),
        ):
            self.menu.refresh()
            self.menu.autostart.trigger()
            self.assertFalse(self.menu.autostart.isChecked())
            self.assertFalse(self.menu.autostart.isEnabled())
            self.assertIn("Не удалось проверить автозапуск", self.errors[0])


if __name__ == "__main__":
    unittest.main()
