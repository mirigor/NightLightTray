"""Чтение и создание ярлыков Windows через COM без скриптов и зависимостей"""

import ctypes
import os
import uuid
from contextlib import contextmanager
from ctypes import wintypes


class _GUID(ctypes.Structure):
    """Двоичное представление идентификатора интерфейса COM"""

    _fields_ = [
        ("data1", ctypes.c_uint32),
        ("data2", ctypes.c_uint16),
        ("data3", ctypes.c_uint16),
        ("data4", ctypes.c_ubyte * 8),
    ]


def _guid(value):
    return _GUID.from_buffer_copy(uuid.UUID(value).bytes_le)


def _check(result):
    if result < 0:
        raise OSError(
            "Не удалось обработать ярлык Windows (HRESULT 0x{:08X}).".format(result & 0xFFFFFFFF)
        )


def _call(pointer, index, argument_types, *arguments, result_type=ctypes.c_long):
    """Вызывает метод интерфейса по его позиции в стандартной таблице COM"""
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    method = ctypes.WINFUNCTYPE(result_type, ctypes.c_void_p, *argument_types)(table[index])
    return method(pointer, *arguments)


@contextmanager
def _interfaces():
    """Освобождает обе ссылки COM и балансирует инициализацию текущего потока"""
    if os.name != "nt":
        raise OSError("Ярлыки автозапуска поддерживаются только в Windows.")
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    ole.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole.CoCreateInstance.restype = ctypes.c_long
    initialized = ole.CoInitializeEx(None, 2)
    # Qt уже мог выбрать другую модель COM: повторная инициализация тогда не нужна
    if initialized < 0 and initialized & 0xFFFFFFFF != 0x80010106:
        _check(initialized)
    link = ctypes.c_void_p()
    persist = ctypes.c_void_p()
    try:
        clsid = _guid("00021401-0000-0000-C000-000000000046")
        iid_link = _guid("000214F9-0000-0000-C000-000000000046")
        iid_persist = _guid("0000010B-0000-0000-C000-000000000046")
        _check(
            ole.CoCreateInstance(
                ctypes.byref(clsid), None, 1, ctypes.byref(iid_link), ctypes.byref(link)
            )
        )
        _check(
            _call(
                link,
                0,
                [ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)],
                ctypes.byref(iid_persist),
                ctypes.byref(persist),
            )
        )
        yield link, persist
    finally:
        for pointer in (persist, link):
            if pointer.value:
                _call(pointer, 2, [], result_type=wintypes.ULONG)
        if initialized >= 0:
            ole.CoUninitialize()


def read_shortcut(path):
    """Читает свойства ярлыка без запуска цели и поиска перемещённого файла"""
    with _interfaces() as (link, persist):
        _check(_call(persist, 5, [wintypes.LPCWSTR, wintypes.DWORD], str(path), 0))
        data = {}
        buffer = ctypes.create_unicode_buffer(32768)
        _check(
            _call(
                link,
                3,
                [wintypes.LPWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
                buffer,
                len(buffer),
                None,
                4,
            )
        )
        data["target"] = buffer.value
        for name, index in (("description", 6), ("working_directory", 8), ("arguments", 10)):
            _check(_call(link, index, [wintypes.LPWSTR, ctypes.c_int], buffer, len(buffer)))
            data[name] = buffer.value
        show = ctypes.c_int()
        _check(_call(link, 14, [ctypes.POINTER(ctypes.c_int)], ctypes.byref(show)))
        data["show_command"] = show.value
        icon_index = ctypes.c_int()
        _check(
            _call(
                link,
                16,
                [wintypes.LPWSTR, ctypes.c_int, ctypes.POINTER(ctypes.c_int)],
                buffer,
                len(buffer),
                ctypes.byref(icon_index),
            )
        )
        data["icon"] = buffer.value
        data["icon_index"] = icon_index.value
        return data


def write_shortcut(path, data):
    """Создаёт ярлык через IShellLinkW и сохраняет его через IPersistFile"""
    with _interfaces() as (link, persist):
        for name, index in (
            ("target", 20),
            ("description", 7),
            ("working_directory", 9),
            ("arguments", 11),
        ):
            _check(_call(link, index, [wintypes.LPCWSTR], data[name]))
        _check(_call(link, 15, [ctypes.c_int], data["show_command"]))
        _check(_call(link, 17, [wintypes.LPCWSTR, ctypes.c_int], data["icon"], data["icon_index"]))
        _check(_call(persist, 6, [wintypes.LPCWSTR, wintypes.BOOL], str(path), True))
