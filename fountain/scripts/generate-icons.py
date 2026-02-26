#!/usr/bin/env python3
"""
Generate Tauri app icons for Fountain.

Requires: macOS (uses sips + iconutil)
No external Python deps — pure stdlib only.

Outputs:
  src-tauri/icons/icon.icns
  src-tauri/icons/icon.ico
  src-tauri/icons/tray-icon.png  (22x22 template icon)
  src-tauri/icons/32x32.png
  src-tauri/icons/128x128.png
  src-tauri/icons/128x128@2x.png
"""

import math
import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

ICONS_DIR = Path(__file__).parent.parent / "src-tauri" / "icons"
WORK_DIR = Path("/tmp/allin-one-icons")

# Brand colors: deep blue bg, white icons
BG_COLOR = (37, 99, 235)   # blue-600
FG_COLOR = (255, 255, 255) # white


# ---------------------------------------------------------------------------
# Minimal PNG writer (pure stdlib, no PIL)
# ---------------------------------------------------------------------------

def _pack_chunk(chunk_type: bytes, data: bytes) -> bytes:
    length = struct.pack(">I", len(data))
    crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    return length + chunk_type + data + crc


def write_png(path: Path, pixels: list[list[tuple[int, int, int, int]]], size: int) -> None:
    """Write an RGBA PNG from a list-of-rows of (R,G,B,A) tuples."""
    raw_rows = []
    for row in pixels:
        row_bytes = bytearray()
        for r, g, b, a in row:
            row_bytes += bytes([r, g, b, a])
        raw_rows.append(b"\x00" + bytes(row_bytes))  # filter type 0

    raw_data = b"".join(raw_rows)
    compressed = zlib.compress(raw_data, 9)

    ihdr_data = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA

    png = (
        b"\x89PNG\r\n\x1a\n"
        + _pack_chunk(b"IHDR", ihdr_data)
        + _pack_chunk(b"IDAT", compressed)
        + _pack_chunk(b"IEND", b"")
    )
    path.write_bytes(png)


# ---------------------------------------------------------------------------
# Drawing primitives (antialiased, no PIL)
# ---------------------------------------------------------------------------

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def make_canvas(size: int, bg: tuple[int, int, int, int] = (0, 0, 0, 0)):
    """Return size×size pixel grid initialized to bg."""
    return [[list(bg) for _ in range(size)] for _ in range(size)]


def blend(canvas, x: int, y: int, r: int, g: int, b: int, alpha: float):
    """Alpha-composite (r,g,b) at coverage alpha onto pixel (x,y)."""
    if x < 0 or y < 0 or x >= len(canvas[0]) or y >= len(canvas):
        return
    px = canvas[y][x]
    a_src = alpha
    a_dst = px[3] / 255.0
    a_out = a_src + a_dst * (1 - a_src)
    if a_out == 0:
        return
    canvas[y][x] = [
        int((r * a_src + px[0] * a_dst * (1 - a_src)) / a_out),
        int((g * a_src + px[1] * a_dst * (1 - a_src)) / a_out),
        int((b * a_src + px[2] * a_dst * (1 - a_src)) / a_out),
        int(a_out * 255),
    ]


def draw_rounded_rect(canvas, x0, y0, x1, y1, radius, r, g, b):
    """Fill a rounded rectangle with antialiased corners."""
    size = len(canvas)
    for py in range(size):
        for px in range(size):
            # Distance to nearest edge inside rect
            cx = max(x0 + radius, min(x1 - radius, px + 0.5))
            cy = max(y0 + radius, min(y1 - radius, py + 0.5))
            dist = math.sqrt((px + 0.5 - cx) ** 2 + (py + 0.5 - cy) ** 2)
            coverage = max(0.0, min(1.0, radius - dist + 0.5))
            if coverage > 0:
                blend(canvas, px, py, r, g, b, coverage)


def draw_arc_thick(canvas, cx, cy, radius, start_angle, end_angle, thickness, r, g, b, samples=200):
    """Draw a thick arc by sampling points along the arc path."""
    for i in range(samples + 1):
        t = start_angle + (end_angle - start_angle) * i / samples
        ax = cx + radius * math.cos(t)
        ay = cy + radius * math.sin(t)
        # Draw a filled circle at this point for thickness
        half = thickness / 2
        ix0, ix1 = int(ax - half - 1), int(ax + half + 2)
        iy0, iy1 = int(ay - half - 1), int(ay + half + 2)
        for py in range(iy0, iy1):
            for px in range(ix0, ix1):
                d = math.sqrt((px + 0.5 - ax) ** 2 + (py + 0.5 - ay) ** 2)
                cov = max(0.0, min(1.0, half - d + 0.5))
                if cov > 0:
                    blend(canvas, px, py, r, g, b, cov)


