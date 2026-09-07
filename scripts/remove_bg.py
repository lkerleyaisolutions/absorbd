"""Make the edge-connected white background of an image transparent.

Flood-fills from the border so only the background (which touches the edges)
is cleared. Interior whites — the nurse's sneakers and the clipboard paper —
are NOT connected to the border, so they stay opaque.
"""

import sys
from collections import deque

import numpy as np
from PIL import Image

THRESHOLD = 232  # a pixel counts as "white-ish" if all RGB channels >= this


def remove_background(in_path: str, out_path: str) -> None:
    img = Image.open(in_path).convert("RGBA")
    arr = np.array(img)
    h, w = arr.shape[:2]
    rgb = arr[:, :, :3].astype(np.int16)

    whiteish = np.all(rgb >= THRESHOLD, axis=2)

    # BFS flood fill from every border pixel that is white-ish.
    bg = np.zeros((h, w), dtype=bool)
    dq = deque()
    for x in range(w):
        for y in (0, h - 1):
            if whiteish[y, x] and not bg[y, x]:
                bg[y, x] = True
                dq.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if whiteish[y, x] and not bg[y, x]:
                bg[y, x] = True
                dq.append((y, x))

    while dq:
        y, x = dq.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not bg[ny, nx] and whiteish[ny, nx]:
                bg[ny, nx] = True
                dq.append((ny, nx))

    # Clear the background and soften the 1px anti-aliased fringe so there's no
    # hard white halo around the figure.
    alpha = arr[:, :, 3].copy()
    alpha[bg] = 0

    # Feather: any kept pixel adjacent to background that is itself light gets
    # partial transparency proportional to how light it is.
    light = np.all(rgb >= 200, axis=2) & ~bg
    pad = np.pad(bg, 1, constant_values=False)
    near_bg = (
        pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:]
    )
    fringe = light & near_bg
    # Map brightness 200..255 -> alpha 255..60 for fringe pixels
    bright = rgb[fringe].max(axis=1)
    faded = np.clip(255 - (bright - 200) * (195 / 55), 60, 255).astype(np.uint8)
    alpha[fringe] = np.minimum(alpha[fringe], faded)

    arr[:, :, 3] = alpha
    Image.fromarray(arr, "RGBA").save(out_path)

    cleared = int(bg.sum())
    print(f"{in_path} -> {out_path}")
    print(f"  size {w}x{h}, cleared {cleared} background px ({cleared / (w * h):.1%})")


if __name__ == "__main__":
    remove_background(sys.argv[1], sys.argv[2])
