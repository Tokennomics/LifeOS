"""Generate LifeOS app icons (pure python, no Pillow): navy field, amber node + orbit ring."""

import math
import pathlib
import struct
import zlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "surfaces" / "app" / "www" / "icons"

NAVY = (15, 20, 32)
NAVY_LIGHT = (24, 31, 48)
AMBER = (232, 161, 60)


def pixel(x, y, size):
    c = size / 2
    d = math.hypot(x - c, y - c) / size
    t = y / size
    bg = tuple(round(NAVY[i] + (NAVY_LIGHT[i] - NAVY[i]) * (1 - t)) for i in range(3))
    if d < 0.085:
        return AMBER
    if 0.24 < d < 0.30:
        return AMBER if (0.25 < d < 0.29) else tuple((a + b) // 2 for a, b in zip(AMBER, bg))
    return bg


def chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def write_png(path: pathlib.Path, size: int) -> None:
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter: none
        for x in range(size):
            raw.extend(pixel(x, y, size))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))
    path.write_bytes(png)
    print(f"{path.name}: {size}x{size}, {len(png)} bytes")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    write_png(OUT / "icon-192.png", 192)
    write_png(OUT / "icon-512.png", 512)
    write_png(OUT / "apple-touch-icon.png", 180)
