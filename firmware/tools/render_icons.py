"""Render the Codex and Claude app icons as small indexed BMPs for the panel.

Sources are the icons shipped with the installed desktop apps (macOS paths below):
the ChatGPT knot from ChatGPT.app (used for Codex) and the Claude spark from
Claude.app's tray icon. Both are reduced to a shape and tinted with the panel colour.

Usage:
    pip install pillow
    python render_icons.py ../images [size]
"""

import sys
from pathlib import Path

from PIL import Image

CODEX_ICON = "/Applications/ChatGPT.app/Contents/Resources/icon-chatgpt.png"
CLAUDE_ICON = "/Applications/Claude.app/Contents/Resources/TrayIconTemplate@3x.png"
CODEX_COLOR = (0x44, 0xC7, 0xF4)
CLAUDE_COLOR = (0xFF, 0x6B, 0x1A)
BACKGROUND = (0x02, 0x03, 0x04)
COLORS = 16


def square(image):
    box = image.getbbox()
    image = image.crop(box)
    side = max(image.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    return canvas


def codex(size):
    # The ChatGPT knot: dark strokes on a light app tile. Stroke darkness becomes
    # coverage, then it is tinted with the panel's Codex colour like the Claude spark.
    icon = Image.open(CODEX_ICON).convert("RGBA")
    tile = icon.getchannel("A").point(lambda a: 255 if a > 200 else 0)
    ink = icon.convert("L").point(lambda v: max(0, min(255, (200 - v) * 2)))
    coverage = Image.new("L", icon.size, 0)
    coverage.paste(ink, mask=tile)
    knot = Image.new("RGBA", icon.size, (0, 0, 0, 0))
    knot.putalpha(coverage)
    alpha = square(knot).resize((size, size), Image.LANCZOS).getchannel("A")
    tinted = Image.new("RGBA", (size, size), CODEX_COLOR + (255,))
    tinted.putalpha(alpha)
    return tinted


def claude(size):
    alpha = square(Image.open(CLAUDE_ICON).convert("RGBA")).resize((size, size), Image.LANCZOS).getchannel("A")
    tinted = Image.new("RGBA", (size, size), CLAUDE_COLOR + (255,))
    tinted.putalpha(alpha)
    return tinted


def to_indexed(icon):
    flat = Image.new("RGB", icon.size, BACKGROUND)
    flat.paste(icon, mask=icon.getchannel("A"))
    # Index 0 stays the panel background so the device can treat it as transparent.
    indexed = flat.quantize(colors=COLORS - 1, method=Image.Quantize.MEDIANCUT)
    palette = indexed.getpalette()[: (COLORS - 1) * 3]
    shifted = indexed.point(lambda i: i + 1)
    shifted.putpalette(list(BACKGROUND) + palette)
    mask = icon.getchannel("A").point(lambda a: 255 if a < 24 else 0)
    shifted.paste(0, mask=mask)
    return shifted


def main():
    out_dir = Path(sys.argv[1])
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 28
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, builder in (("codex", codex), ("claude", claude)):
        path = out_dir / "{}-icon.bmp".format(name)
        to_indexed(builder(size)).save(path)
        print("wrote", path)


if __name__ == "__main__":
    main()
