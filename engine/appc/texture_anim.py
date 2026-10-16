# engine/appc/texture_anim.py
"""App.g_kTextureAnimManager (spec 2026-10-16 §7.5).

Stock BC (Tactical/EffectTextures.py) and mods declare a texture's animation
frames as UV rects: AddContainer(path).AddTextureTrack(n).SetFrame(i, l, t, r, b).
We record them and, when they form a regular grid, report (cols, rows) for
that path; CreateTarget uses it when the sprite library has no entry. An
irregular track is logged once and ignored.
"""
from __future__ import annotations

import sys


def _fold(p) -> str:
    return str(p).replace("\\", "/").strip().strip("/").lower()


class _Track:
    def __init__(self, n):
        self.frames = [None] * max(0, int(n))

    def SetFrame(self, i, left, top, right, bottom):
        i = int(i)
        if 0 <= i < len(self.frames):
            self.frames[i] = (float(left), float(top), float(right), float(bottom))


class _Container:
    def __init__(self, path):
        self.path = path
        self.tracks = []

    def AddTextureTrack(self, n):
        t = _Track(n)
        self.tracks.append(t)
        return t


class TextureAnimManager:
    def __init__(self):
        self._containers: dict = {}
        self._warned: set = set()

    def AddContainer(self, path):
        c = _Container(path)
        self._containers[_fold(path)] = c
        return c

    def grid_for(self, path):
        c = self._containers.get(_fold(path))
        if c is None:
            return None
        rects = [f for t in c.tracks for f in t.frames if f is not None]
        grid = _infer_grid(rects)
        if grid is None and rects and c.path not in self._warned:
            self._warned.add(c.path)
            print(f"[texture-anim] {c.path}: frames are not a regular grid; ignored",
                  file=sys.stderr)
        return grid


def _infer_grid(rects):
    if not rects:
        return None
    eps = 1e-3
    w = abs(rects[0][2] - rects[0][0])
    h = abs(rects[0][1] - rects[0][3])
    if w <= 0 or h <= 0:
        return None
    cols, rows = round(1.0 / w), round(1.0 / h)
    if cols < 1 or rows < 1 or abs(cols * w - 1) > eps or abs(rows * h - 1) > eps:
        return None
    for left, top, right, bottom in rects:
        if abs(abs(right - left) - w) > eps or abs(abs(top - bottom) - h) > eps:
            return None
        lo_x, lo_y = min(left, right), min(top, bottom)
        if abs(lo_x / w - round(lo_x / w)) > eps or abs(lo_y / h - round(lo_y / h)) > eps:
            return None
    return (int(cols), int(rows))


g_kTextureAnimManager = TextureAnimManager()


def grid_for(path):
    return g_kTextureAnimManager.grid_for(path)


def reset() -> None:
    g_kTextureAnimManager._containers.clear()
    g_kTextureAnimManager._warned.clear()
