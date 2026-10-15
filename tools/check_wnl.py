"""Диагностика CLI и QProcess. По умолчанию только читает состояние Windows"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from nightlight import (
    NightLightClient,
    NightLightError,
    find_wnl,
    parse_strength,
    parse_temperature,
    process_error,
)


def run_command(command, arguments):
    """Запускает CLI без оболочки и консольного окна с ограничением времени"""
    result = subprocess.run(
        [command] + arguments,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode:
        raise NightLightError(process_error(result.returncode, result.stderr))
    return result.stdout


def check_client(client, expected=None, generation=1):
    """Проверяет настоящее чтение либо запись и проверочное чтение через QProcess"""
    loop = QEventLoop()
    values = []
    errors = []
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)

    def ready(_generation, value, _active):
        values.append(value)
        loop.quit()

    def failed(_generation, message):
        errors.append(message)
        if expected is None:
            loop.quit()

    client.status_ready.connect(ready)
    client.operation_error.connect(failed)
    timer.start(20000)
    if expected is None:
        client.read_strength(generation)
    else:
        client.set_strength(expected, generation)
    if not values and not (errors and expected is None):
        loop.exec()
    timer.stop()
    client.status_ready.disconnect(ready)
    client.operation_error.disconnect(failed)
    if errors:
        raise NightLightError("; ".join(errors))
    if not values:
        raise NightLightError("Не получен ответ QProcess.")
    if expected is not None and values[-1] != expected:
        raise NightLightError("Проверочное чтение отличается от выбранного значения.")
    return values[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-test",
        action="store_true",
        help="Проверить 56%% и 68%%, затем вернуть исходную температуру",
    )
    arguments = parser.parse_args()
    app = QCoreApplication(sys.argv)
    command = find_wnl()
    if not command:
        raise NightLightError("Не найден wnl.exe.")
    original = run_command(command, ["status"])
    strength = parse_strength(original)
    temperature = str(parse_temperature(original))
    client = NightLightClient(command)
    actual = check_client(client)
    if actual != strength:
        raise NightLightError("Состояние изменилось во время проверки чтения.")
    print("QProcess: текущее значение {}%.".format(actual))
    if arguments.write_test:
        try:
            for generation, value in enumerate((56, 68), start=2):
                actual = check_client(client, value, generation)
                print("Запись и проверочное чтение: {}%.".format(actual))
        finally:
            run_command(command, ["temp", temperature])
            restored = run_command(command, ["status"])
            restored_temperature = str(parse_temperature(restored))
            if restored_temperature != temperature:
                raise NightLightError("Не удалось вернуть исходную температуру Windows.")
            # Проверяем, что интенсивность не затронула включение и расписание
            for field in ("active", "schedule", "set hours", "sunset to sunrise"):
                pattern = r"^{}:\s*([^\r\n]*)".format(field)
                if re.findall(pattern, original, re.MULTILINE) != re.findall(
                    pattern, restored, re.MULTILINE
                ):
                    raise NightLightError("При проверке изменилось поле {}.".format(field))
            print(
                "Исходная температура {} K восстановлена; включение и расписание сохранены.".format(
                    temperature
                )
            )
    client.close()
    app.quit()


if __name__ == "__main__":
    try:
        main()
    except (NightLightError, OSError, subprocess.TimeoutExpired) as error:
        print("Ошибка: {}".format(error), file=sys.stderr)
        sys.exit(1)
