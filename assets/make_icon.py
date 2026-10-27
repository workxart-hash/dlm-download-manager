"""Generate assets/dlm.ico (a download glyph) with pure Python.

No third-party or native imaging libraries: each icon size is rendered to an
RGBA raster and packed as a 32-bit BMP/DIB entry inside a classic .ico. Re-run
to regenerate.
"""

from __future__ import annotations

import struct
from pathlib import Path

BLUE = (37, 99, 235, 255)
WHITE = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)


def _inside_rrect(x, y, x0, y0, x1, y1, r):
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    # corner circles
    for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)):
        in_x = (cx == x0 + r and x < x0 + r) or (cx == x1 - r and x > x1 - r)
        in_y = (cy == y0 + r and y < y0 + r) or (cy == y1 - r and y > y1 - r)
        if in_x and in_y and (x - cx) ** 2 + (y - cy) ** 2 > r * r:
            return False
    return True


def _in_triangle(px, py, a, b, c):
    def sign(p, q, r):
        return (p[0] - r[0]) * (q[1] - r[1]) - (q[0] - r[0]) * (p[1] - r[1])
    d1, d2, d3 = sign((px, py), a, b), sign((px, py), b, c), sign((px, py), c, a)
    neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (neg and pos)


def render(S):
    k = S / 256.0
    def s(v):
        return v * k
    cx = S / 2.0
    shaft = (cx - s(18), s(58), cx + s(18), s(150))
    head = ((cx - s(48), s(138)), (cx + s(48), s(138)), (cx, s(198)))
    px = [[CLEAR] * S for _ in range(S)]
    for y in range(S):
        for x in range(S):
            xc, yc = x + 0.5, y + 0.5
            color = CLEAR
            if _inside_rrect(xc, yc, s(8), s(8), S - s(8), S - s(8), s(48)):
                color = BLUE
            if shaft[0] <= xc <= shaft[2] and shaft[1] <= yc <= shaft[3]:
                color = WHITE
            elif _in_triangle(xc, yc, *head):
                color = WHITE
            elif _inside_rrect(xc, yc, s(64), s(206), S - s(64), s(224), s(9)):
                color = WHITE
            px[y][x] = color
    return px


def dib_entry(px, S):
    # BITMAPINFOHEADER: height doubled for the (empty) AND mask
    header = struct.pack("<IiiHHIIiiII", 40, S, S * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    body = bytearray()
    for y in range(S - 1, -1, -1):          # bottom-up
        for x in range(S):
            r, g, b, a = px[y][x]
            body += bytes((b, g, r, a))      # BGRA
    mask_row = ((S + 31) // 32) * 4          # 1bpp AND mask, 32-bit aligned, all zero
    body += bytes(mask_row * S)
    return header + bytes(body)


def main():
    sizes = [16, 32, 48, 64, 128, 256]
    images = [(S, dib_entry(render(S), S)) for S in sizes]
    out = Path(__file__).with_name("dlm.ico")
    offset = 6 + 16 * len(images)
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = bytearray()
    blob = bytearray()
    for S, data in images:
        w = 0 if S == 256 else S
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(data), offset)
        blob += data
        offset += len(data)
    out.write_bytes(header + bytes(entries) + bytes(blob))
    print("wrote", out, f"({out.stat().st_size} bytes, {len(images)} sizes)")


if __name__ == "__main__":
    main()
