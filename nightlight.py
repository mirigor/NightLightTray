"""Асинхронное управление штатным ночным светом через win-nightlight-cli"""

import os
import re
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from config import PROCESS_TIMEOUT_MS, application_directory, resource_path

MIN_KELVIN = 1200
MAX_KELVIN = 6500
MISSING_COMMAND_MESSAGE = (
    "Не найден wnl.exe. Поместите его в папку tools рядом с приложением "
    "или установите win-nightlight-cli и перезапустите приложение."
)


class NightLightError(Exception):
    """Ошибка запуска или ответа win-nightlight-cli"""


def strength_to_kelvin(value):
    """Переводит целую интенсивность 0..100 в системную температуру 6500..1200 K"""
    if type(value) is not int or not 0 <= value <= 100:
        raise NightLightError("Интенсивность должна быть целым числом от 0 до 100.")
    return MAX_KELVIN - 53 * value


def parse_temperature(output):
    """Извлекает и проверяет числовую температуру из ``wnl status``"""
    fields = [
        field.strip()
        for field in re.findall(r"^[ \t]*color temperature:[ \t]*([^\r\n]*)", output, re.MULTILINE)
    ]
    if fields == ["Windows default"]:
        raise NightLightError(
            "Windows не сохранила числовую интенсивность. Один раз измените "
            "ползунок в параметрах «Ночного света» и откройте окно снова."
        )
    if len(fields) != 1 or not re.fullmatch(r"\d{4}K\s*", fields[0]):
        raise NightLightError("Не удалось прочитать интенсивность из ответа wnl status.")
    kelvin = int(fields[0].strip()[:-1])
    if not MIN_KELVIN <= kelvin <= MAX_KELVIN:
        raise NightLightError("wnl вернул температуру вне диапазона 1200–6500 K.")
    return kelvin


def parse_strength(output):
    """Переводит прочитанную температуру в проценты, не выдумывая значение Windows"""
    kelvin = parse_temperature(output)
    # Шаг ползунка равен 53 K; округляем к ближайшему целому проценту
    return (MAX_KELVIN - kelvin + 26) // 53


def parse_active(output):
    """Читает фактическое включение из status, не путая его с расписанием"""
    fields = [
        field.strip()
        for field in re.findall(r"^[ \t]*active:[ \t]*([^\r\n]*)", output, re.MULTILINE)
    ]
    if fields not in (["yes"], ["no"]):
        raise NightLightError("Не удалось прочитать состояние включения из ответа wnl status.")
    return fields[0] == "yes"


def process_error(exit_code, stderr, timed_out=False):
    """Превращает технический результат процесса в короткое сообщение для пользователя"""
    if timed_out:
        return "Команда wnl не ответила вовремя."
    details = stderr.strip().splitlines()
    if details:
        return "wnl: " + details[-1][:240]
    return "wnl завершился с кодом {}.".format(exit_code)


def find_wnl(extra_paths=None):
    """Ищет EXE рядом с приложением, в сборке PyInstaller, PATH и папке Cargo"""
    configured = os.environ.get("NIGHTLIGHT_WNL")
    if configured:
        candidates = [Path(configured)]
    else:
        candidates = [
            application_directory() / "tools" / "wnl.exe",
            application_directory() / "wnl.exe",
            resource_path("tools", "wnl.exe"),
        ]
        found = shutil.which("wnl.exe")
        if found:
            candidates.append(Path(found))
        cargo_home = os.environ.get("CARGO_HOME")
        if cargo_home:
            candidates.append(Path(cargo_home) / "bin" / "wnl.exe")
        candidates.append(Path.home() / ".cargo" / "bin" / "wnl.exe")
        if extra_paths:
            candidates.extend(Path(item) for item in extra_paths)
    for candidate in candidates:
        try:
            if candidate.suffix.lower() == ".exe" and candidate.is_file():
                return str(candidate.resolve())
        except OSError:
            # Недоступная папка не должна мешать проверке остальных кандидатов
            continue
    return None


