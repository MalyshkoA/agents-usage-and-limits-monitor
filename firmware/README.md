# Firmware: the panel UI

CircuitPython runtime for the **Adafruit Qualia ESP32-S3** driving the
**ER-TFT3.71-1** 3.71" 240×960 bar display. It joins Wi-Fi, syncs the clock
over NTP, polls the backend's `GET /v1/widget` once a second and draws:

- per provider (ChatGPT/Codex and Claude): remaining share of the 5-hour
  window, time to its reset, the weekly remainder, and agent activity
  (`WORKING`, `WAITING`, `IDLE`, `ERROR`, with a count when several agents run);
- a full-screen "CODEX COMPLETED" / "CLAUDE COMPLETED" moment when a provider
  goes from working or waiting to idle;
- clock and date, a link indicator (accent: fresh data, coral: older than
  10 minutes, grey: nothing yet) and a one-line status at the bottom right.

The weather block is a static placeholder for now.

Network trouble never clears the panel: the last known values stay on screen
and turn stale.

## Files

| Path | Goes to `CIRCUITPY/` | What it is |
|---|---|---|
| `code.py` | `code.py` | Main loop: network, data, layout |
| `celebrate.py` | `celebrate.py` | The "COMPLETED" animation |
| `fonts/` | `fonts/` | Spleen bitmap fonts (BSD-2-Clause) |
| `images/` | `images/` | Provider icons and pre-rendered titles (indexed BMP) |
| `settings.toml.example` | `settings.toml` | Wi-Fi, backend URL and key, time zone |
| `requirements.txt` | libraries in `lib/` | Adafruit libraries for `circup` |
| `tools/` | no | Scripts that regenerate fonts and images on a computer |

## Flash it

1. **Before connecting the display**, compare its 40-pin FPC pinout with the
   Qualia (see the [display datasheet](https://www.buydisplay.com/download/manual/ER-TFT3.71-1_Datasheet.pdf)). Plug and unplug the FPC only with USB
   disconnected. Contacts face the board; close the ZIF latch without force.
2. Install the latest stable CircuitPython for
   [Adafruit Qualia ESP32-S3 RGB666](https://circuitpython.org/board/adafruit_qualia_s3_rgb666/):
   double-tap reset to get the boot drive and drop the `.uf2` onto it (or use
   the web installer from the same page). The board comes back as a drive
   named `CIRCUITPY`.
3. Install the libraries:

   ```bash
   pip install circup
   circup install -r firmware/requirements.txt
   ```

4. Copy the runtime:

   ```bash
   cp firmware/code.py firmware/celebrate.py /Volumes/CIRCUITPY/
   cp -R firmware/fonts firmware/images /Volumes/CIRCUITPY/
   cp firmware/settings.toml.example /Volumes/CIRCUITPY/settings.toml
   ```

5. Edit `CIRCUITPY/settings.toml`:

   | Key | Value |
   |---|---|
   | `CIRCUITPY_WIFI_SSID`, `CIRCUITPY_WIFI_PASSWORD` | Your 2.4 GHz network |
   | `QWB_WIDGET_URL` | `https://<your server>/v1/widget` |
   | `QWB_WIDGET_KEY` | One of the read-only `QWB_WIDGET_KEYS` from the backend |
   | `TZ_OFFSET_HOURS` | Local offset from UTC in whole hours (the RTC runs in UTC) |
   | `PANEL_FREQUENCY_HZ` | RGB pixel clock, `16000000` by default |

   `settings.toml` holds your Wi-Fi password and the display key: never commit
   it (it is in `.gitignore`).

The board reloads on save; the limits appear within a few seconds.

## Troubleshooting

The status line in the bottom-right corner and the serial console
(`screen /dev/tty.usbmodem* 115200`, or the Mu/Thonny serial panel) tell what
is wrong:

| Status | Meaning |
|---|---|
| `WIFI...` | Starting up |
| `OK 14:32` | Last successful update with limits |
| `NO DATA` | The backend answers but has no limits yet: sign in the server poller |
| `HTTP 401` | Wrong `QWB_WIDGET_KEY` |
| `WIFI ERR` | No network, or no `QWB_WIDGET_KEY` set; the console prints the exact error |
| `NTP ERR` | Time sync failed; check the network or DNS |
| `API ERR` | The backend is unreachable or returned invalid JSON |

After an error the panel retries every 30 seconds.

- **No picture at all.** Run Adafruit's rainbow test UF2 for the 3.7" 240×960
  bar display first, then return to CircuitPython. If the image is rotated or
  mirrored, change `display.rotation` in `code.py`.
- **The picture twitches on Wi-Fi traffic.** The framebuffer is streamed from
  PSRAM over the bus Wi-Fi also uses. Lower `PANEL_FREQUENCY_HZ` (for example
  to `12000000`) and power-cycle the board; a soft reload is not enough.
- **Panel layout.** The display is used in its native 960×240 orientation; the
  same layout is drawn by the [browser simulator](../simulator/).

## Regenerating assets

- `tools/make_timer_font.py`: builds `spleen-24x48-digits.bdf` (Spleen 32×64
  digits scaled to 75%) for the reset timer.
- `tools/render_icons.py`: renders the 28 px provider icons from the icons
  shipped with the ChatGPT and Claude desktop apps on macOS.
- `tools/render_titles.py`: renders the "COMPLETED" titles from Big Noodle
  Titling Oblique (the font is not included; pass its path).

They need Pillow (`pip install pillow`) and run on a computer, not on the board.
