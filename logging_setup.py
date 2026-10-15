"""Настройка неболтливого журнала ошибок"""

import logging
from logging.handlers import RotatingFileHandler

from config import data_directory


def configure_logging():
    """Создаёт файловый журнал с ротацией; вызывается один раз при старте"""
    logger = logging.getLogger("nightlight_tray")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        data_directory() / "nightlight-tray.log",
        maxBytes=512 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger
