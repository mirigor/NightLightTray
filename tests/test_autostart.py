"""Проверки настоящих ярлыков в временной папке без изменения автозапуска Windows"""

import ctypes
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from autostart import MARKER, SHORTCUT_MARKER, is_enabled, refresh_enabled, set_enabled
from windows_shortcut import read_shortcut, write_shortcut


def target_data(folder, name="NightLightTray.exe"):
    """Создаёт безопасную цель для проверки свойств ярлыка; цель не запускается"""
    target = Path(folder) / "Программы с пробелами" / name
    target.parent.mkdir(exist_ok=True)
    target.touch()
    return {
        "target": str(target),
        "arguments": "",
        "working_directory": str(target.parent),
        "description": SHORTCUT_MARKER,
        "show_command": 7,
        "icon": str(target),
        "icon_index": 0,
    }


def old_vbs(path):
    path.write_text(
        MARKER
        + '\nCreateObject("WScript.Shell").Run """C:\\Old\\NightLightTray.exe""", 0, False\n',
        encoding="utf-16",
    )


@unittest.skipUnless(os.name == "nt", "Нужен механизм ярлыков Windows")
class AutostartTests(unittest.TestCase):
    def test_enable_disable_and_unicode_shortcut_metadata(self):
        with tempfile.TemporaryDirectory(prefix="Ночной свет ") as folder:
            shortcut = Path(folder) / "Автозагрузка с пробелами" / "NightLightTray.lnk"
            data = target_data(folder)
            self.assertFalse(is_enabled(shortcut))
            with patch("autostart._target", return_value=data):
                set_enabled(True, shortcut)
            self.assertTrue(is_enabled(shortcut))
            self.assertEqual(read_shortcut(shortcut), data)
            set_enabled(False, shortcut)
            self.assertFalse(is_enabled(shortcut))

    def test_corrupt_foreign_shortcut_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            shortcut = Path(folder) / "NightLightTray.lnk"
            shortcut.write_bytes(b"foreign content")
            self.assertFalse(is_enabled(shortcut))
            with self.assertRaises(OSError):
                set_enabled(True, shortcut)
            self.assertEqual(shortcut.read_bytes(), b"foreign content")

    def test_valid_foreign_shortcut_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            shortcut = Path(folder) / "NightLightTray.lnk"
            data = target_data(folder)
            data["description"] = "Чужой ярлык"
            write_shortcut(shortcut, data)
            self.assertFalse(is_enabled(shortcut))
            with self.assertRaises(OSError):
                set_enabled(False, shortcut)
            self.assertTrue(shortcut.exists())

    def test_both_old_formats_migrate_only_after_new_link_is_created(self):
        with tempfile.TemporaryDirectory() as folder:
            shortcut = Path(folder) / "NightLightTray.lnk"
            vbs, cmd = shortcut.with_suffix(".vbs"), shortcut.with_suffix(".cmd")
            old_vbs(vbs)
            cmd.write_text(
                '@echo off\nstart "" /b "C:\\Old\\NightLightTray.exe"\n', encoding="utf-8"
            )
            self.assertTrue(is_enabled(shortcut))
            with patch("autostart._target", return_value=target_data(folder)):
                set_enabled(True, shortcut)
            self.assertTrue(shortcut.exists())
            self.assertFalse(vbs.exists())
            self.assertFalse(cmd.exists())

    def test_failed_migration_preserves_old_autostart(self):
        with tempfile.TemporaryDirectory() as folder:
            shortcut = Path(folder) / "NightLightTray.lnk"
            vbs = shortcut.with_suffix(".vbs")
            old_vbs(vbs)
            previous = vbs.read_bytes()
            with patch("autostart.write_shortcut", side_effect=OSError("failed")):
                with self.assertRaises(OSError):
                    set_enabled(True, shortcut)
            self.assertFalse(shortcut.exists())
            self.assertEqual(vbs.read_bytes(), previous)
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_unknown_legacy_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            shortcut = Path(folder) / "NightLightTray.lnk"
            legacy = shortcut.with_suffix(".vbs")
            legacy.write_bytes(b"foreign plain text")
            self.assertFalse(is_enabled(shortcut))
            with self.assertRaises(OSError):
                set_enabled(True, shortcut)
            self.assertEqual(legacy.read_bytes(), b"foreign plain text")

    def test_refresh_updates_moved_exe_without_rewriting_unchanged_link(self):
        with tempfile.TemporaryDirectory() as folder:
            shortcut = Path(folder) / "NightLightTray.lnk"
            with patch("autostart._target", return_value=target_data(folder, "Old.exe")):
                set_enabled(True, shortcut)
            desired = target_data(folder)
            with (
                patch("autostart.startup_script_path", return_value=shortcut),
                patch("autostart._target", return_value=desired),
            ):
                refresh_enabled()
                self.assertEqual(read_shortcut(shortcut), desired)
                with patch("autostart.os.replace") as replace:
                    refresh_enabled()
                    replace.assert_not_called()

    def test_refresh_does_not_enable_disabled_autostart(self):
        with tempfile.TemporaryDirectory() as folder:
            shortcut = Path(folder) / "NightLightTray.lnk"
            with (
                patch("autostart.startup_script_path", return_value=shortcut),
                patch("autostart._target") as target,
            ):
                refresh_enabled()
                target.assert_not_called()
            self.assertFalse(shortcut.exists())

    def test_failed_replace_preserves_existing_shortcut(self):
        with tempfile.TemporaryDirectory() as folder:
            shortcut = Path(folder) / "NightLightTray.lnk"
            with patch("autostart._target", return_value=target_data(folder, "Old.exe")):
                set_enabled(True, shortcut)
            previous = shortcut.read_bytes()
            with (
                patch("autostart._target", return_value=target_data(folder)),
                patch("autostart.os.replace", side_effect=OSError("failed")),
            ):
                with self.assertRaises(OSError):
                    set_enabled(True, shortcut)
            self.assertEqual(shortcut.read_bytes(), previous)
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_disable_also_removes_owned_legacy_file(self):
        with tempfile.TemporaryDirectory() as folder:
            shortcut = Path(folder) / "NightLightTray.lnk"
            legacy = shortcut.with_suffix(".vbs")
            old_vbs(legacy)
            set_enabled(False, shortcut)
            self.assertFalse(legacy.exists())
            self.assertFalse(is_enabled(shortcut))

    def test_windows_shell_launches_unicode_target_without_script_host(self):
        with tempfile.TemporaryDirectory(prefix="Ночной свет ") as folder:
            root = Path(folder)
            helper = root / "Программа с пробелами.py"
            marker = root / "started.txt"
            helper.write_text(
                'from pathlib import Path\nPath({!r}).write_text("started", encoding="utf-8")\n'.format(
                    str(marker)
                ),
                encoding="utf-8",
            )
            data = {
                "target": str(Path(sys.executable).with_name("pythonw.exe")),
                "arguments": subprocess.list2cmdline([str(helper)]),
                "working_directory": folder,
                "description": SHORTCUT_MARKER,
                "show_command": 7,
                "icon": str(Path(sys.executable)),
                "icon_index": 0,
            }
            shortcut = root / "NightLightTray.lnk"
            with patch("autostart._target", return_value=data):
                set_enabled(True, shortcut)
            shell = ctypes.WinDLL("shell32", use_last_error=True)
            shell.ShellExecuteW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_wchar_p,
                ctypes.c_wchar_p,
                ctypes.c_wchar_p,
                ctypes.c_wchar_p,
                ctypes.c_int,
            ]
            shell.ShellExecuteW.restype = ctypes.c_void_p
            result = shell.ShellExecuteW(None, "open", str(shortcut), None, None, 0)
            self.assertGreater(result, 32)
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists(), "Windows не запустила цель ярлыка")


if __name__ == "__main__":
    unittest.main()
