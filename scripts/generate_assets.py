"""Generate deterministic bitmap assets for the static Peach site."""

from __future__ import annotations

import math
from pathlib import Path
import struct
import zlib


WIDTH = 1400
HEIGHT = 900


def blend(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def put_px(buf: bytearray, x: int, y: int, color: tuple[int, int, int]) -> None:
    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
        idx = (y * WIDTH + x) * 3
        buf[idx : idx + 3] = bytes(color)


def rect(
    buf: bytearray,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
) -> None:
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(WIDTH, x1)
    y1 = min(HEIGHT, y1)
    row = bytes(color) * max(0, x1 - x0)
    for y in range(y0, y1):
        start = (y * WIDTH + x0) * 3
        buf[start : start + len(row)] = row


def rounded_rect(
    buf: bytearray,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    radius: int,
    color: tuple[int, int, int],
) -> None:
    for y in range(y0, y1):
        for x in range(x0, x1):
            dx = max(x0 + radius - x, 0, x - (x1 - radius - 1))
            dy = max(y0 + radius - y, 0, y - (y1 - radius - 1))
            if dx * dx + dy * dy <= radius * radius:
                put_px(buf, x, y, color)


def circle(buf: bytearray, cx: int, cy: int, r: int, color: tuple[int, int, int]) -> None:
    r2 = r * r
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= r2:
                put_px(buf, x, y, color)


def line(
    buf: bytearray,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
    width: int = 3,
) -> None:
    steps = max(abs(x1 - x0), abs(y1 - y0), 1)
    for i in range(steps + 1):
        t = i / steps
        x = int(x0 + (x1 - x0) * t)
        y = int(y0 + (y1 - y0) * t)
        circle(buf, x, y, max(1, width // 2), color)


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_png(path: Path, buf: bytearray) -> None:
    raw = bytearray()
    stride = WIDTH * 3
    for y in range(HEIGHT):
        raw.append(0)
        raw.extend(buf[y * stride : (y + 1) * stride])

    data = b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            png_chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)),
            png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
            png_chunk(b"IEND", b""),
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def main() -> None:
    buf = bytearray(WIDTH * HEIGHT * 3)

    top = (255, 242, 221)
    mid = (255, 205, 160)
    low = (248, 137, 94)
    dusk = (74, 48, 73)
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        if t < 0.52:
            color = blend(top, mid, t / 0.52)
        elif t < 0.78:
            color = blend(mid, low, (t - 0.52) / 0.26)
        else:
            color = blend(low, dusk, (t - 0.78) / 0.22)
        rect(buf, 0, y, WIDTH, y + 1, color)

    for r, alpha_color in [(170, (255, 227, 166)), (126, (255, 191, 111)), (92, (255, 247, 199))]:
        circle(buf, 1035, 276, r, alpha_color)

    for i in range(9):
        y = 320 + i * 24
        color = blend((255, 248, 231), (238, 122, 89), i / 8)
        line(buf, 0, y, WIDTH, y + int(math.sin(i) * 18), color, 2)

    rect(buf, 0, 585, WIDTH, 900, (49, 39, 48))
    rect(buf, 0, 620, WIDTH, 900, (38, 34, 43))
    for x in range(0, WIDTH, 58):
        line(buf, x, 620, x + 210, 900, (58, 49, 56), 1)

    rounded_rect(buf, 124, 186, 902, 658, 28, (42, 33, 43))
    rounded_rect(buf, 142, 208, 884, 640, 18, (28, 30, 42))
    rect(buf, 142, 208, 884, 260, (64, 48, 54))
    circle(buf, 174, 234, 9, (255, 132, 101))
    circle(buf, 205, 234, 9, (255, 194, 105))
    circle(buf, 236, 234, 9, (123, 205, 145))

    for y, color in [(306, (255, 205, 143)), (358, (122, 205, 191)), (410, (247, 148, 114)), (462, (151, 132, 214))]:
        rect(buf, 184, y, 392, y + 14, color)
        rect(buf, 426, y, 812, y + 14, blend(color, (255, 242, 221), 0.45))

    chart = [(184, 560), (258, 528), (332, 546), (407, 492), (482, 506), (556, 444), (631, 468), (706, 386), (792, 416)]
    for a, b in zip(chart, chart[1:]):
        line(buf, a[0], a[1], b[0], b[1], (255, 183, 99), 7)
    for x, y in chart:
        circle(buf, x, y, 10, (255, 238, 188))

    rounded_rect(buf, 905, 424, 1238, 694, 22, (253, 230, 202))
    rounded_rect(buf, 930, 448, 1213, 528, 12, (79, 57, 72))
    for i, h in enumerate([48, 75, 42, 102, 86]):
        x = 958 + i * 47
        rect(buf, x, 644 - h, x + 24, 644, (238, 124, 92))
    line(buf, 930, 562, 1213, 562, (224, 180, 150), 2)
    line(buf, 930, 644, 1213, 644, (224, 180, 150), 2)

    write_png(Path("public/assets/sunset-console.png"), buf)


if __name__ == "__main__":
    main()
