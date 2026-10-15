"""Подменю настроек в системном трее"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMenu

from autostart import is_enabled, set_enabled


class SettingsMenu(QMenu):
    """Переключает автозапуск прямо из меню и проверяет его фактическое состояние"""

    operation_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__("Настройки", parent)
        self._last_enabled = None
        self.autostart = self.addAction("Автозапуск при старте Windows")
        self.autostart.setCheckable(True)
        self.autostart.setEnabled(False)
        self.autostart.triggered.connect(self._set_autostart)
        self.aboutToShow.connect(self.refresh)

    def refresh(self):
        """Читает настройку при открытии подменю, не включая фоновый опрос"""
        try:
            enabled = is_enabled()
        except (OSError, UnicodeError) as error:
            if self._last_enabled is not None:
                self.autostart.setChecked(self._last_enabled)
            self.autostart.setEnabled(False)
            self.autostart.setToolTip("Не удалось проверить состояние автозапуска.")
            self.operation_error.emit("Не удалось проверить автозапуск: {}".format(error))
            return
        self._last_enabled = enabled
        self.autostart.setChecked(enabled)
        self.autostart.setEnabled(True)
        self.autostart.setToolTip("")

    def _set_autostart(self, enabled):
        if not self.autostart.isEnabled():
            return
        try:
            set_enabled(enabled)
        except (OSError, UnicodeError) as error:
            self.operation_error.emit("Не удалось изменить автозапуск: {}".format(error))
        self.refresh()
