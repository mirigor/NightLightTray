"""Значок трея, меню и жизненный цикл приложения"""

import ctypes
import getpass
import logging
import time
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QLockFile, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QMenu, QMessageBox, QSystemTrayIcon

from autostart import refresh_enabled
from config import APP_ID, EXIT_TIMEOUT_MS, data_directory, resource_path
from popup import NightLightPopup
from settings import SettingsMenu


class PowerMessage(ctypes.Structure):
    """Начальные поля Windows MSG, достаточные для события пробуждения"""

    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
    ]


class ResumeEventFilter(QAbstractNativeEventFilter):
    """Отмечает пробуждение без фонового опроса системы"""

    def __init__(self, client):
        super().__init__()
        self.client = client

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            event = ctypes.cast(int(message), ctypes.POINTER(PowerMessage)).contents
            if event.message == 0x0218 and event.wParam in (0x0006, 0x0007, 0x0012):
                self.client.mark_resumed()
        return False


class SingleInstance:
    """Передаёт повторный запуск уже работающему процессу без второй иконки"""

    def __init__(self, activate):
        self.name = "{}-{}".format(APP_ID, getpass.getuser())
        self.activate = activate
        self.lock = QLockFile(str(data_directory() / "instance.lock"))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer()
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept_connection)

    def acquire(self):
        # На Windows listen() допускает несколько серверов на одной named pipe
        # Межпроцессная блокировка должна быть получена раньше создания сервера
        if not self.lock.tryLock(0):
            if self.lock.error() != QLockFile.LockError.LockFailedError:
                raise OSError("Не удалось создать блокировку экземпляра приложения.")
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            if socket.waitForConnected(400):
                socket.write(b"show")
                socket.waitForBytesWritten(200)
                socket.disconnectFromServer()
            return False
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self.lock.unlock()
            raise OSError("Не удалось создать канал связи с приложением.")
        return True

    def _accept_connection(self):
        socket = self.server.nextPendingConnection()
        if socket:
            socket.disconnectFromServer()
            socket.deleteLater()
            self.activate()

    def close(self):
        if self.lock.isLocked():
            self.server.close()
            QLocalServer.removeServer(self.name)
            self.lock.unlock()


class TrayController:
    """Связывает клиент CLI, popup и действия контекстного меню"""

    def __init__(self, client):
        self.client = client
        self.logger = logging.getLogger("nightlight_tray")
        self._last_notification = None
        self._exiting = False
        self._exit_error = None
        self._exit_finished = False
        self._power_filter = None
        self._exit_timer = QTimer(client)
        self._exit_timer.setSingleShot(True)
        self._exit_timer.setInterval(EXIT_TIMEOUT_MS)
        self._exit_timer.timeout.connect(self._exit_timed_out)
        self.popup = NightLightPopup(client)
        self.tray = QSystemTrayIcon(QIcon(str(resource_path("resources", "moon.svg"))))
        self.tray.setToolTip("NightLight Tray")
        self._create_menu()
        self.tray.activated.connect(self._activated)
        client.operation_error.connect(self._notify_error)
        client.drained.connect(self._finish_exit)

    def _create_menu(self):
        menu = QMenu()
        self._menu = menu
        open_action = QAction("Открыть", menu)
        open_action.triggered.connect(self.show_popup)
        exit_action = QAction("Выход", menu)
        exit_action.triggered.connect(self.request_exit)
        menu.addAction(open_action)
        self._settings_menu = SettingsMenu(menu)
        self._settings_menu.operation_error.connect(lambda message: self._notify_error(0, message))
        menu.addMenu(self._settings_menu)
        menu.addSeparator()
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)

    def start(self):
        self.popup.winId()
        self._power_filter = ResumeEventFilter(self.client)
        QCoreApplication.instance().installNativeEventFilter(self._power_filter)
        self.tray.show()
        try:
            refresh_enabled()
        except OSError as error:
            self._notify_error(0, "Не удалось обновить путь автозапуска: {}".format(error))
        self.client.read_strength()

    def _activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_popup()

    def toggle_popup(self):
        if self._exiting:
            return
        if self.popup.isVisible():
            self.popup.hide()
        else:
            self.show_popup()

    def show_popup(self):
        """Открывает окно, в том числе при повторном запуске программы"""
        if self._exiting:
            return
        self.popup.open_near(self.tray.geometry())

    def _notify_error(self, _generation, message):
        self.logger.error(message)
        if self._exiting:
            self._exit_error = message
        now = time.monotonic()
        if (
            self._last_notification
            and self._last_notification[0] == message
            and now - self._last_notification[1] < 5
        ):
            return
        self._last_notification = (message, now)
        self.tray.showMessage("NightLight Tray", message, QSystemTrayIcon.MessageIcon.Warning, 6000)

    def close(self):
        """Завершает процессы и скрывает значок при выходе"""
        if self._power_filter is not None:
            QCoreApplication.instance().removeNativeEventFilter(self._power_filter)
            self._power_filter = None
        self._exit_timer.stop()
        self.popup.stop()
        self.client.close()
        self.tray.hide()

    def request_exit(self):
        """Асинхронно применяет последнее значение и только затем закрывает программу"""
        if self._exiting:
            return
        self._exiting = True
        self.tray.contextMenu().setEnabled(False)
        self.tray.setToolTip("NightLight Tray — завершение…")
        self.popup.setEnabled(False)
        self._exit_timer.start()
        self.popup.flush_changes()
        self.popup.hide()
        self.client.finish_pending()

    def _exit_timed_out(self):
        self._exit_error = "Не удалось завершить применение интенсивности вовремя. Последнее значение не подтверждено."
        self.logger.error(self._exit_error)
        self.client.close()
        self._finish_exit()

    def _finish_exit(self):
        if not self._exiting or self._exit_finished:
            return
        self._exit_finished = True
        self._exit_timer.stop()
        if self._exit_error:
            QMessageBox.warning(
                None,
                "NightLight Tray",
                "Не удалось подтвердить последнее значение перед выходом.\n\n" + self._exit_error,
            )
        QCoreApplication.quit()
