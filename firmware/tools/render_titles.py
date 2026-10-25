"""Pre-render the "<AGENT> COMPLETED" titles as images for the Qualia panel.

The Big Noodle Titling licence allows using the font but not converting or
redistributing it, so the font file stays outside the repo and only the
rendered phrases ship to the device.

Usage:
    pip install pillow
    python render_titles.py path/to/big_noodle_titling_oblique.ttf ../images

Each BMP is 8-bit indexed with 4 levels (0 = background .. 3 = full ink);
the device maps the levels onto the agent colour.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TITLES = {"codex": "CHATGPT COMPLETED", "claude": "CLAUDE COMPLETED"}
MAX_WIDTH = 900
MAX_HEIGHT = 200
LEVELS = 4


def fit_font(ttf, texts):
    size = MAX_HEIGHT
    while size > 10:
        font = ImageFont.truetype(str(ttf), size)
        boxes = [font.getbbox(text) for text in texts]
        if max(b[2] - b[0] for b in boxes) <= MAX_WIDTH and max(b[3] - b[1] for b in boxes) <= MAX_HEIGHT:
            return font
        size -= 2
    raise ValueError("titles do not fit")


def render(font, text):
    left, top, right, bottom = font.getbbox(text)
    image = Image.new("L", (right - left + 4, bottom - top + 4), 0)
    ImageDraw.Draw(image).text((2 - left, 2 - top), text, font=font, fill=255)
    indexed = image.point(lambda value: round(value * (LEVELS - 1) / 255))
    indexed = indexed.convert("P")
    indexed.putpalette([round(level * 255 / (LEVELS - 1)) for level in range(LEVELS) for _ in range(3)])
    return indexed


def main():
    ttf, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    font = fit_font(ttf, TITLES.values())
    for provider, text in TITLES.items():
        path = out_dir / "{}-completed.bmp".format(provider)
        image = render(font, text)
        image.save(path)
        print("{}: {}x{} px, font {} px".format(path.name, image.width, image.height, font.size))


if __name__ == "__main__":
    main()