def draw_triangle(canvas, p1, p2, p3, r, g, b):
    """Fill a triangle using barycentric coordinates."""
    xs = [p1[0], p2[0], p3[0]]
    ys = [p1[1], p2[1], p3[1]]
    x_min, x_max = int(min(xs)) - 1, int(max(xs)) + 2
    y_min, y_max = int(min(ys)) - 1, int(max(ys)) + 2

    def sign(px, py, ax, ay, bx, by):
        return (px - bx) * (ay - by) - (ax - bx) * (py - by)

    for py in range(y_min, y_max):
        for px in range(x_min, x_max):
            # Supersampling 2x2
            cov = 0
            for sx in [0.25, 0.75]:
                for sy in [0.25, 0.75]:
                    spx, spy = px + sx, py + sy
                    d1 = sign(spx, spy, p1[0], p1[1], p2[0], p2[1])
                    d2 = sign(spx, spy, p2[0], p2[1], p3[0], p3[1])
                    d3 = sign(spx, spy, p3[0], p3[1], p1[0], p1[1])
                    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
                    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
                    if not (has_neg and has_pos):
                        cov += 0.25
            if cov > 0:
                blend(canvas, px, py, r, g, b, cov)


# ---------------------------------------------------------------------------
# Icon artwork
# ---------------------------------------------------------------------------

def draw_sync_icon(size: int) -> list:
    """Draw the app icon: blue rounded rect + white circular arrows."""
    canvas = make_canvas(size)
    bg_r, bg_g, bg_b = BG_COLOR
    fg_r, fg_g, fg_b = FG_COLOR

    # Background rounded rect with 22% corner radius
    pad = size * 0.0  # full bleed
    corner = size * 0.22
    draw_rounded_rect(canvas, pad, pad, size - pad, size - pad, corner, bg_r, bg_g, bg_b)

    # Circular sync arrows — two arcs ~270° each with arrowheads
    cx, cy = size / 2, size / 2
    radius = size * 0.28
    thickness = size * 0.09
    ar_size = size * 0.12  # arrowhead size

    # Top arc: left half + up  (270° → 90°, i.e. from 3π/2 around to π/2)
    # We draw two arcs to create the circular arrow look:
    # Arc 1: from ~20° to ~200° (clockwise, upper-right to lower-left)
    a1_start = math.radians(20)
    a1_end = math.radians(200)
    draw_arc_thick(canvas, cx - size * 0.04, cy, radius, a1_start, a1_end, thickness, fg_r, fg_g, fg_b)

    # Arc 2: from ~200° to ~20° going the other way (upper-left to lower-right)
    a2_start = math.radians(200)
    a2_end = math.radians(380)
    draw_arc_thick(canvas, cx + size * 0.04, cy, radius, a2_start, a2_end, thickness, fg_r, fg_g, fg_b)

    # Arrowhead 1 at the end of arc 1 (~200°)
    tip_angle = a1_end
    tip_x = (cx - size * 0.04) + radius * math.cos(tip_angle)
    tip_y = cy + radius * math.sin(tip_angle)
    perp = tip_angle + math.pi / 2
    p1 = (tip_x, tip_y)
    p2 = (tip_x - ar_size * math.cos(tip_angle - 0.5) - ar_size * 0.5 * math.cos(perp),
          tip_y - ar_size * math.sin(tip_angle - 0.5) - ar_size * 0.5 * math.sin(perp))
    p3 = (tip_x - ar_size * math.cos(tip_angle - 0.5) + ar_size * 0.5 * math.cos(perp),
          tip_y - ar_size * math.sin(tip_angle - 0.5) + ar_size * 0.5 * math.sin(perp))
    draw_triangle(canvas, p1, p2, p3, fg_r, fg_g, fg_b)

    # Arrowhead 2 at the end of arc 2 (~380° = ~20°)
    tip_angle2 = a2_end
    tip_x2 = (cx + size * 0.04) + radius * math.cos(tip_angle2)
    tip_y2 = cy + radius * math.sin(tip_angle2)
    perp2 = tip_angle2 + math.pi / 2
    q1 = (tip_x2, tip_y2)
    q2 = (tip_x2 - ar_size * math.cos(tip_angle2 - 0.5) - ar_size * 0.5 * math.cos(perp2),
          tip_y2 - ar_size * math.sin(tip_angle2 - 0.5) - ar_size * 0.5 * math.sin(perp2))
    q3 = (tip_x2 - ar_size * math.cos(tip_angle2 - 0.5) + ar_size * 0.5 * math.cos(perp2),
          tip_y2 - ar_size * math.sin(tip_angle2 - 0.5) + ar_size * 0.5 * math.sin(perp2))
    draw_triangle(canvas, q1, q2, q3, fg_r, fg_g, fg_b)

    return canvas


def draw_tray_icon(size: int) -> list:
    """
    Monochrome template icon for macOS tray (white on transparent).
    macOS renders template images with its own color, so we draw white.
    Two simple circular arrows — simplified for small sizes.
    """
    canvas = make_canvas(size)
    fg_r, fg_g, fg_b = (255, 255, 255)

    cx, cy = size / 2, size / 2
    radius = size * 0.30
    thickness = max(1.5, size * 0.12)

    draw_arc_thick(canvas, cx - size * 0.06, cy, radius,
                   math.radians(20), math.radians(195), thickness, fg_r, fg_g, fg_b)
    draw_arc_thick(canvas, cx + size * 0.06, cy, radius,
                   math.radians(200), math.radians(375), thickness, fg_r, fg_g, fg_b)
    return canvas


