# Simulator: the panel in a browser

A device-first mock-up of the 960×240 panel. The screen is a real 960×240
canvas drawn with the same primitives the ESP32-S3 has (bitmap text,
rectangles, rounded rectangles, circles) and the same Spleen pixel fonts, so
what you see here is what the firmware draws.

Use it to try layouts without hardware. It shows demo values and does not talk
to the backend.

## Run

```bash
python3 -m http.server 4173 -d simulator
```

Then open <http://localhost:4173>. (Opening `index.html` straight from disk
does not work in most browsers because of ES modules.)

## What is in it

- the **Limits** scene: Codex and Claude side by side, 5-hour remainder, reset
  timer, weekly bar, clock and placeholder weather;
- extra concept scenes (**Focus**, **Call**, **Build**) for other uses of the bar;
- a pixel grid overlay, brightness, and a full-screen panel mode;
- the rotary encoder on the right is a concept from an earlier enclosure
  revision; the current build has no controls.

Layout data lives in `src/model.js`, drawing in `src/renderer.js`. Providers are
an array, and the layout splits the width between 2 to 4 of them.
