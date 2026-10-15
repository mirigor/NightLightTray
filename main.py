"""Точка входа NightLight Tray"""

import sys

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QLockFile, QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from autostart import remove_installed_autostart
from config import APP_ID, APP_NAME, TRAY_STARTUP_RETRY_MS, TRAY_STARTUP_TIMEOUT_MS, data_directory
from logging_setup import configure_logging
from nightlight import NightLightClient
from tray import SingleInstance, TrayController


def installer_operation(arguments):
    """Обслуживает установщик без запуска трея и без изменения ночного света"""
    if arguments not in (["--installer-check"], ["--uninstall-cleanup"]):
        return 2
    app = QCoreApplication.instance() or QCoreApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    try:
        lock = QLockFile(str(data_directory() / "instance.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            return 3 if lock.error() == QLockFile.LockError.LockFailedError else 1
        try:
            if arguments == ["--uninstall-cleanup"]:
                remove_installed_autostart()
            return 0
        finally:
            lock.unlock()
    except OSError:
        return 1


class TrayStartup(QObject):
    """Ожидает готовности трея при входе в Windows, не блокируя цикл событий"""

    ready = Signal()
    unavailable = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._started = False
        self._waiting = False
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(TRAY_STARTUP_RETRY_MS)
        self._timer.timeout.connect(self._check)

    def start(self):
        if self._started:
            return
        self._started = True
        self._waiting = True
        self._elapsed.start()
        self._check()

    def _check(self):
        if not self._waiting:
            return
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.stop()
            self.ready.emit()
        elif self._elapsed.elapsed() >= TRAY_STARTUP_TIMEOUT_MS:
            self.stop()
            self.unavailable.emit()
        else:
            self._timer.start()

    def stop(self):
        self._waiting = False
        self._timer.stop()


def main():
    """Запускает приложение без главного окна"""
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ID)
    app.setQuitOnLastWindowClosed(False)
    holder = {}
    single = None
    startup = None

    def activate():
        if "controller" in holder:
            holder["controller"].show_popup()
        else:
            holder["show_requested"] = True

    def start_controller():
        try:
            controller = TrayController(NightLightClient())
            holder["controller"] = controller
            app.aboutToQuit.connect(controller.close)
            controller.start()
            if holder.get("show_requested"):
                controller.show_popup()
        except OSError:
            logger.exception("Не удалось запустить приложение после появления трея")
            QMessageBox.critical(
                None, APP_NAME, "Не удалось запустить приложение. Проверьте журнал NightLight Tray."
            )
            app.exit(1)

    def tray_unavailable():
        logger.error("Системный трей не появился за время ожидания")
        QMessageBox.warning(
            None,
            APP_NAME,
            "Системный трей Windows не появился за минуту.\nПопробуйте запустить NightLight Tray после загрузки рабочего стола.",
        )
        app.exit(1)

    try:
        single = SingleInstance(activate)
        if not single.acquire():
            return 0
        logger = configure_logging()
        startup = TrayStartup(app)
        startup.ready.connect(start_controller)
        startup.unavailable.connect(tray_unavailable)
        app.aboutToQuit.connect(startup.stop)
        QTimer.singleShot(0, startup.start)
        return app.exec()
    except OSError:
        QMessageBox.critical(
            None,
            APP_NAME,
            "Не удалось запустить приложение. Проверьте доступ к папке LocalAppData и журналу NightLight Tray.",
        )
        return 1
    finally:
        if startup is not None:
            startup.stop()
            startup.deleteLater()
        if single is not None:
            single.close()


if __name__ == "__main__":
    if sys.argv[1:] and sys.argv[1] in ("--installer-check", "--uninstall-cleanup"):
        sys.exit(installer_operation(sys.argv[1:]))
    sys.exit(main())