# ---------------------------------------------------------------------------
# ICO writer (pure stdlib)
# ---------------------------------------------------------------------------

def write_ico(path: Path, png_files: list[tuple[int, Path]]) -> None:
    """
    Build a .ico from pre-existing PNG files.
    ICO format: ICONDIR + N * ICONDIRENTRY + PNG data blobs.
    """
    images = []
    for size, png_path in png_files:
        data = png_path.read_bytes()
        images.append((size, data))

    n = len(images)
    # ICONDIR header (6 bytes)
    header = struct.pack("<HHH", 0, 1, n)  # reserved=0, type=1 (ICO), count=n

    # Each ICONDIRENTRY is 16 bytes
    offset = 6 + n * 16
    entries = b""
    blobs = b""
    for size, data in images:
        w = size if size < 256 else 0  # 256 stored as 0 in ICO spec
        h = size if size < 256 else 0
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data

    path.write_bytes(header + entries + blobs)


# ---------------------------------------------------------------------------
# Pixel list → PNG tuple conversion helper
# ---------------------------------------------------------------------------

def canvas_to_rows(canvas):
    return [[(p[0], p[1], p[2], p[3]) for p in row] for row in canvas]


# ---------------------------------------------------------------------------
# sips-based resize (macOS)
# ---------------------------------------------------------------------------

def resize_with_sips(src: Path, dst: Path, size: int) -> None:
    subprocess.run(
        ["sips", "-z", str(size), str(size), str(src), "--out", str(dst)],
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    ICONS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Draw and save master 1024×1024 PNG
    print("Drawing 1024×1024 master icon...", flush=True)
    master_path = WORK_DIR / "master.png"
    canvas_1024 = draw_sync_icon(1024)
    write_png(master_path, canvas_to_rows(canvas_1024), 1024)
    print(f"  Saved: {master_path}")

    # 2. Build .iconset directory
    iconset_dir = WORK_DIR / "icon.iconset"
    iconset_dir.mkdir(exist_ok=True)

    iconset_sizes = [16, 32, 64, 128, 256, 512, 1024]
    for s in iconset_sizes:
        dst = iconset_dir / f"icon_{s}x{s}.png"
        resize_with_sips(master_path, dst, s)
        print(f"  sips → {dst.name}")
        # @2x variants
        if s <= 512:
            dst2x = iconset_dir / f"icon_{s}x{s}@2x.png"
            resize_with_sips(master_path, dst2x, s * 2)
            print(f"  sips → {dst2x.name}")

    # 3. iconutil → .icns
    icns_tmp = WORK_DIR / "icon.icns"
    print("Running iconutil...", flush=True)
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_tmp)],
        check=True,
    )
    shutil.copy2(icns_tmp, ICONS_DIR / "icon.icns")
    print(f"  Wrote: {ICONS_DIR / 'icon.icns'} ({(ICONS_DIR / 'icon.icns').stat().st_size} bytes)")

    # 4. Generate .ico (16, 32, 48, 64, 128, 256)
    print("Building .ico...", flush=True)
    ico_sizes = [16, 32, 48, 64, 128, 256]
    ico_pngs = []
    for s in ico_sizes:
        p = WORK_DIR / f"ico_{s}.png"
        if s in iconset_sizes:
            shutil.copy2(iconset_dir / f"icon_{s}x{s}.png", p)
        else:
            resize_with_sips(master_path, p, s)
        ico_pngs.append((s, p))

    write_ico(ICONS_DIR / "icon.ico", ico_pngs)
    print(f"  Wrote: {ICONS_DIR / 'icon.ico'} ({(ICONS_DIR / 'icon.ico').stat().st_size} bytes)")

    # 5. Tray icon (22×22 template — monochrome white on transparent)
    print("Drawing tray icon (22×22)...", flush=True)
    tray_canvas = draw_tray_icon(22)
    write_png(ICONS_DIR / "tray-icon.png", canvas_to_rows(tray_canvas), 22)
    print(f"  Wrote: {ICONS_DIR / 'tray-icon.png'}")

    # 6. Copy standard-sized PNGs used by Tauri
    shutil.copy2(iconset_dir / "icon_32x32.png", ICONS_DIR / "32x32.png")
    shutil.copy2(iconset_dir / "icon_128x128.png", ICONS_DIR / "128x128.png")
    shutil.copy2(iconset_dir / "icon_128x128@2x.png", ICONS_DIR / "128x128@2x.png")
    print("  Copied 32x32.png, 128x128.png, 128x128@2x.png")

    print("\nAll icons generated successfully.")


if __name__ == "__main__":
    main()
