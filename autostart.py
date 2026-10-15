"""Управление автозапуском без прав администратора"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from config import application_directory, resource_path, startup_script_path
from windows_shortcut import read_shortcut, write_shortcut

MARKER = "' NightLightTray autorun"
SHORTCUT_MARKER = "NightLightTray — автозапуск"


def _paths(script):
    """Возвращает ярлык и оба старых формата для безопасной миграции"""
    shortcut = Path(script) if script else startup_script_path()
    shortcut = shortcut.with_suffix(".lnk")
    return shortcut, shortcut.with_suffix(".vbs"), shortcut.with_suffix(".cmd")


def _owned(script):
    """Проверяет, что файл создан приложением, прежде чем его заменить или удалить"""
    if not script.is_file():
        return False
    if script.suffix.lower() == ".lnk":
        try:
            return read_shortcut(script)["description"] == SHORTCUT_MARKER
        except OSError:
            return False
    if script.suffix.lower() == ".vbs":
        try:
            lines = script.read_text(encoding="utf-16").splitlines()
        except UnicodeError:
            return False
        return (
            len(lines) == 2
            and lines[0] == MARKER
            and re.fullmatch(
                r'CreateObject\("WScript\.Shell"\)\.Run "(?:""|[^"])*", 0, False', lines[1]
            )
            is not None
        )
    try:
        content = script.read_text(encoding="utf-8")
    except UnicodeError:
        return False
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    return (
        len(lines) == 2
        and lines[0].lower() == "@echo off"
        and lines[1].lower().startswith('start "" /b ')
        and ("NightLightTray.exe" in content or "main.py" in content)
    )


def is_enabled(script=None):
    """Распознаёт ярлык либо принадлежащий приложению старый автозапуск"""
    return any(_owned(entry) for entry in _paths(script))


def _target():
    """Разделяет путь и аргументы: кириллица и пробелы сохраняются в самом ярлыке"""
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        arguments = ""
        icon = executable
    else:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw.is_file():
            raise OSError("Для автозапуска из исходников требуется pythonw.exe.")
        executable = pythonw.resolve()
        arguments = subprocess.list2cmdline([str(application_directory() / "main.py")])
        icon = resource_path("resources", "moon.ico")
    return {
        "target": str(executable),
        "arguments": arguments,
        "working_directory": str(application_directory()),
        "description": SHORTCUT_MARKER,
        "show_command": 7,
        "icon": str(icon),
        "icon_index": 0,
    }


def set_enabled(enabled, script=None):
    """Атомарно создаёт ярлык и удаляет только проверенные старые файлы приложения"""
    shortcut, *legacy = _paths(script)
    entries = [shortcut] + legacy
    for entry in entries:
        if entry.exists() and not _owned(entry):
            raise OSError(
                "Файл автозапуска {} существует, но не принадлежит приложению.".format(entry.name)
            )
    if enabled:
        shortcut.parent.mkdir(parents=True, exist_ok=True)
        data = _target()
        if (
            shortcut.is_file()
            and read_shortcut(shortcut) == data
            and not any(entry.exists() for entry in legacy)
        ):
            return
        temporary = None
        try:
            descriptor, name = tempfile.mkstemp(
                dir=shortcut.parent, prefix="NightLightTray-", suffix=".tmp"
            )
            os.close(descriptor)
            temporary = Path(name)
            write_shortcut(temporary, data)
            os.replace(temporary, shortcut)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        for entry in legacy:
            if entry.is_file():
                entry.unlink()
    else:
        for entry in entries:
            if entry.is_file():
                entry.unlink()


def refresh_enabled():
    """Обновляет путь включённого автозапуска после переноса EXE, не включая выключенный"""
    if is_enabled():
        set_enabled(True)


def remove_installed_autostart():
    """Удаляет только собственный ярлык, направленный на удаляемый EXE"""
    if not getattr(sys, "frozen", False):
        raise OSError("Удаление установленного автозапуска доступно только из EXE.")
    shortcut = startup_script_path()
    if not _owned(shortcut):
        return
    data = read_shortcut(shortcut)
    if Path(data["target"]).resolve() == Path(sys.executable).resolve() and not data["arguments"]:
        shortcut.unlink()
