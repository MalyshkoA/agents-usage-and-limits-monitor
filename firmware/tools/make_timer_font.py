"""Build the 24x48 digit font for the reset timer from Spleen 32x64.

Spleen has no size between 16x32 and 32x64, so the 32x64 digits are box-downscaled
to 75% and thresholded; this keeps stroke weight in line with the 32x64 percentage.
Spleen is BSD-2-Clause (fonts/LICENSE-spleen.txt), derivatives are allowed.

Usage:
    pip install pillow
    python make_timer_font.py path/to/spleen-32x64.bdf ../fonts/spleen-24x48-digits.bdf
"""

import re, sys
from PIL import Image

def load(path):
    txt = open(path).read()
    glyphs = {}
    for m in re.finditer(r'ENCODING (\d+)\n(.*?)ENDCHAR', txt, re.S):
        body = m.group(2)
        w, h, x, y = map(int, re.search(r'BBX (-?\d+) (-?\d+) (-?\d+) (-?\d+)', body).groups())
        dw = int(re.search(r'DWIDTH (\d+)', body).group(1))
        rows = body.split('BITMAP\n')[1].split()
        img = Image.new('L', (w, h), 0)
        for j, r in enumerate(rows):
            bits = bin(int(r, 16))[2:].zfill(len(r) * 4)
            for i in range(w):
                if bits[i] == '1':
                    img.putpixel((i, j), 255)
        glyphs[int(m.group(1))] = (img, x, y, dw)
    return glyphs, txt

def scaled(glyphs, factor, method):
    out = {}
    for code, (img, x, y, dw) in glyphs.items():
        w, h = max(1, round(img.width * factor)), max(1, round(img.height * factor))
        s = img.resize((w, h), method).point(lambda v: 255 if v >= 128 else 0)
        out[code] = (s, round(x * factor), round(y * factor), round(dw * factor))
    return out

def write_bdf(glyphs, path, name, size, ascent, descent):
    lines = ['STARTFONT 2.1', f'FONT {name}', f'SIZE {size} 75 75',
             f'FONTBOUNDINGBOX {max(g[0].width for g in glyphs.values())} {ascent + descent} 0 {-descent}',
             'STARTPROPERTIES 2', f'FONT_ASCENT {ascent}', f'FONT_DESCENT {descent}', 'ENDPROPERTIES', f'CHARS {len(glyphs)}']
    for code, (img, x, y, dw) in sorted(glyphs.items()):
        lines += [f'STARTCHAR U+{code:04X}', f'ENCODING {code}', f'SWIDTH {round(dw * 1000 / size)} 0', f'DWIDTH {dw} 0',
                  f'BBX {img.width} {img.height} {x} {y}', 'BITMAP']
        for j in range(img.height):
            bits = ''.join('1' if img.getpixel((i, j)) else '0' for i in range(img.width))
            bits += '0' * (-len(bits) % 8)
            lines.append(''.join(f'{int(bits[k:k + 8], 2):02X}' for k in range(0, len(bits), 8)))
        lines.append('ENDCHAR')
    lines.append('ENDFONT')
    open(path, 'w').write('\n'.join(lines) + '\n')


def main():
    source, target = sys.argv[1], sys.argv[2]
    glyphs, _ = load(source)
    digits = {code: glyph for code, glyph in glyphs.items() if chr(code) in "0123456789-"}
    write_bdf(scaled(digits, 0.75, Image.BOX), target,
              "-spleen-medium-r-normal--48-480-72-72-C-240-ISO10646-1", 48, 39, 9)
    print("wrote", target)


if __name__ == "__main__":
    main()
