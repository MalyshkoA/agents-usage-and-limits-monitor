# SPDX-License-Identifier: MIT
"""Full-screen "<AGENT> COMPLETED" call shown when an agent finishes a task.

The panel dims through ordered-dither steps to black, then the title fades in
in the agent's colour. Titles are pre-rendered in Big Noodle Titling (the
Overwatch UI face) by tools/render_titles.py; the font itself is not shipped.
"""

import time
import adafruit_imageload
import bitmaptools
import displayio
import vectorio

WIDTH = 960
HEIGHT = 240
COLORS = {"codex": 0x44C7F4, "claude": 0xFF6B1A}
HOLD_SECONDS = 5.0

# 2x2 ordered dither: which cells of each 2x2 block are black at each step.
DITHER_STEPS = (((0, 0),), ((0, 0), (1, 1)), ((0, 0), (1, 1), (1, 0)))


def _scale(color, factor):
    return (
        int(((color >> 16) & 0xFF) * factor) << 16
        | int(((color >> 8) & 0xFF) * factor) << 8
        | int((color & 0xFF) * factor)
    )


class Celebration:
    def __init__(self, display):
        self.display = display
        self.titles = {}
        for provider in COLORS:
            bitmap, palette = adafruit_imageload.load(
                "/images/{}-completed.bmp".format(provider),
                bitmap=displayio.Bitmap,
                palette=displayio.Palette,
            )
            self.titles[provider] = (bitmap, palette)
        self.levels = len(self.titles["codex"][1])
        self.shade = displayio.Bitmap(WIDTH, HEIGHT, 2)
        self.row = displayio.Bitmap(WIDTH, 2, 2)

    def _dither(self, cells):
        for y in range(2):
            for x in range(WIDTH):
                self.row[x, y] = 1 if (x % 2, y) in cells else 0
        for y in range(0, HEIGHT, 2):
            bitmaptools.blit(self.shade, self.row, 0, y)

    def _refresh(self):
        self.display.refresh(target_frames_per_second=12, minimum_frames_per_second=0)

    def _ink(self, palette, color, strength):
        # Level 0 is the black background; the others ramp up to the agent colour.
        for level in range(1, self.levels):
            palette[level] = _scale(color, strength * level / (self.levels - 1))

    def play(self, provider_id, hold=HOLD_SECONDS):
        scene = self.display.root_group
        auto_refresh = self.display.auto_refresh
        self.display.auto_refresh = False
        shade_palette = displayio.Palette(2)
        shade_palette.make_transparent(0)
        shade_palette[1] = 0x000000
        self.shade.fill(0)
        shade = displayio.TileGrid(self.shade, pixel_shader=shade_palette)
        scene.append(shade)
        try:
            # Dim the scene: denser and denser black dither on top of it.
            for cells in DITHER_STEPS:
                self._dither(cells)
                self._refresh()

            bitmap, palette = self.titles[provider_id]
            color = COLORS[provider_id]
            self._ink(palette, color, 0)
            black = displayio.Palette(1)
            black[0] = 0x000000
            overlay = displayio.Group()
            overlay.append(vectorio.Rectangle(pixel_shader=black, width=WIDTH, height=HEIGHT, x=0, y=0))
            overlay.append(displayio.TileGrid(
                bitmap, pixel_shader=palette,
                x=(WIDTH - bitmap.width) // 2, y=(HEIGHT - bitmap.height) // 2,
            ))
            self.display.root_group = overlay
            for strength in (0.35, 0.7, 1.0):
                self._ink(palette, color, strength)
                self._refresh()

            time.sleep(hold)

            for strength in (0.5, 0.0):
                self._ink(palette, color, strength)
                self._refresh()
        finally:
            scene.remove(shade)
            self.display.root_group = scene
            self.display.auto_refresh = auto_refresh