class LatestRequest:
    """Хранит только последнее движение ползунка и отбрасывает устаревшие ответы"""

    def __init__(self):
        self.generation = 0
        self.pending = None

    def submit(self, value, generation=None):
        if generation is None:
            self.generation += 1
        else:
            self.generation = max(self.generation + 1, generation)
        self.pending = (value, self.generation)
        return self.generation

    def take(self):
        value = self.pending
        self.pending = None
        return value

    def current(self, generation):
        return generation == self.generation


class NightLightClient(QObject):
    """Последовательно выполняет команды CLI через QProcess, не блокируя интерфейс"""

    status_ready = Signal(int, int, bool)
    operation_error = Signal(int, str)
    command_finished = Signal(int)
    drained = Signal()

    def __init__(self, command=None, parent=None):
        super().__init__(parent)
        self.command = command if command is not None else find_wnl()
        self._process = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._kind = None
        self._generation = 0
        self._timed_out = False
        self._pending_sets = LatestRequest()
        self._pending_read = None
        self._verification = None
        self._wake_recovery = False
        self._recovery_generation = None
        self._closing = False
        self._finishing = False

    @property
    def available(self):
        return bool(self.command)

    def mark_resumed(self):
        """Запоминает пробуждение до следующего изменения интенсивности"""
        if not self._closing:
            self._wake_recovery = True

    def read_strength(self, generation=0):
        """Запрашивает реальную интенсивность. Новый запрос заменяет ожидающий старый"""
        if self._closing or self._finishing:
            return
        if not self.available:
            self.operation_error.emit(generation, MISSING_COMMAND_MESSAGE)
            return
        self._enqueue_read(generation)

    def _enqueue_read(self, generation):
        """Ставит чтение в очередь, включая проверку записи при завершении"""
        if self._pending_read is None:
            self._pending_read = generation
        else:
            self._pending_read = max(self._pending_read, generation)
        self._start_next()

    def set_strength(self, value, generation=None):
        """Ставит изменение в очередь; несколько быстрых изменений схлопываются в последнее"""
        if self._closing or self._finishing:
            return 0
        try:
            strength_to_kelvin(value)
        except NightLightError as error:
            self.operation_error.emit(generation or 0, str(error))
            return 0
        generation = self._pending_sets.submit(value, generation)
        if not self.available:
            self._pending_sets.take()
            self.operation_error.emit(generation, MISSING_COMMAND_MESSAGE)
            return generation
        self._start_next()
        return generation

    def _start_next(self):
        if self._closing or self._process is not None:
            return
        pending_set = self._pending_sets.take()
        if pending_set:
            value, generation = pending_set
            self._recovery_generation = None
            self._verification = (generation, value)
            self._run("set", ["temp", str(strength_to_kelvin(value))], generation)
            return
        if self._pending_read is not None:
            generation = self._pending_read
            self._pending_read = None
            self._run("read", ["status"], generation)
            return
        if self._finishing:
            self.drained.emit()

    def _run(self, kind, arguments, generation):
        self._kind = kind
        self._generation = generation
        self._timed_out = False
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process = self._process
        process.finished.connect(lambda code, status: self._on_finished(process, code, status))
        process.errorOccurred.connect(lambda error: self._on_process_error(process, error))
        self._timer.start(PROCESS_TIMEOUT_MS)
        self._process.start(self.command, arguments)

    def _on_timeout(self):
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            self._timed_out = True
            self._process.kill()

    def _on_process_error(self, process, error):
        # После убийства по таймауту приходит finished: именно он сообщит причину
        if process is self._process and error == QProcess.ProcessError.FailedToStart:
            self._complete(False, "Не удалось запустить wnl.exe.")

    def _on_finished(self, process, exit_code, exit_status):
        if process is not self._process:
            return
        stdout = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        stderr = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace")
        if self._timed_out or exit_code != 0:
            self._complete(False, process_error(exit_code, stderr, self._timed_out))
            return
        if exit_status == QProcess.ExitStatus.CrashExit:
            self._complete(False, "wnl неожиданно завершился. Попробуйте открыть ползунок снова.")
            return
        if self._kind == "read":
            try:
                value = parse_strength(stdout)
                active = parse_active(stdout)
            except NightLightError as error:
                self._complete(False, str(error))
                return
            generation = self._generation
            verification = self._verification
            if (
                self._wake_recovery
                and verification == (generation, value)
                and active
                and generation >= self._pending_sets.generation
                and self._pending_sets.pending is None
            ):
                self._wake_recovery = False
                self._recovery_generation = generation
                self._clear_process()
                self._run("resume_off", ["off"], generation)
                return
            if verification == (generation, value) and not active:
                self._wake_recovery = False
            self._verification = None
            if self._recovery_generation == generation:
                self._recovery_generation = None
                if not active:
                    self.operation_error.emit(
                        generation,
                        "После пробуждения ночной свет не включился снова. Проверьте его в параметрах Windows.",
                    )
            self._clear_process()
            if generation >= self._pending_sets.generation:
                self.status_ready.emit(generation, value, active)
                if verification and value != verification[1]:
                    self.operation_error.emit(
                        generation,
                        "Windows вернула {}% вместо выбранных {}%. Показано фактическое значение.".format(
                            value, verification[1]
                        ),
                    )
            self.command_finished.emit(generation)
            self._start_next()
            return
        if self._kind == "resume_off":
            generation = self._generation
            self._clear_process()
            self._run("resume_on", ["on"], generation)
            return
        if self._kind == "resume_on":
            generation = self._generation
            self._clear_process()
            if self._pending_sets.pending:
                self._wake_recovery = True
            self._enqueue_read(generation)
            return
        generation = self._generation
        self._clear_process()
        # Если пользователь уже выбрал новое значение, его команда важнее проверки старого
        if self._pending_sets.pending:
            self._start_next()
        else:
            self._enqueue_read(generation)

    def _complete(self, success, message):
        failed_set = self._kind == "set" and not success
        generation = self._generation
        if self._kind in ("resume_off", "resume_on"):
            failed_kind = self._kind
            self._clear_process()
            self.operation_error.emit(
                generation,
                "Не удалось восстановить ночной свет после пробуждения: {}".format(message),
            )
            if failed_kind == "resume_off":
                # Возвращаем исходное включённое состояние даже после ошибки выключения
                self._run("resume_on", ["on"], generation)
            else:
                self._enqueue_read(generation)
            return
        self._clear_process()
        if not success and generation >= self._pending_sets.generation:
            self.operation_error.emit(generation, message)
        if failed_set:
            self._verification = None
            # Даже после ошибки записи возвращаем ползунок к настройке Windows
            if self._pending_read is None:
                self._pending_read = generation
            else:
                self._pending_read = max(self._pending_read, generation)
        self.command_finished.emit(generation)
        self._start_next()

    def _clear_process(self):
        self._timer.stop()
        if self._process:
            self._process.deleteLater()
        self._process = None
        self._kind = None

    def close(self):
        """Отменяет очередь и завершает дочерний процесс при выходе приложения"""
        self._closing = True
        self._timer.stop()
        self._pending_read = None
        self._pending_sets.pending = None
        self._verification = None
        self._wake_recovery = False
        self._recovery_generation = None
        process = self._process
        self._process = None
        self._kind = None
        if process is not None:
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(300)
            process.deleteLater()

    def finish_pending(self):
        """Заканчивает последний выбранный запрос, затем сообщает готовность к выходу"""
        if self._closing or self._finishing:
            return
        self._finishing = True
        # Без незавершённой записи ждать обычное чтение при выходе не требуется
        if (
            self._pending_sets.pending is None
            and self._verification is None
            and self._kind != "set"
        ):
            self.drained.emit()
        else:
            self._start_next()
