"""Пути и небольшие настройки приложения"""

import os
import sys
from pathlib import Path

APP_NAME = "NightLight Tray"
APP_ID = "NightLightTray"
TRAY_STARTUP_RETRY_MS = 2000
TRAY_STARTUP_TIMEOUT_MS = 60000
PROCESS_TIMEOUT_MS = 7000
SLIDER_DEBOUNCE_MS = 160
EXIT_TIMEOUT_MS = PROCESS_TIMEOUT_MS * 5 + 1000


def application_directory():
    """Возвращает папку EXE либо исходного файла при запуске из исходников"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(*parts):
    """Находит ресурс как при обычном запуске, так и после PyInstaller"""
    base = Path(getattr(sys, "_MEIPASS", application_directory()))
    return base.joinpath(*parts)


def data_directory():
    """Папка для журнала; не содержит настроек ночного света"""
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    folder = base / "NightLightTray"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def startup_script_path():
    """Путь к файлу автозапуска текущего пользователя"""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise OSError("Не найдена папка AppData текущего пользователя.")
    startup = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return startup / "NightLightTray.lnk"
