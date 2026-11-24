#!/usr/bin/env python3
"""THE MONDAY GLOBE -- Monday 23 November 2026 in one image.

A newspaper front page drawn from scratch with a tiny pixel engine:
a framebuffer, a hand-made 5x7 bitmap font, flat-vector scenes, a dotted
world map, and a hand-rolled PNG encoder. Standard library only.
Deterministic: two runs write byte-identical PNGs.

Layout (1024x1024): navy masthead with the date, a UTC timeline strip,
a region strip with counts computed from the story data, a six-numbers
strip, 3 lead stories, 10 more illustrated stories, a dotted world map
with numbered pins, 33 numbered briefs, a red DATE CHECK box and a
sources footer. 46 stories in all, every one first reported on Monday
23 November 2026 (UTC).
"""

import hashlib
import os
import struct
import sys
import zlib

W = 1024
H = 1024

# ---------------------------------------------------------------- palette
PAPER = (247, 242, 231)
INK = (20, 20, 20)
NAVY = (14, 38, 66)
NAVY2 = (22, 56, 92)
SLATE = (38, 48, 60)
RED = (176, 30, 36)
GOLD = (201, 162, 39)
GOLD_L = (232, 196, 90)
WHITE = (255, 255, 255)
GREY = (110, 110, 105)
LGREY = (222, 216, 203)
GREEN = (28, 120, 70)
TEAL = (18, 110, 120)
ORANGE = (214, 110, 30)
SKY = (140, 190, 220)
SEA = (52, 110, 150)
SAND = (226, 205, 160)

REGION_COLORS = {
    "N AMERICA": (176, 30, 36),
    "EUROPE": (22, 56, 140),
    "ASIA": (28, 120, 70),
    "AFRICA": (214, 130, 20),
    "MID EAST": (120, 60, 140),
    "OCEANIA": (18, 110, 120),
    "LATIN AM": (200, 60, 90),
    "GLOBAL": (90, 90, 95),
}

# ---------------------------------------------------------------- canvas
buf = bytearray(W * H * 3)


def px(x, y, c):
    if 0 <= x < W and 0 <= y < H:
        i = (y * W + x) * 3
        buf[i] = c[0]
        buf[i + 1] = c[1]
        buf[i + 2] = c[2]


def rect(x, y, w, h, c):
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(W, x + w)
    y1 = min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    row = bytes(c) * (x1 - x0)
    for yy in range(y0, y1):
        i = (yy * W + x0) * 3
        buf[i:i + (x1 - x0) * 3] = row


def recto(x, y, w, h, c, t=1):
    rect(x, y, w, t, c)
    rect(x, y + h - t, w, t, c)
    rect(x, y, t, h, c)
    rect(x + w - t, y, t, h, c)


def hline(x, y, w, c):
    rect(x, y, w, 1, c)


def vline(x, y, h, c):
    rect(x, y, 1, h, c)


def line(x0, y0, x1, y1, c):
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        px(x0, y0, c)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def circle(cx, cy, r, c, fill=True):
    if fill:
        for dy in range(-r, r + 1):
            dx = int((r * r - dy * dy) ** 0.5)
            rect(cx - dx, cy + dy, dx * 2 + 1, 1, c)
    else:
        steps = max(8, r * 6)
        for k in range(steps):
            import math as _m
            a = 2 * _m.pi * k / steps
            px(int(cx + r * _m.cos(a)), int(cy + r * _m.sin(a)), c)


def tri(x0, y0, x1, y1, x2, y2, c):
    pts = sorted([(x0, y0), (x1, y1), (x2, y2)], key=lambda p: p[1])
    (ax, ay), (bx, by), (cx, cy) = pts
    if ay == cy:
        return
    def edge(xa, ya, xb, yb, y):
        if yb == ya:
            return xa
        return xa + (xb - xa) * (y - ya) / (yb - ya)
    for y in range(ay, cy + 1):
        if y < by:
            xa = edge(ax, ay, bx, by, y)
            xb = edge(ax, ay, cx, cy, y)
        else:
            xa = edge(bx, by, cx, cy, y)
            xb = edge(ax, ay, cx, cy, y)
        x0 = int(min(xa, xb))
        x1 = int(max(xa, xb))
        rect(x0, y, x1 - x0 + 1, 1, c)


def vgrad(x, y, w, h, c0, c1):
    for k in range(h):
        t = k / max(1, h - 1)
        c = tuple(int(c0[i] + (c1[i] - c0[i]) * t) for i in range(3))
        rect(x, y + k, w, 1, c)
        # halftone grain so the gradient reads as print, not plastic
        dk = shade(c, 0.90)
        for xx in range(x, x + w):
            n = (xx * 374761393 + (y + k) * 668265263) & 0xFFFFFFFF
            if (n % 1000) < 220:
                px(xx, y + k, dk)


