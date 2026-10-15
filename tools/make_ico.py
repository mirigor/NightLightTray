"""Создаёт ICO из простой растровой луны для иконки собранного EXE.

Запускается только при сборке. В самом приложении используется векторный moon.svg
"""

import binascii
import struct
import zlib
from pathlib import Path


def png_chunk(kind, data):
    """Возвращает один блок PNG"""
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)
    )


def make_png(size):
    """Рисует тёмный квадрат с жёлтым серпом без внешних библиотек"""
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            r, g, b, a = 27, 38, 59, 255
            dx, dy = x - size * 0.45, y - size * 0.50
            outer = dx * dx + dy * dy <= (size * 0.30) ** 2
            cut_dx = x - size * 0.56
            cut_dy = y - size * 0.42
            inner = cut_dx * cut_dx + cut_dy * cut_dy <= (size * 0.28) ** 2
            if outer and not inner:
                r, g, b = 246, 211, 101
            row.extend((r, g, b, a))
        rows.append(b"\0" + bytes(row))
    raw = b"".join(rows)
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(raw, 9))
        + png_chunk(b"IEND", b"")
    )


def main():
    """Записывает ICO с двумя вариантами размера"""
    images = [make_png(32), make_png(64)]
    offset = 6 + 16 * len(images)
    entries = []
    data = bytearray()
    for size, image in zip((32, 64), images):
        entries.append(struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(image), offset))
        data.extend(image)
        offset += len(image)
    result = struct.pack("<HHH", 0, 1, len(images)) + b"".join(entries) + data
    Path(__file__).resolve().parents[1].joinpath("resources", "moon.ico").write_bytes(result)


if __name__ == "__main__":
    main()
