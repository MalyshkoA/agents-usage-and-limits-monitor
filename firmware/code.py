# SPDX-License-Identifier: MIT
"""Ambient Status Bar — CircuitPython runtime for Adafruit Qualia ESP32-S3.

Limits come from Quota Watch Bridge (GET /v1/widget, read-only X-Widget-Key).
Settings live in CIRCUITPY/settings.toml, see settings.toml.example.
"""

import gc
import os
import time
import adafruit_imageload
import displayio
import rtc
import wifi
import adafruit_connection_manager
import adafruit_ntp
import adafruit_requests
from adafruit_bitmap_font import bitmap_font
from adafruit_display_text import bitmap_label
from adafruit_display_shapes.circle import Circle
from adafruit_display_shapes.rect import Rect
from adafruit_display_shapes.roundrect import RoundRect
from adafruit_qualia.displays.bar240x960 import Bar240x960
from celebrate import Celebration

WIDTH = 960
HEIGHT = 240
UTILITY_WIDTH = 220
PAD = 24

BLACK = 0x020304
SURFACE = 0x111519
LINE = 0x191D20
TEXT = 0xF4F6F2
MUTED = 0x8B939A
ACCENT = 0xD9FF3F
STALE = 0xFF7356
OFFLINE = 0x3A4248
WAITING = 0xFFB020

WIDGET_URL = os.getenv("QWB_WIDGET_URL") or "https://quota.example.com/v1/widget"
WIDGET_KEY = os.getenv("QWB_WIDGET_KEY") or ""
TZ_OFFSET = int(os.getenv("TZ_OFFSET_HOURS") or 0) * 3600
FETCH_SECONDS = 1
# RGB pixel clock; Adafruit's profile uses 16 MHz (~39 fps). The framebuffer is
# streamed from PSRAM over the bus Wi-Fi also uses, so lower it if the picture
# twitches on radio traffic (after a full power cycle, not just a soft reload).
PANEL_FREQUENCY = int(os.getenv("PANEL_FREQUENCY_HZ") or 16_000_000)
# Data older than this is marked stale on the panel, but never cleared.
STALE_SECONDS = 10 * 60

PROVIDERS = (
    {"id": "codex", "name": "ChatGPT", "color": 0x44C7F4},
    {"id": "claude", "name": "Claude", "color": 0xFF6B1A},
)
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
# Spleen pixel font (BSD-2-Clause, fonts/LICENSE-spleen.txt), used at native sizes without scaling.
FONT_LABEL = bitmap_font.load_font("/fonts/spleen-12x24.pcf")
FONT_VALUE = bitmap_font.load_font("/fonts/spleen-16x32.pcf")
FONT_HERO = bitmap_font.load_font("/fonts/spleen-32x64.pcf")
# Reset timer digits: Spleen 32x64 scaled to 75% (tools/make_timer_font.py).
FONT_TIMER = bitmap_font.load_font("/fonts/spleen-24x48-digits.bdf")
# The 32x64 percentage label sits at y=88; its baseline is y + ascent // 2.
HERO_BASELINE = 88 + 52 // 2
WEATHER = {"location": "MOSCOW", "temperature": 18, "condition": "CLOUDY", "high": 20, "low": 12}


def add_label(group, value, x, y, color=TEXT, font=FONT_LABEL, align="left", baseline=False):
    """baseline=True places the text baseline at y instead of the label's middle."""
    item = bitmap_label.Label(font, text=value, color=color, base_alignment=baseline)
    item.y = y
    group.append(item)
    set_text(item, value, x, align)
    return item


def set_text(item, value, x, align="left"):
    item.text = value
    item.x = x - item.bounding_box[2] if align == "right" else x


def set_bar(group, x, y, width, height, radius, percent, color):
    while len(group):
        group.pop()
    if percent:
        group.append(RoundRect(x, y, max(height, int(width * percent / 100)), height, radius, fill=color))