def shade(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def speckle(x, y, w, h, c, seed, frac=0.12):
    """Deterministic grain: dots where a hash of the position is small."""
    s = seed & 0xFFFFFFFF
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            n = (xx * 374761393 + yy * 668265263 + s * 974634211) & 0xFFFFFFFF
            n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
            if (n % 1000) < frac * 1000:
                px(xx, yy, c)


# ---------------------------------------------------------------- 5x7 font
# Each glyph: 7 rows of 5 bits, '1' = ink. Uppercase + digits + punctuation.
FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00110", "01000", "10000", "11111"),
    "3": ("11111", "00010", "00100", "00010", "00001", "10001", "01110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    ",": ("00000", "00000", "00000", "00000", "01100", "00100", "01000"),
    ":": ("00000", "01100", "01100", "00000", "01100", "01100", "00000"),
    ";": ("00000", "01100", "01100", "00000", "01100", "00100", "01000"),
    "!": ("00100", "00100", "00100", "00100", "00100", "00000", "00100"),
    "?": ("01110", "10001", "00001", "00110", "00100", "00000", "00100"),
    "'": ("00100", "00100", "01000", "00000", "00000", "00000", "00000"),
    '"': ("01010", "01010", "00000", "00000", "00000", "00000", "00000"),
    "-": ("00000", "00000", "00000", "01110", "00000", "00000", "00000"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"),
    ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
    "%": ("11001", "11010", "00010", "00100", "01000", "01011", "10011"),
    "+": ("00000", "00100", "00100", "01110", "00100", "00100", "00000"),
    "=": ("00000", "00000", "11111", "00000", "11111", "00000", "00000"),
    "$": ("00100", "01111", "10100", "01110", "00101", "11110", "00100"),
    "&": ("01100", "10010", "10100", "01000", "10101", "10010", "01101"),
    "*": ("00000", "10101", "01110", "11111", "01110", "10101", "00000"),
    "#": ("01010", "01010", "11111", "01010", "11111", "01010", "01010"),
    "@": ("01110", "10001", "10111", "10101", "10110", "10000", "01110"),
    "_": ("00000", "00000", "00000", "00000", "00000", "00000", "11111"),
    "[": ("01110", "01000", "01000", "01000", "01000", "01000", "01110"),
    "]": ("01110", "00010", "00010", "00010", "00010", "00010", "01110"),
    "<": ("00010", "00100", "01000", "10000", "01000", "00100", "00010"),
    ">": ("01000", "00100", "00010", "00001", "00010", "00100", "01000"),
    "^": ("00100", "01010", "10001", "00000", "00000", "00000", "00000"),
    "~": ("00000", "00000", "01001", "10110", "00000", "00000", "00000"),
    "`": ("01000", "00100", "00000", "00000", "00000", "00000", "00000"),
    "|": ("00100", "00100", "00100", "00100", "00100", "00100", "00100"),
    "\\": ("10000", "01000", "01000", "00100", "00010", "00010", "00001"),
    "{": ("00110", "01000", "01000", "11110", "01000", "01000", "00110"),
    "}": ("01100", "00010", "00010", "01111", "00010", "00010", "01100"),
}

CHAR_W = 5
CHAR_H = 7


# ---------------------------------------------------------------- text
def text_width(s, scale, spacing=1):
    return len(s) * (CHAR_W * scale + spacing) - spacing


def draw_text(s, x, y, scale, c, spacing=1, align="l"):
    """Draw uppercase text; returns the pixel width drawn."""
    s = s.upper()
    w = text_width(s, scale, spacing)
    if align == "c":
        x -= w // 2
    elif align == "r":
        x -= w
    for ch in s:
        g = FONT.get(ch, FONT["?"])
        for r in range(CHAR_H):
            row = g[r]
            for col in range(CHAR_W):
                if row[col] == "1":
                    rect(x + col * scale, y + r * scale, scale, scale, c)
        x += CHAR_W * scale + spacing
    return w


def wrap_words(s, maxw, scale, spacing=1):
    """Greedy word wrap; returns a list of lines that fit maxw."""
    words = s.upper().split(" ")
    lines = []
    cur = ""
    for wd in words:
        trial = wd if not cur else cur + " " + wd
        if text_width(trial, scale, spacing) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def text_block(s, x, y, w, scale, c, spacing=1, lh=None, max_lines=None):
    """Wrapped paragraph; returns the y just below the last line."""
    if lh is None:
        lh = CHAR_H * scale + 3
    lines = wrap_words(s, w, scale, spacing)
    if max_lines is not None:
        lines = lines[:max_lines]
    for ln in lines:
        draw_text(ln, x, y, scale, c, spacing)
        y += lh
    return y


def fit_line(s, maxw, scale, spacing=0):
    """Shorten a one-liner with an ellipsis until it fits maxw."""
    s = s.upper()
    while s and text_width(s, scale, spacing) > maxw:
        s = s[:-1].rstrip()
    return s


def badge(x, y, w, h, c, label, tcol=WHITE):
    rect(x, y, w, h, c)
    draw_text(label, x + w // 2, y + (h - CHAR_H) // 2, 1, tcol, 1, "c")


# ---------------------------------------------------------------- scenes
# Each scene draws inside (x, y, w, h). All use fixed seeds, so the
# picture is identical on every run.


def scene_nvda(x, y, w, h):
    """Nvidia: a chip on a board under a rocketing green chart."""
    vgrad(x, y, w, h, (16, 24, 40), (30, 60, 50))
    # circuit traces
    for k in range(6):
        yy = y + 8 + k * (h // 7)
        hline(x + 4, yy, w - 8, shade(GREEN, 0.7))
        vline(x + 10 + k * 22, yy, 6, shade(GREEN, 0.7))
    # chip
    cx, cy = x + w // 2 - 34, y + h - 62
    rect(cx - 6, cy - 6, 80, 64, (10, 18, 12))
    rect(cx, cy, 68, 52, (24, 90, 52))
    rect(cx + 6, cy + 6, 56, 40, (18, 66, 38))
    draw_text("NVDA", cx + 34, cy + 16, 2, (190, 255, 200), 1, "c")
    for k in range(6):
        rect(cx - 6 + k * 12, cy - 12, 4, 6, GOLD_L)
        rect(cx - 6 + k * 12, cy + 52, 4, 6, GOLD_L)
    # rocketing chart
    pts = [(x + 8, y + h - 70), (x + 30, y + h - 84), (x + 52, y + h - 78),
           (x + 74, y + h - 96), (x + 96, y + h - 88), (x + 118, y + h - 110),
           (x + 140, y + h - 96), (x + 162, y + h - 122), (x + 186, y + h - 100),
           (x + 208, y + h - 128), (x + 232, y + h - 108), (x + 256, y + h - 138),
           (x + 280, y + h - 118), (x + w - 10, y + 12)]
    for a, b in zip(pts, pts[1:]):
        line(a[0], a[1], b[0], b[1], (110, 255, 140))
        line(a[0], a[1] + 1, b[0], b[1] + 1, (110, 255, 140))
    tri(x + w - 22, y + 8, x + w - 6, y + 12, x + w - 22, y + 18, (110, 255, 140))
    draw_text("+31.5%", x + w - 8, y + 26, 2, (140, 255, 160), 1, "r")
    # server rack, bottom right
    rect(x + w - 70, y + h - 40, 56, 34, (12, 20, 26))
    for k in range(4):
        rect(x + w - 64, y + h - 36 + k * 8, 44, 4, (40, 140, 80))
        circle(x + w - 60, y + h - 34 + k * 8, 1, (140, 255, 160))
    speckle(x, y, w, h, (255, 255, 255), 11, 0.02)


def scene_benghazi(x, y, w, h):
    """Benghazi: a warship at sea, struck by sea drones, smoke rising."""
    vgrad(x, y, w, h, (250, 190, 120), (120, 170, 210))
    circle(x + w - 46, y + 26, 18, (255, 220, 130))
    # sea
    rect(x, y + h - 52, w, 52, SEA)
    for k in range(5):
        yy = y + h - 44 + k * 9
        hline(x + 6 + (k * 37) % 60, yy, 70, (140, 200, 235))
    # coast
    rect(x, y + h - 52, 70, 10, SAND)
    rect(x + 8, y + h - 62, 14, 10, (220, 200, 170))
    rect(x + 26, y + h - 66, 18, 14, (210, 190, 160))
    # warship
    sx = x + 96
    sy = y + h - 66
    rect(sx, sy, 120, 12, (70, 76, 84))
    tri(sx + 118, sy, sx + 150, sy, sx + 118, sy + 12, (70, 76, 84))
    rect(sx + 40, sy - 16, 44, 16, (90, 96, 104))
    rect(sx + 52, sy - 30, 6, 14, (90, 96, 104))
    rect(sx + 66, sy - 26, 18, 6, (90, 96, 104))
    # explosion (kept inside the scene: ey stays below y+20)
    ex, ey = sx + 60, sy - 20
    for dx, dy in [(0, -13), (10, -8), (13, 2), (8, 10), (0, 13),
                   (-10, 8), (-13, 0), (-8, -10)]:
        tri(ex, ey, ex + dx, ey + dy, ex + dx // 2 + 3, ey + dy // 2 + 3,
            (255, 160, 40))
    circle(ex, ey, 8, (255, 220, 90))
    # smoke, capped at the scene top
    circle(ex - 18, ey - 12, 9, (90, 90, 90))
    circle(ex - 4, ey - 18, 11, (120, 120, 120))
    circle(ex + 12, ey - 12, 8, (90, 90, 90))
    # sea drones
    for dx, dy in [(30, 18), (150, 30), (230, 14)]:
        rect(x + dx, y + dy, 16, 5, (40, 40, 44))
        circle(x + dx + 8, y + dy - 3, 3, (40, 40, 44))
        line(x + dx + 8, y + dy + 5, sx + 60, sy - 20, (200, 60, 40))
    # birds and extra waves
    for bx, by in [(60, 44), (80, 52), (250, 40)]:
        line(bx - 6, by, bx, by - 4, (40, 40, 44))
        line(bx, by - 4, bx + 6, by, (40, 40, 44))
    for k in range(3):
        yy = y + h - 30 + k * 8
        hline(x + 90 + (k * 61) % 120, yy, 60, (140, 200, 235))
    speckle(x, y, w, h, (255, 255, 255), 22, 0.02)


def scene_dymer(x, y, w, h):
    """Dymer: an apartment block hit at night, rescuers below."""
    vgrad(x, y, w, h, (24, 28, 48), (60, 50, 70))
    for k in range(14):
        px(x + (k * 53) % w, y + (k * 29) % (h // 2), (255, 255, 220))
    # skyline
    for bx, bw, bh in [(0, 46, 60), (52, 60, 88), (118, 44, 66), (168, 58, 96),
                       (232, 48, 70), (286, 40, 54)]:
        rect(x + bx, y + h - bh, bw, bh, (30, 34, 46))
        for wy in range(y + h - bh + 8, y + h - 8, 14):
            for wx in range(x + bx + 6, x + bx + bw - 6, 12):
                if (wx * 7 + wy * 13) % 5:
                    rect(wx, wy, 5, 7, (255, 210, 120))
    # struck block with a hole and fire
    bx = x + 52
    rect(bx, y + h - 88, 60, 88, (48, 40, 44))
    rect(bx + 18, y + h - 66, 24, 20, (10, 8, 8))
    tri(bx + 30, y + h - 66, bx + 18, y + h - 46, bx + 42, y + h - 46,
        (255, 140, 30))
    tri(bx + 30, y + h - 80, bx + 22, y + h - 62, bx + 38, y + h - 62,
        (255, 200, 60))
    circle(bx + 30, y + h - 92, 10, (90, 88, 88))
    circle(bx + 44, y + h - 100, 11, (120, 118, 118))
    # rescuers and ladder
    line(x + 130, y + h - 6, x + 96, y + h - 78, (220, 180, 60))
    line(x + 138, y + h - 6, x + 104, y + h - 78, (220, 180, 60))
    for k in range(5):
        yy = y + h - 18 - k * 13
        line(x + 128 - k * 7, yy, x + 136 - k * 7, yy, (220, 180, 60))
    for dx in (150, 170, 210, 235):
        rect(x + dx, y + h - 22, 8, 22, (200, 60, 40))
        circle(x + dx + 4, y + h - 28, 5, (240, 200, 160))
    # ambulance, bottom right, and smoke wisps
    rect(x + w - 64, y + h - 26, 52, 20, WHITE)
    rect(x + w - 64, y + h - 26, 52, 8, RED)
    circle(x + w - 52, y + h - 6, 5, (30, 30, 30))
    circle(x + w - 24, y + h - 6, 5, (30, 30, 30))
    circle(x + 220, y + 22, 7, (150, 148, 148))
    circle(x + 238, y + 16, 9, (170, 168, 168))
    circle(x + 258, y + 24, 6, (150, 148, 148))
    speckle(x, y, w, h, (255, 255, 255), 33, 0.02)


def scene_cop31(x, y, w, h):
    """After COP31: an empty hall, a Pacific palm, and a NO DEAL banner."""
    vgrad(x, y, w, h, (250, 220, 170), (200, 160, 120))
    # conference hall
    rect(x, y + 10, w, h - 10, (120, 90, 60))
    rect(x + 10, y + 20, w - 20, h - 40, (200, 170, 120))
    # empty chairs (bottom-anchored, inside the scene)
    for k in range(5):
        cx = x + 22 + k * 56
        rect(cx, y + h - 34, 34, 18, (90, 60, 40))
        rect(cx + 4, y + h - 50, 26, 16, (110, 75, 45))
    # podium
    rect(x + w // 2 - 30, y + h - 58, 60, 24, (70, 50, 30))
    # palm tree, right: trunk + fronds capped inside the scene
    px0, py0 = x + w - 52, y + h - 30
    ph = min(34, h - 42)
    line(px0, py0, px0 + 6, py0 - ph, (120, 80, 40))
    for dx, dy in [(-20, -10), (-10, -16), (2, -18), (14, -14), (22, -6),
                   (-16, -2), (12, -4)]:
        line(px0 + 6, py0 - ph, px0 + 6 + dx, py0 - ph - dy, GREEN)
    circle(px0 + 2, py0 - ph, 5, (110, 80, 40))
    circle(px0 + 12, py0 - ph + 2, 5, (110, 80, 40))
    # rising sea
    rect(x, y + h - 18, w, 18, (40, 110, 160))
    hline(x, y + h - 24, w, (90, 170, 220))
    # NO DEAL banner
    rect(x + 14, y + 16, 150, 26, RED)
    draw_text("NO DEAL", x + 89, y + 23, 2, WHITE, 1, "c")
    # floor line
    hline(x + 10, y + h - 14, w - 20, (90, 65, 40))
    speckle(x, y, w, h, (255, 255, 255), 44, 0.02)


def scene_tanker(x, y, w, h):
    """Strait of Hormuz: a tanker convoy under a blockade warning."""
    vgrad(x, y, w, h, (250, 200, 130), (150, 110, 70))
    circle(x + 40, y + 28, 20, (255, 230, 150))
    rect(x, y + h - 56, w, 56, (30, 80, 120))
    for k in range(4):
        yy = y + h - 46 + k * 11
        hline(x + (k * 53) % 80, yy, 90, (120, 180, 220))
    # tanker convoy
    for k, tx in enumerate((16, 96, 176)):
        hull = (150, 40, 36) if k != 1 else (40, 40, 44)
        rect(x + tx, y + h - 44, 66, 20, hull)
        rect(x + tx + 8, y + h - 58, 30, 14, (230, 230, 225))
        rect(x + tx + 44, y + h - 52, 8, 8, (230, 230, 225))
        rect(x + tx + 52, y + h - 66, 4, 14, (200, 200, 195))
    # blockade warship, right
    sx = x + w - 78
    rect(sx, y + h - 40, 64, 14, (70, 76, 84))
    rect(sx + 14, y + h - 56, 26, 16, (90, 96, 104))
    rect(sx + 22, y + h - 68, 4, 12, (90, 96, 104))
    # warning triangle
    tx, ty = x + w - 66, y + 12
    tri(tx, ty + 34, tx + 18, ty, tx + 36, ty + 34, (255, 200, 30))
    rect(tx + 16, ty + 12, 4, 12, (20, 20, 20))
    rect(tx + 16, ty + 27, 4, 4, (20, 20, 20))
    draw_text("14 TANKERS", x + w - 8, y + 52, 1, (60, 30, 10), 1, "r")
    # birds and more waves
    for bx, by in [(70, 10), (92, 16), (120, 8)]:
        line(bx - 5, by, bx, by - 3, (60, 40, 20))
        line(bx, by - 3, bx + 5, by, (60, 40, 20))
    for k in range(3):
        yy = y + h - 26 + k * 8
        hline(x + 120 + (k * 47) % 90, yy, 54, (120, 180, 220))
    speckle(x, y, w, h, (255, 255, 255), 55, 0.02)


def scene_nepal(x, y, w, h):
    """Delhi: two leaders shake hands before mountains and India Gate."""
    vgrad(x, y, w, h, (170, 205, 235), (250, 225, 180))
    # Himalayas (base at y+34, inside even a short scene)
    tri(x, y + 34, x + 60, y + 4, x + 120, y + 34, (240, 244, 250))
    tri(x + 80, y + 34, x + 150, y + 2, x + 220, y + 34, (225, 232, 240))
    tri(x + 180, y + 34, x + 250, y + 6, x + w, y + 34, (240, 244, 250))
    rect(x, y + 34, w, h - 34, (190, 220, 150))
    # India Gate arch
    ax = x + w // 2 - 26
    rect(ax, y + 40, 52, h - 48, (190, 140, 90))
    rect(ax + 14, y + 52, 24, h - 60, PAPER)
    rect(ax - 6, y + 36, 64, 6, (170, 120, 70))
    # flags (poles end above the scene bottom)
    for fx, cols in ((x + 22, [(255, 150, 50), (255, 255, 255), (20, 130, 70)]),
                     (x + w - 52, [(220, 30, 40), (255, 255, 255), (20, 60, 140)])):
        vline(fx, y + 28, h - 36, (90, 70, 50))
        for k, c in enumerate(cols):
            rect(fx + 1, y + 28 + k * 9, 26, 9, c)
        circle(fx + 14, y + 46, 4, NAVY)
    # two figures shaking hands
    for dx, c in ((-14, (40, 60, 110)), (10, (140, 40, 50))):
        fx = x + w // 2 + dx
        circle(fx, y + h - 34, 7, (240, 200, 160))
        rect(fx - 6, y + h - 26, 12, 26, c)
    line(x + w // 2 - 6, y + h - 20, x + w // 2 + 4, y + h - 20, (240, 200, 160))
    # birds over the field and grass tufts
    for bx, by in [(30, 44), (250, 42), (210, 48)]:
        line(bx - 5, by, bx, by - 3, (60, 60, 40))
        line(bx, by - 3, bx + 5, by, (60, 60, 40))
    for gx in (14, 60, 120, 200, 280):
        vline(x + gx, y + h - 8, 6, (120, 150, 80))
        line(x + gx - 3, y + h - 8, x + gx, y + h - 14, (120, 150, 80))
        line(x + gx + 3, y + h - 8, x + gx, y + h - 14, (120, 150, 80))
    speckle(x, y, w, h, (255, 255, 255), 66, 0.02)


def scene_wellington(x, y, w, h):
    """Wellington Test: a batsman holds out for the draw, scoreboard up."""
    vgrad(x, y, w, h, (150, 200, 235), (210, 225, 190))
    rect(x, y + h - 40, w, 40, (110, 170, 90))
    rect(x + 40, y + h - 40, w - 80, 40, (200, 180, 130))
    # pitch strip
    rect(x + w // 2 - 26, y + h - 40, 52, 40, (215, 195, 150))
    # stumps
    for sx in (x + w // 2 - 16, x + w // 2 - 11, x + w // 2 - 6):
        vline(sx, y + h - 52, 12, (250, 220, 130))
    # batsman (right of the scoreboard)
    bx = x + w // 2 + 52
    circle(bx, y + h - 62, 8, (240, 200, 160))
    rect(bx - 8, y + h - 54, 16, 28, (30, 60, 120))
    rect(bx - 7, y + h - 26, 6, 26, (240, 240, 235))
    rect(bx + 2, y + h - 26, 6, 26, (240, 240, 235))
    line(bx - 6, y + h - 44, bx - 26, y + h - 18, (150, 110, 60))
    # ball
    circle(bx - 34, y + h - 14, 4, RED)
    # scoreboard, top left (clear of the batsman)
    rect(x + 10, y + 10, 120, 40, (20, 30, 40))
    recto(x + 10, y + 10, 120, 40, GOLD, 2)
    draw_text("NZ 239/5", x + 70, y + 16, 2, WHITE, 1, "c")
    draw_text("DRAW", x + 70, y + 34, 1, GOLD_L, 1, "c")
    # crowd dots (below the scoreboard)
    for k in range(24):
        cx = x + 12 + (k * 37) % (w - 24)
        cy = y + 56 + (k * 17) % 18
        px(cx, cy, (200, 60, 60) if k % 3 == 0 else (240, 240, 240))
        px(cx + 1, cy, (200, 60, 60) if k % 3 == 0 else (240, 240, 240))
    # boundary rope, in the two outfield segments (clear of the pitch)
    hline(x + 8, y + h - 24, 50, (250, 250, 240))
    hline(x + w - 58, y + h - 24, 50, (250, 250, 240))
    speckle(x, y, w, h, (255, 255, 255), 77, 0.02)


def scene_sudan(x, y, w, h):
    """South Sudan: savanna, acacia, huts, and a red-cross tent."""
    vgrad(x, y, w, h, (250, 200, 130), (220, 160, 90))
    circle(x + w - 44, y + 26, 18, (255, 215, 120))
    rect(x, y + h - 44, w, 44, (190, 150, 80))
    # acacia, right of the "24 DEAD" label
    ax = x + 78
    line(ax, y + h - 44, ax + 4, y + h - 62, (110, 75, 40))
    for dx in (-22, -8, 6, 20):
        circle(ax + 4 + dx, y + h - 64, 10, (90, 130, 60))
    # huts
    for hx in (110, 170, 230):
        rect(x + hx, y + h - 62, 34, 18, (170, 120, 70))
        tri(x + hx - 4, y + h - 62, x + hx + 17, y + h - 72, x + hx + 38,
            y + h - 62, (130, 85, 45))
        rect(x + hx + 13, y + h - 54, 8, 10, (60, 40, 25))
    # medical tent with cross
    tx = x + w - 92
    rect(tx, y + h - 66, 60, 22, WHITE)
    tri(tx - 6, y + h - 66, tx + 30, y + h - 74, tx + 66, y + h - 66, WHITE)
    rect(tx + 26, y + h - 62, 8, 14, RED)
    rect(tx + 21, y + h - 59, 18, 5, RED)
    draw_text("24", x + 14, y + 12, 3, (140, 20, 20), 1, "l")
    draw_text("DEAD", x + 14, y + 40, 1, (140, 20, 20), 1, "l")
    # birds and grass tufts
    for bx, by in [(120, 12), (160, 18), (200, 10)]:
        line(bx - 5, by, bx, by - 3, (60, 40, 20))
        line(bx, by - 3, bx + 5, by, (60, 40, 20))
    for gx in (100, 150, 200, 270):
        vline(x + gx, y + h - 8, 6, (140, 110, 50))
        line(x + gx - 3, y + h - 8, x + gx, y + h - 13, (140, 110, 50))
    speckle(x, y, w, h, (255, 255, 255), 88, 0.02)


def scene_kenya_drc(x, y, w, h):
    """Kenya-DRC: two flags, a handshake, doves over two skylines."""
    vgrad(x, y, w, h, (160, 200, 230), (235, 225, 190))
    # skylines
    for bx, bw, bh in [(0, 40, 44), (44, 34, 60), (82, 44, 38)]:
        rect(x + bx, y + h - bh, bw, bh, (70, 80, 95))
    for bx, bw, bh in [(w - 84, 40, 52), (w - 44, 44, 34)]:
        rect(x + bx, y + h - bh, bw, bh, (80, 70, 85))
    # flags (poles end above the scene bottom)
    for fx, stripes in ((x + 96, [(20, 20, 20), (200, 30, 30), (20, 120, 60)]),
                        (x + 190, [(0, 90, 170), (240, 200, 30), (200, 30, 30)])):
        vline(fx, y + 20, h - 28, (90, 70, 50))
        for k, c in enumerate(stripes):
            rect(fx + 1, y + 20 + k * 9, 30, 9, c)
    # doves
    for dx, dy in [(60, 20), (150, 12), (240, 24)]:
        circle(x + dx, y + dy, 5, WHITE)
        line(x + dx - 12, y + dy - 4, x + dx - 2, y + dy, WHITE)
        line(x + dx + 2, y + dy, x + dx + 12, y + dy - 4, WHITE)
    # sun and skyline windows
    circle(x + 28, y + 16, 10, (255, 220, 130))
    for wx, wy in [(10, 14), (24, 8), (60, 20), (96, 10), (110, 16),
                   (w - 70, 12), (w - 30, 8)]:
        rect(x + wx, y + h - 34 + (wy % 12), 4, 5, (255, 210, 120))
    # handshake figures
    for dx, c in ((-16, (20, 90, 60)), (12, (0, 70, 150))):
        fx = x + w // 2 + dx
        circle(fx, y + h - 36, 8, (240, 200, 160))
        rect(fx - 7, y + h - 28, 14, 28, c)
    line(x + w // 2 - 8, y + h - 22, x + w // 2 + 8, y + h - 22,
         (240, 200, 160))
    speckle(x, y, w, h, (255, 255, 255), 99, 0.02)


def scene_chapo(x, y, w, h):
    """Sinaloa: hills, a helicopter, armoured trucks, a badge."""
    vgrad(x, y, w, h, (250, 210, 140), (200, 140, 80))
    # hills (apexes kept inside the scene)
    tri(x, y + h - 30, x + 90, y + h - 56, x + 180, y + h - 30, (150, 110, 60))
    tri(x + 120, y + h - 30, x + 220, y + h - 62, x + w, y + h - 30,
        (130, 95, 55))
    rect(x, y + h - 30, w, 30, (120, 95, 55))
    # helicopter (right of the trucks)
    hx, hy = x + w - 70, y + 26
    rect(hx, hy, 34, 12, (60, 60, 64))
    rect(hx + 30, hy + 3, 26, 4, (60, 60, 64))
    tri(hx + 34, hy, hx + 44, hy - 6, hx + 44, hy + 12, (60, 60, 64))
    line(hx - 14, hy - 6, hx + 48, hy - 6, (40, 40, 44))
    circle(hx + 8, hy + 16, 5, (40, 40, 44))
    # armoured trucks (all inside the scene)
    for tx in (16, 76, 136):
        rect(x + tx, y + h - 52, 44, 20, (70, 76, 60))
        rect(x + tx + 6, y + h - 66, 20, 14, (90, 96, 80))
        circle(x + tx + 9, y + h - 30, 6, (30, 30, 30))
        circle(x + tx + 33, y + h - 30, 6, (30, 30, 30))
    # badge
    bx, by = x + 16, y + 14
    circle(bx + 12, by + 10, 12, GOLD)
    circle(bx + 12, by + 10, 8, (160, 120, 20))
    draw_text("4+7", bx + 12, by + 7, 1, WHITE, 0, "c")
    # sun and one cactus (both inside the scene)
    circle(x + 60, y + 14, 10, (255, 220, 130))
    rect(x + 10, y + h - 44, 6, 14, (40, 110, 60))
    rect(x + 5, y + h - 38, 5, 4, (40, 110, 60))
    rect(x + 16, y + h - 40, 5, 4, (40, 110, 60))
    speckle(x, y, w, h, (255, 255, 255), 111, 0.02)


def scene_fiji(x, y, w, h):
    """Udine: Fiji beat Italy 21-16, rugby posts and a flying ball."""
    vgrad(x, y, w, h, (150, 200, 235), (220, 235, 200))
    rect(x, y + h - 36, w, 36, (100, 160, 80))
    for k in range(8):
        hline(x + (k * 41) % w, y + h - 28 + (k % 3) * 8, 40, (140, 200, 110))
    # posts (kept inside the scene)
    px0 = x + w // 2 - 44
    vline(px0, y + 16, h - 40, WHITE)
    vline(px0 + 88, y + 16, h - 40, WHITE)
    hline(px0, y + h - 24, 88, WHITE)
    # ball mid-flight, near the right post
    bx, by = x + w // 2 + 34, y + 44
    for t in range(6):
        line(bx - 14 + t * 5, by - 4 + t, bx - 10 + t * 5, by + 4 - t,
             (120, 70, 30))
    circle(bx, by, 10, (150, 95, 45))
    circle(bx, by, 6, (200, 140, 80))
    # players (heads below the scoreboard's bottom edge)
    for dx, c in ((-70, (20, 90, 160)), (64, (200, 30, 40))):
        fx = x + w // 2 + dx
        circle(fx, y + h - 52, 7, (240, 200, 160))
        rect(fx - 8, y + h - 44, 16, 26, c)
        rect(fx - 7, y + h - 18, 6, 18, (240, 240, 235))
        rect(fx + 2, y + h - 18, 6, 18, (240, 240, 235))
    # scoreboard, top centre (clear of players and ball)
    rect(x + w // 2 - 56, y + 8, 112, 24, (20, 30, 40))
    recto(x + w // 2 - 56, y + 8, 112, 24, GOLD, 2)
    draw_text("FIJ 21-16 ITA", x + w // 2, y + 15, 1, WHITE, 1, "c")
    # crowd dots along the bottom and a cloud
    for k in range(12):
        cx = x + 10 + (k * 29) % (w - 20)
        px(cx, y + h - 6, (200, 60, 60) if k % 3 == 0 else (240, 240, 240))
        px(cx + 1, y + h - 6, (200, 60, 60) if k % 3 == 0 else (240, 240, 240))
    circle(x + 14, y + 12, 5, WHITE)
    circle(x + 22, y + 10, 7, WHITE)
    speckle(x, y, w, h, (255, 255, 255), 122, 0.02)


def scene_bolsonaro(x, y, w, h):
    """Brasilia: a hospital bed and a monitor's heartbeat line."""
    vgrad(x, y, w, h, (200, 220, 235), (235, 230, 210))
    # flag colours strip + label (drawn before the patient)
    for k, c in enumerate([(0, 150, 70), (255, 220, 40), (0, 60, 160)]):
        rect(x + 16 + k * 40, y + 8, 38, 12, c)
    draw_text("ICU", x + 16, y + 24, 2, (160, 20, 30), 1, "l")
    # monitor, top right
    rect(x + w - 118, y + 8, 104, 32, (20, 30, 40))
    recto(x + w - 118, y + 8, 104, 32, (90, 110, 130), 2)
    pts = [(x + w - 112, y + 28), (x + w - 96, y + 28), (x + w - 88, y + 16),
           (x + w - 80, y + 34), (x + w - 72, y + 28), (x + w - 56, y + 28),
           (x + w - 48, y + 16), (x + w - 40, y + 34), (x + w - 32, y + 28),
           (x + w - 20, y + 28)]
    for a, b in zip(pts, pts[1:]):
        line(a[0], a[1], b[0], b[1], (110, 255, 140))
    # bed
    bx = x + 16
    rect(bx, y + h - 38, 150, 10, (120, 130, 140))
    rect(bx, y + h - 28, 8, 14, (90, 100, 110))
    rect(bx + 142, y + h - 28, 8, 14, (90, 100, 110))
    circle(bx + 10, y + h - 14, 5, (60, 60, 60))
    circle(bx + 140, y + h - 14, 5, (60, 60, 60))
    # patient
    rect(bx + 30, y + h - 50, 96, 12, (240, 240, 235))
    circle(bx + 40, y + h - 56, 8, (240, 200, 160))
    # floor line
    hline(x + 8, y + h - 6, w - 16, (150, 160, 170))
    speckle(x, y, w, h, (255, 255, 255), 133, 0.02)


def scene_ebola(x, y, w, h):
    """Ituri: a clinic in the forest, a barrier, virus dots in the air."""
    vgrad(x, y, w, h, (180, 215, 170), (120, 160, 110))
    # forest (trees capped at 40px tall, inside the scene)
    for tx in (8, 40, 72, w - 84, w - 52, w - 20):
        line(x + tx + 10, y + h - 30, x + tx + 10, y + h - 48, (80, 60, 40))
        tri(x + tx, y + h - 46, x + tx + 10, y + h - 68, x + tx + 20,
            y + h - 46, (40, 100, 50))
        tri(x + tx + 2, y + h - 38, x + tx + 10, y + h - 58, x + tx + 18,
            y + h - 38, (50, 120, 60))
    rect(x, y + h - 30, w, 30, (110, 130, 70))
    # clinic tent
    tx = x + w // 2 - 44
    rect(tx, y + h - 62, 88, 32, WHITE)
    tri(tx - 8, y + h - 62, tx + 44, y + h - 72, tx + 96, y + h - 62, WHITE)
    rect(tx + 38, y + h - 58, 12, 20, RED)
    rect(tx + 30, y + h - 52, 28, 7, RED)
    # barrier tape
    line(x + 10, y + h - 18, x + w - 10, y + h - 10, (255, 200, 30))
    for k in range(9):
        xx = x + 14 + k * 34
        line(xx, y + h - 18, xx + 8, y + h - 10, (20, 20, 20))
    # virus dots (clear of the ITURI label, which spans x+14..x+69)
    for dx, dy, r in [(100, 10, 3), (150, 14, 4), (210, 10, 3),
                      (250, 22, 4), (280, 12, 3)]:
        circle(x + dx, y + dy, r, (120, 30, 30))
        for ox, oy in [(-r - 2, 0), (r + 2, 0), (0, -r - 2), (0, r + 2)]:
            px(x + dx + ox, y + dy + oy, (120, 30, 30))
    draw_text("ITURI", x + 14, y + 12, 2, (90, 20, 20), 1, "l")
    # birds and a path to the tent door
    for bx, by in [(160, 10), (182, 16)]:
        line(bx - 5, by, bx, by - 3, (40, 40, 40))
        line(bx, by - 3, bx + 5, by, (40, 40, 40))
    rect(tx + 40, y + h - 30, 12, 12, (200, 180, 140))
    speckle(x, y, w, h, (255, 255, 255), 144, 0.02)


SCENES = [scene_nvda, scene_benghazi, scene_dymer, scene_cop31, scene_tanker,
          scene_nepal, scene_wellington, scene_sudan, scene_kenya_drc,
          scene_chapo, scene_fiji, scene_bolsonaro, scene_ebola]


# ---------------------------------------------------------------- world map
# Continents as ellipses on a 92 x 30 lon/lat grid (lon -180..180,
# lat 90..-60). Dots are drawn where a grid cell falls inside an ellipse.
MAP_ELLIPSES = [
    # North America
    (14, 7, 11, 5), (10, 12, 9, 4), (20, 13, 8, 4), (26, 17, 5, 3),
    (6, 17, 4, 3),
    # Greenland
    (30, 3, 4, 2),
    # South America
    (32, 21, 5, 3), (33, 25, 4, 4), (35, 30, 3, 4), (36, 35, 2, 3),
    # Europe
    (48, 8, 5, 3), (50, 11, 4, 2), (53, 6, 3, 2),
    # Africa
    (48, 17, 6, 4), (50, 21, 6, 4), (52, 25, 5, 4), (53, 29, 3, 3),
    (45, 15, 3, 2),
    # Asia
    (60, 7, 9, 4), (66, 10, 10, 4), (74, 8, 8, 4), (80, 12, 7, 4),
    (70, 16, 8, 4), (78, 19, 6, 3), (84, 15, 5, 3), (88, 10, 4, 3),
    # SE Asia islands
    (76, 22, 4, 2), (80, 23, 3, 1),
    # Australia
    (78, 27, 6, 3), (82, 28, 3, 2),
    # New Zealand
    (89, 31, 1, 2),
    # Japan
    (87, 12, 1, 3),
    # UK
    (45, 6, 1, 2),
]


def map_xy(lon, lat, mx, my, mw, mh):
    gx = (lon + 180.0) / 360.0 * 92.0
    gy = (90.0 - lat) / 150.0 * 30.0
    return (mx + gx / 92.0 * mw, my + gy / 30.0 * mh)


def draw_map(mx, my, mw, mh, pins):
    """Dotted world map; pins = list of (lon, lat, number)."""
    rect(mx, my, mw, mh, (16, 42, 66))
    cols, rows = 92, 30
    cw = mw / cols
    ch = mh / rows
    for gy in range(rows):
        for gx in range(cols):
            inside = False
            for (ex, ey, rx, ry) in MAP_ELLIPSES:
                if ((gx - ex) / rx) ** 2 + ((gy - ey) / ry) ** 2 <= 1.0:
                    inside = True
                    break
            if inside:
                cx = int(mx + (gx + 0.5) * cw)
                cy = int(my + (gy + 0.5) * ch)
                circle(cx, cy, 1, (120, 170, 210))
    for (lon, lat, num) in pins:
        px_, py_ = map_xy(lon, lat, mx, my, mw, mh)
        circle(int(px_), int(py_), 7, RED)
        circle(int(px_), int(py_), 7, WHITE, fill=False)
        draw_text(str(num), int(px_), int(py_) - 3, 1, WHITE, 0, "c")


# ---------------------------------------------------------------- story bank
# (headline, kicker, body, region, lon, lat) -- every story was first
# reported on Monday 23 November 2026 (UTC). Claims are attributed to
# their makers; nothing unconfirmed is stated as fact.
DRAWN = [
    ("HUANG IS BACK AT NVIDIA",
     "TECH . WALL STREET",
     "Board reinstates Jensen Huang as chief executive 11 days after he "
     "resigned; shares jump 31.5% and lift the whole market.",
     "N AMERICA", -122.0, 37.4),
    ("UKRAINE SINKS RUSSIAN SHIP OFF LIBYA",
     "CONFLICT . BENGHAZI",
     "Kyiv says seven sea drones sank the corvette Merkury in Benghazi "
     "port; the UN mission in Libya demands an inquiry.",
     "AFRICA", 20.1, 32.1),
    ("RUSSIAN STRIKE KILLS 11 IN DYMER",
     "WAR . KYIV REGION",
     "A missile hits an apartment block north of Kyiv; a drone strikes a "
     "kindergarten in Kharkiv as 153 drones fly overnight.",
     "EUROPE", 30.3, 50.8),
    ("AFTER COP31: BLAME AND DESPAIR",
     "CLIMATE . CANBERRA",
     "With the Antalya talks collapsed, Australia's opposition blames "
     "minister Chris Bowen; Pacific islands say they were let down.",
     "OCEANIA", 149.1, -35.3),
    ("TRUMP DARES IRAN'S TANKER CONVOY",
     "MIDDLE EAST . HORMUZ",
     "The president says 14 tankers testing the US blockade would end up "
     "\"at the bottom of the sea\"; strikes may resume in the new year.",
     "MID EAST", 56.5, 26.5),
    ("NEPAL'S SHAH MEETS MODI IN DELHI",
     "DIPLOMACY . INDIA",
     "The prime ministers hold bilateral talks; India pledges about "
     "1.4 billion euros to rebuild after a deadly glacier flood.",
     "ASIA", 77.2, 28.6),
    ("WELLINGTON TEST ENDS IN A DRAW",
     "CRICKET . NEW ZEALAND",
     "Mitchell and Phillips bat 43 overs to hold India, who declared at "
     "720 for 9; New Zealand reach 239 for 5 on the final day.",
     "OCEANIA", 174.8, -41.3),
    ("24 CIVILIANS KILLED IN SOUTH SUDAN",
     "CONFLICT . WARRAP",
     "Local officials blame suspected SPLA-IO fighters for the attack on "
     "Bol Bol Boma in Tonj East County over the weekend.",
     "AFRICA", 28.7, 7.9),
    ("KENYA AND DR CONGO RESTORE TIES",
     "DIPLOMACY . AFRICA",
     "After more than two years of fallout, the two countries agree to "
     "send ambassadors back; Ruto announces the deal in Nairobi.",
     "AFRICA", 36.8, -1.3),
    ("CHAPO RAID TOLL: 4 SOLDIERS, 7 GUNMEN",
     "MEXICO . SINALOA",
     "Mexico confirms the dead from the weekend operation that captured "
     "cartel leader Chapo Isidro after a fierce gun battle.",
     "LATIN AM", -107.4, 24.8),
    ("FIJI EDGE ITALY 21-16 IN UDINE",
     "RUGBY . NATIONS CHAMPIONSHIP",
     "Tevita Ikanivere scores two tries as Fiji take their first win of "
     "the championship against the hosts in Italy.",
     "OCEANIA", 13.2, 46.1),
    ("BOLSONARO TAKEN TO ICU IN BRASILIA",
     "BRAZIL . HEALTH",
     "The former president is admitted to intensive care with an acute "
     "bowel obstruction after strong abdominal pains.",
     "LATIN AM", -47.9, -15.8),
    ("FIGHTING TRAPS EBOLA RESPONDERS",
     "HEALTH . ITURI, DR CONGO",
     "Heavy fighting near a hospital in Ituri province holds back the "
     "Ebola response, the WHO says, as cases keep spreading.",
     "AFRICA", 29.5, 1.5),
]

# (one-line brief, region) -- numbered 14..46
BRIEFS = [
    ("S&P +4.73%, NASDAQ +6.51%, DOW +3.01%", "N AMERICA"),
    ("KOSPI -3.3%; SAMSUNG -3.1%, SK HYNIX -2.5%", "ASIA"),
    ("SENSEX -1,484; NIFTY -1.75%; RUPEE 92.92", "ASIA"),
    ("GOLD $3,635 +3.3%; BITCOIN $61,147; OIL $80", "GLOBAL"),
    ("BESSENT DEMANDS ANSWERS ON NVIDIA CHINA SALES", "N AMERICA"),
    ("RUBIO MEETS QATAR PM IN WASHINGTON ON IRAN", "N AMERICA"),
    ("TRUMP: IRAN FIRED MORE MISSILES IN A WEEK", "N AMERICA"),
    ("EU PROPOSES 22ND SANCTIONS PACKAGE ON RUSSIA", "EUROPE"),
    ("NATO MEETING IN BERLIN WARNS RUSSIA", "EUROPE"),
    ("BURNHAM: CLOSER EU TIES COULD HELP BRITAIN", "EUROPE"),
    ("EU LEADERS WRANGLE OVER 45BN UKRAINE LOAN", "EUROPE"),
    ("FLASH NOVEMBER PMIS DUE ACROSS THE WEST", "GLOBAL"),
    ("UKRAINE DRONES HIT OIL SITES IN 3 REGIONS", "EUROPE"),
    ("POLAND PROBES RUSSIAN MISSILES ON ITS SOIL", "EUROPE"),
    ("POLAND: RUSSIA 'TWICE TRIED TO KILL' RAPPER", "EUROPE"),
    ("NETANYAHU-EISENKOT TALKS END WITHOUT DEAL", "MID EAST"),
    ("ZAMBIA: OPPOSITION LEADER IN TREASON TRIAL", "AFRICA"),
    ("AFRICAN ENERGY STATES GAINED $21.6BN IN WAR", "AFRICA"),
    ("DOZENS KILLED IN NIGERIA'S NIGER STATE", "AFRICA"),
    ("GAMBIA INTERCEPTS 491 WOULD-BE MIGRANTS", "AFRICA"),
    ("EL NINO RAISES CYCLONE THREAT, PACIFIC WARNS", "OCEANIA"),
    ("SUDAN: RSF DRONE STRIKES 'MAY BE WAR CRIMES'", "AFRICA"),
    ("DELTA FAULT DELAYS ~1,000 THANKSGIVING FLIGHTS", "N AMERICA"),
    ("US ARMY TO DETONATE IOWA BOMB CHEMICALS", "N AMERICA"),
    ("49ERS RELEASE BRANDON AIYUK AFTER DISPUTE", "N AMERICA"),
    ("JOKIC'S 202ND TRIPLE-DOUBLE: NUGGETS WIN IN OT", "N AMERICA"),
    ("WARRIORS EDGE CELTICS 88-87; BOSTON LOSES 4TH", "N AMERICA"),
    ("MARCOS URGES STRONGER ASEAN; SINGAPORE CHAIRS", "ASIA"),
    ("ASIA OPENS BEHIND NEW MARKET DEFENCES", "ASIA"),
    ("WONG DEFENDS US ALLIANCE, AUKUS IN CANBERRA", "OCEANIA"),
    ("ARGENTINA FM CASTS DOUBT ON BRAZIL VOTE COUNT", "LATIN AM"),
    ("GTA VI DAY-ONE SALES PUT AT $3.79BN", "GLOBAL"),
    ("GURU NANAK JAYANTI OBSERVED WORLDWIDE", "ASIA"),
]

TIMELINE = [
    ("00:04", "TRUMP: IRAN FIRED MORE MISSILES IN A WEEK"),
    ("04:27", "JOKIC'S 202ND TRIPLE-DOUBLE"),
    ("05:01", "WELLINGTON TEST DRAWN"),
    ("14:43", "TRUMP: IRAN STRIKES MAY RESUME IN NEW YEAR"),
    ("18:26", "WHO: FIGHTING TRAPS EBOLA RESPONDERS"),
    ("21:00", "S&P CLOSES +4.73%, BEST DAY SINCE APRIL 2025"),
]

SIX_NUMBERS = [
    ("46", "STORIES"),
    ("13", "DRAWN SCENES"),
    ("8", "REGIONS"),
    ("+31.5%", "NVIDIA SHARES"),
    ("+4.73%", "S&P 500"),
    ("24", "DEAD IN S. SUDAN"),
]

# Stories deliberately left out: first reported 21-22 November, or not
# yet happened. The collapse itself was Sunday; Monday brought the
# reactions, which the poster covers instead.
DATE_CHECK = [
    "COP31 COLLAPSE (SUN 22 NOV)",
    "DEMOCRATS 258 SEATS (22 NOV)",
    "LIVERPOOL 4-0 MAN UTD (22 NOV)",
    "EU-INDONESIA DEAL (SAT 21 NOV)",
    "LULA RE-ELECTED (SUN 22 NOV)",
    "CHAPO ISIDRO SEIZED (SAT 21 NOV)",
    "WEALTH-TAX SUMMIT (SAT 21 NOV)",
    "SHENZHEN SUMMIT (22 NOV)",
    "INDIA 720/9 (22 NOV)",
    "VERSTAPPEN GP WIN (22 NOV)",
    "KYIV DRONE STRIKE (22 NOV)",
    "SEOUL MINISTER QUITS (22 NOV)",
    "NOT YET: THANKSGIVING (26 NOV)",
    "NOT YET: SPAIN VOTE (29 NOV)",
]

SOURCES = ("SOURCES: REUTERS - AP - AFP - AL JAZEERA - UN NEWS - PANA - "
           "OKAYAFRICA - SYDNEY MORNING HERALD - ESPN")


def region_counts():
    counts = {}
    for item in DRAWN:
        counts[item[3]] = counts.get(item[3], 0) + 1
    for _, region in BRIEFS:
        counts[region] = counts.get(region, 0) + 1
    return counts


# ---------------------------------------------------------------- layout
def card(x, y, w, h, number, region, scene_fn, kicker, headline, body,
         scene_h, head_scale=1, body_lines=3):
    rect(x, y, w, h, WHITE)
    rect(x, y, 4, h, REGION_COLORS[region])
    recto(x, y, w, h, GREY)
    scene_fn(x + 5, y + 5, w - 10, scene_h)
    recto(x + 5, y + 5, w - 10, scene_h, (200, 195, 185))
    speckle(x + 5, y + 5, w - 10, scene_h, (255, 255, 255), number * 31,
            0.05)
    # story number badge
    circle(x + 16, y + 16, 9, RED)
    draw_text(str(number), x + 16, y + 13, 1, WHITE, 0, "c")
    ty = y + 5 + scene_h + 6
    draw_text(kicker, x + 8, ty, 1, RED, 1)
    ty += 11
    ty = text_block(headline, x + 8, ty, w - 16, head_scale, INK, 1,
                    lh=CHAR_H * head_scale + 3, max_lines=2)
    text_block(body, x + 8, ty + 2, w - 16, 1, (60, 60, 60), 1, lh=10,
               max_lines=body_lines)


def draw_masthead():
    rect(0, 0, W, 6, RED)
    rect(0, 6, W, 96, NAVY)
    speckle(0, 6, W, 96, (10, 28, 50), 5, 0.10)
    for dx in (-262, 262):
        cx = W // 2 + dx
        tri(cx, 26, cx + 7, 33, cx, 40, GOLD)
        tri(cx, 40, cx + 7, 33, cx, 26, GOLD)
        tri(cx, 26, cx - 7, 33, cx, 40, GOLD)
        tri(cx, 40, cx - 7, 33, cx, 26, GOLD)
    draw_text("THE MONDAY GLOBE", W // 2, 16, 5, WHITE, 1, "c")
    draw_text("MONDAY 23 NOVEMBER 2026", W // 2, 58, 4, GOLD_L, 1, "c")
    draw_text("ALL EVENTS FIRST REPORTED MONDAY 23 NOVEMBER 2026 (UTC)",
              W // 2, 90, 1, (180, 200, 220), 1, "c")
    hline(0, 102, W, GOLD)


def draw_timeline():
    rect(0, 103, W, 37, SLATE)
    for row in range(2):
        for col in range(3):
            idx = row * 3 + col
            t, txt = TIMELINE[idx]
            ex = 12 + col * 340
            ey = 109 + row * 16
            draw_text(t, ex, ey, 1, GOLD_L, 1)
            draw_text(txt, ex + 36, ey, 1, WHITE, 1)


def draw_region_strip():
    counts = region_counts()
    assert sum(counts.values()) == 46, counts
    order = ["N AMERICA", "EUROPE", "ASIA", "AFRICA",
             "MID EAST", "OCEANIA", "LATIN AM", "GLOBAL"]
    for k, region in enumerate(order):
        x = 8 + k * 126
        rect(x, 140, 126, 22, REGION_COLORS[region])
        draw_text("%s %d" % (region, counts[region]), x + 63, 146, 1,
                  WHITE, 1, "c")


def draw_six_numbers():
    for k, (num, label) in enumerate(SIX_NUMBERS):
        x = 8 + k * 168
        rect(x, 162, 168, 22, WHITE)
        recto(x, 162, 168, 22, LGREY)
        nw = text_width(num, 2, 1)
        lw = text_width(label, 1, 1)
        sx = x + (168 - nw - 6 - lw) // 2
        draw_text(num, sx, 166, 2, RED, 1)
        draw_text(label, sx + nw + 6, 170, 1, GREY, 1)


def draw_briefs():
    draw_text("ALSO ON MONDAY", 8, 742, 2, NAVY, 1)
    draw_text("33 MORE STORIES", 8 + text_width("ALSO ON MONDAY", 2, 1) + 12,
              746, 1, RED, 1)
    hline(8, 760, 632, RED)
    for k, (txt, region) in enumerate(BRIEFS):
        col = 0 if k < 17 else 1
        row = k if k < 17 else k - 17
        bx = 8 + col * 320
        by = 766 + row * 14
        draw_text("%d." % (14 + k), bx, by, 1, RED, 0)
        line_txt = fit_line(txt, 278, 1, 0)
        draw_text(line_txt, bx + 26, by, 1, INK, 0)
        # region tick
        rect(bx + 306, by + 1, 5, 5, REGION_COLORS[region])


def draw_date_check():
    x, y, w, h = 648, 892, 368, 100
    rect(x, y, w, h, (255, 245, 240))
    recto(x, y, w, h, RED, 2)
    draw_text("DATE CHECK - NOT 23 NOVEMBER", x + 10, y + 7, 1, RED, 1)
    hline(x + 10, y + 19, w - 20, RED)
    half = (len(DATE_CHECK) + 1) // 2
    for k, item in enumerate(DATE_CHECK):
        col = 0 if k < half else 1
        row = k if k < half else k - half
        ix = x + 10 + col * 182
        iy = y + 24 + row * 11
        draw_text("X " + item, ix, iy, 1, (90, 30, 30), 0)


def draw_poster():
    rect(0, 0, W, H, PAPER)
    speckle(0, 0, W, H, (233, 227, 214), 7, 0.09)
    draw_masthead()
    draw_timeline()
    draw_region_strip()
    draw_six_numbers()
    # 3 leads
    for k in range(3):
        headline, kicker, body, region, lon, lat = DRAWN[k]
        card(8 + k * 336, 188, 328, 228, k + 1, region, SCENES[k], kicker,
             headline, body, 130, head_scale=2, body_lines=3)
    # 10 more illustrated stories
    for k in range(10):
        idx = 3 + k
        headline, kicker, body, region, lon, lat = DRAWN[idx]
        row = 0 if k < 5 else 1
        col = k if k < 5 else k - 5
        x = 8 + col * 201
        y = 420 + row * 160
        card(x, y, 195, 156, idx + 1, region, SCENES[idx], kicker,
             headline, body, 76, head_scale=1, body_lines=3)
    # briefs
    draw_briefs()
    # map panel
    rect(648, 740, 368, 144, WHITE)
    recto(648, 740, 368, 144, GREY)
    draw_text("WHERE IT HAPPENED", 832, 746, 1, NAVY, 1, "c")
    pins = [(lon, lat, i + 1) for i, (_, _, _, _, lon, lat)
            in enumerate(DRAWN)]
    draw_map(656, 762, 352, 110, pins)
    draw_text("PINS = DRAWN STORIES - DOTS = BRIEFS", 832, 876, 1, GREY, 1,
              "c")
    draw_date_check()
    # footer
    draw_text(SOURCES, W // 2, 1004, 1, GREY, 1, "c")


# ---------------------------------------------------------------- PNG output
def chunk(kind, data):
    out = struct.pack(">I", len(data)) + kind + data
    out += struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return out


def encode_png():
    raw = bytearray()
    for y in range(H):
        raw.append(0)
        raw += buf[y * W * 3:(y + 1) * W * 3]
    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def main():
    draw_poster()
    data = encode_png()
    outdir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "entry.png")
    with open(path, "wb") as f:
        f.write(data)
    print("wrote %s %d bytes sha256=%s" % (
        path, len(data), hashlib.sha256(data).hexdigest()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