class ProviderCell:
    def __init__(self, root, provider, region_x, region_width):
        self.color = provider["color"]
        self.x = region_x + PAD
        self.right = region_x + region_width - PAD
        self.available = self.right - self.x
        x = self.x
        # App icons from the desktop apps, 28 px (tools/render_icons.py).
        icon, palette = adafruit_imageload.load(
            "/images/{}-icon.bmp".format(provider["id"]), bitmap=displayio.Bitmap, palette=displayio.Palette
        )
        palette.make_transparent(0)
        root.append(displayio.TileGrid(icon, pixel_shader=palette, x=x, y=32 - icon.height // 2))
        # Name in 16x32: 20 px caps centred on the icon (baseline 42, icon 18..46).
        add_label(root, provider["name"], x + icon.width + 10, 42, TEXT, FONT_VALUE, baseline=True)
        # Agent activity from IDE hooks: dot + word, right side of the name row.
        self.activity_dot = displayio.Group()
        root.append(self.activity_dot)
        self.activity = add_label(root, "", self.right, 32, MUTED, align="right")
        self.remaining = add_label(root, "--%", x - 2, 88, TEXT, FONT_HERO)
        # Reset countdown sits next to the remaining percentage, larger than labels.
        # Time to the 5h reset, right-aligned on the percentage baseline: "1 h 25 min".
        self.reset_parts = [
            add_label(root, "", self.right, HERO_BASELINE, TEXT, FONT_TIMER, baseline=True),
            add_label(root, "", self.right, HERO_BASELINE, MUTED, baseline=True),
            add_label(root, "", self.right, HERO_BASELINE, TEXT, FONT_TIMER, baseline=True),
            add_label(root, "", self.right, HERO_BASELINE, MUTED, baseline=True),
        ]
        add_label(root, "5H", x, 138, MUTED)
        root.append(RoundRect(x, 154, self.available, 14, 7, fill=SURFACE))
        self.bar = displayio.Group()
        root.append(self.bar)
        add_label(root, "WEEK", x, 194, MUTED)
        self.weekly = add_label(root, "--%", self.right, 194, TEXT, align="right")
        root.append(RoundRect(x, 210, self.available, 7, 3, fill=SURFACE))
        self.weekly_bar = displayio.Group()
        root.append(self.weekly_bar)
        self.shown = None

    def place_reset(self, left):
        parts = reset_parts(left)
        # Number labels (even slots) use the large face; pair parts with slots in order.
        slots = [self.reset_parts[0], self.reset_parts[1], self.reset_parts[2], self.reset_parts[3]]
        if len(parts) == 1:
            used = [slots[0]]
        elif len(parts) == 2:
            used = [slots[2], slots[3]]
        else:
            used = slots
        for label in slots:
            if label not in used:
                label.text = ""
        x = self.right
        for label, (text, gap) in reversed(list(zip(used, parts))):
            set_text(label, text, x, "right")
            x = label.x - gap

    def update(self, data, now):
        five_hour, weekly = data.get("five_hour"), data.get("weekly")
        remaining = percent(five_hour)
        week = percent(weekly)
        reset = countdown(five_hour and five_hour.get("resets_at"), now)
        activity = activity_view(data)
        if (remaining, week, reset, activity) == self.shown:
            return
        self.shown = (remaining, week, reset, activity)
        text, color, dot = activity
        self.activity.color = color
        set_text(self.activity, text, self.right, "right")
        while len(self.activity_dot):
            self.activity_dot.pop()
        if dot:
            self.activity_dot.append(Circle(self.activity.x - 14, 32, 6, fill=color))
        set_text(self.remaining, "--%" if remaining is None else "{}%".format(remaining), self.x - 2)
        self.place_reset(reset)
        set_text(self.weekly, "--%" if week is None else "{}%".format(week), self.right, "right")
        set_bar(self.bar, self.x, 154, self.available, 14, 7, remaining, self.color)
        set_bar(self.weekly_bar, self.x, 210, self.available, 7, 3, week, self.color)


def reset_parts(left):
    """(hours, minutes) -> [(text, gap before)] for "1 h 25 min" / "25 min"."""
    if left is None:
        return [("--", 0)]
    hours, minutes = left
    parts = [(str(minutes), 0), ("min", 5)]
    if hours:
        parts = [(str(hours), 0), ("h", 5), (str(minutes), 12), ("min", 5)]
    return parts


def activity_view(data):
    """Server provider status -> (text, color, show dot)."""
    status = data.get("status")
    if status == "working":
        count = data.get("working_agents") or 0
        return ("WORKING {}".format(count) if count > 1 else "WORKING", ACCENT, True)
    if status == "waiting":
        count = data.get("waiting_agents") or 0
        return ("WAITING {}".format(count) if count > 1 else "WAITING", WAITING, True)
    if status == "error":
        return ("ERROR", STALE, True)
    if status == "idle":
        return ("IDLE", MUTED, False)
    return ("", MUTED, False)


def percent(window):
    if not window or window.get("remaining_percent") is None:
        return None
    return max(0, min(100, round(window["remaining_percent"])))


def parse_utc(value):
    """ISO 8601 from the server (always UTC) -> epoch seconds."""
    date, clock = value[:10], value[11:19]
    return time.mktime((int(date[0:4]), int(date[5:7]), int(date[8:10]),
                        int(clock[0:2]), int(clock[3:5]), int(clock[6:8]), 0, -1, -1))


def countdown(resets_at, now):
    if not resets_at:
        return None
    left = max(0, parse_utc(resets_at) - now) // 60
    return (left // 60, left % 60)


def render_scene(display):
    root = displayio.Group()
    root.append(Rect(0, 0, WIDTH, HEIGHT, fill=BLACK))

    provider_width = (WIDTH - UTILITY_WIDTH) // len(PROVIDERS)
    cells = {}
    for index, provider in enumerate(PROVIDERS):
        region_x = provider_width * index
        if region_x:
            root.append(Rect(region_x, 0, 1, HEIGHT, fill=LINE))
        cells[provider["id"]] = ProviderCell(root, provider, region_x, provider_width)

    utility_x = WIDTH - UTILITY_WIDTH
    root.append(Rect(utility_x, 0, 1, HEIGHT, fill=LINE))
    x = utility_x + PAD
    add_label(root, WEATHER["location"], x, 30, TEXT)
    clock = add_label(root, "00:00", x - 2, 74, TEXT, FONT_HERO)
    date = add_label(root, "MON 01 JAN", x, 120, MUTED)
    # Link indicator: accent = fresh data, coral = stale, grey = no data yet.
    link = Circle(x + 11, 154, 10, fill=OFFLINE)
    root.append(link)
    add_label(root, "{}°C".format(WEATHER["temperature"]), x + 32, 156, TEXT, FONT_VALUE)
    add_label(root, WEATHER["condition"], x, 194, MUTED)
    # Link status line: shows why limits are missing without a serial console.
    status = add_label(root, "WIFI...", x, 222, 0x5F686F)

    display.root_group = root
    return cells, clock, date, link, status


def set_if_changed(item, value):
    # Assigning identical text still re-renders the label, which makes the panel twitch.
    if item.text != value:
        item.text = value


def update_clock(clock, date, now):
    local = time.localtime(now + TZ_OFFSET)
    set_if_changed(clock, "{:02d}:{:02d}".format(local.tm_hour, local.tm_min))
    set_if_changed(date, "{} {:02d} {}".format(WEEKDAYS[local.tm_wday], local.tm_mday, MONTHS[local.tm_mon - 1]))


def connect(session_holder):
    # CircuitPython joins the network itself from CIRCUITPY_WIFI_* in settings.toml
    # and keeps it up; reconnect only if the link dropped.
    if not wifi.radio.connected:
        ssid = os.getenv("CIRCUITPY_WIFI_SSID")
        if not ssid:
            return False
        wifi.radio.connect(ssid, os.getenv("CIRCUITPY_WIFI_PASSWORD"))
        session_holder.clear()
        print("wifi:", wifi.radio.ipv4_address)
    if "session" not in session_holder:
        pool = adafruit_connection_manager.get_radio_socketpool(wifi.radio)
        ssl_context = adafruit_connection_manager.get_radio_ssl_context(wifi.radio)
        session_holder["pool"] = pool
        session_holder["session"] = adafruit_requests.Session(pool, ssl_context)
    return True


def sync_time(pool):
    # RTC runs in UTC so reset times from the server compare directly.
    rtc.RTC().datetime = adafruit_ntp.NTP(pool, tz_offset=0, cache_seconds=3600).datetime
    print("ntp:", time.localtime())


def fetch_widget(session):
    response = session.get(WIDGET_URL, headers={"X-Widget-Key": WIDGET_KEY}, timeout=15)
    try:
        if response.status_code != 200:
            raise RuntimeError("widget HTTP {}".format(response.status_code))
        return response.json()
    finally:
        response.close()


displayio.release_displays()
panel = Bar240x960()
panel._timings["frequency"] = PANEL_FREQUENCY
panel.init()
display = panel.display
print("panel:", PANEL_FREQUENCY, "Hz")
display.rotation = 270
cells, clock, date, link, status = render_scene(display)
celebration = Celebration(display)

net = {}
time_synced = False
providers = {}
last_success = None
next_fetch = 0
link_color = OFFLINE
# A provider that goes working/waiting -> idle has just finished a task.
BUSY = ("working", "waiting")
last_status = {}
completed = []
while True:
    now = time.time()
    if now >= next_fetch:
        next_fetch = now + FETCH_SECONDS
        stage = "WIFI"
        try:
            if not connect(net):
                raise RuntimeError("no SSID")
            if not time_synced:
                stage = "NTP"
                sync_time(net["pool"])
                time_synced = True
                now = time.time()
                next_fetch = now + FETCH_SECONDS
            if not WIDGET_KEY:
                raise RuntimeError("no key")
            stage = "API"
            providers = fetch_widget(net["session"]).get("providers") or {}
            last_success = now
            for provider in PROVIDERS:
                state = (providers.get(provider["id"]) or {}).get("status")
                if last_status.get(provider["id"]) in BUSY and state == "idle":
                    completed.append(provider["id"])
                last_status[provider["id"]] = state
            has_limits = any((providers.get(p["id"]) or {}).get("five_hour") for p in PROVIDERS)
            local = time.localtime(now + TZ_OFFSET)
            set_if_changed(status, "OK {:02d}:{:02d}".format(local.tm_hour, local.tm_min) if has_limits else "NO DATA")
        except Exception as error:  # Network loss must never clear the panel or reboot.
            print("update failed at", stage, repr(error))
            message = str(error)
            set_if_changed(status, message.replace("widget ", "")[:12] if message.startswith("widget HTTP") else stage + " ERR")
            net.clear()
            next_fetch = now + 30
        gc.collect()

    for provider_id, cell in cells.items():
        try:
            cell.update(providers.get(provider_id) or {}, now)
        except Exception as error:  # A bad value must not drop the panel to the console.
            print("render failed for", provider_id, repr(error))
    color = OFFLINE if last_success is None else (ACCENT if now - last_success <= STALE_SECONDS else STALE)
    if color != link_color:
        link.fill = link_color = color
    update_clock(clock, date, now)
    while completed:
        celebration.play(completed.pop(0))
        gc.collect()
    time.sleep(FETCH_SECONDS)
