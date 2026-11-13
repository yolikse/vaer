#!/usr/bin/env python3
import os
import warnings

# Draw in memory only. We copy frames to the screen ourselves.
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
warnings.filterwarnings("ignore", category=RuntimeWarning)

import json
import math
import random
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import pygame

URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=63.43&lon=10.40"
HEADERS = {"User-Agent": "pilikse-weather/1.0 eskilhsb@gmail.com"}
TZ = ZoneInfo("Europe/Oslo")

W, H = 640, 360   # drawing size, scaled up to fill the monitor
FPS = 15

# Forecast strip along the bottom
COLS = 8          # number of columns
STEP = 2          # hours per column (8 x 2 = next 16 hours)
COL_W = 78
PANEL_Y = 200

# Test an animation: python3 weather_anim.py heavysnow
FORCE = sys.argv[1] if len(sys.argv) > 1 else None

weather = {"series": None, "error": None}


# ---------- screen (framebuffer) ----------

FB_SYS = "/sys/class/graphics/fb0/"


def read_sys(name):
    with open(FB_SYS + name) as f:
        return f.read().strip()


def fb_info():
    bpp = int(read_sys("bits_per_pixel"))
    stride = int(read_sys("stride"))
    m = re.search(r"(\d+)x(\d+)", read_sys("modes"))
    if m:
        w, h = int(m.group(1)), int(m.group(2))
    else:
        w, h = map(int, read_sys("virtual_size").split(","))
    return w, h, bpp, stride


class Screen:
    def __init__(self):
        self.w, self.h, self.bpp, self.stride = fb_info()
        if self.bpp not in (16, 32):
            sys.exit(f"Screen uses {self.bpp} bits per pixel, this script only handles 16 or 32")
        self.fb = open("/dev/fb0", "r+b", buffering=0)
        self.big = pygame.Surface((self.w, self.h), 0, self.bpp)
        print(f"Drawing to {self.w}x{self.h}, {self.bpp} bits per pixel. Ctrl+C to stop.")

    def canvas(self, w, h):
        return pygame.Surface((w, h), 0, self.bpp)

    def show(self, canvas):
        pygame.transform.scale(canvas, (self.w, self.h), self.big)
        data = self.big.get_buffer().raw
        pitch = self.big.get_pitch()
        self.fb.seek(0)
        if pitch == self.stride:
            self.fb.write(data)
        else:
            row = self.w * self.bpp // 8
            for y in range(self.h):
                self.fb.seek(y * self.stride)
                self.fb.write(data[y * pitch:y * pitch + row])

    def clear(self):
        self.big.fill((0, 0, 0))
        self.fb.seek(0)
        self.fb.write(self.big.get_buffer().raw)


# ---------- fetching data ----------

def fetch_loop():
    while True:
        wait = 1800
        try:
            req = urllib.request.Request(URL, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                weather["series"] = json.load(r)["properties"]["timeseries"]
                weather["error"] = None
                expires = r.headers.get("Expires")
                if expires:
                    left = (parsedate_to_datetime(expires) - datetime.now(timezone.utc)).total_seconds()
                    wait = max(600, left + 30)
        except Exception as e:
            weather["error"] = str(e)
            wait = 600
        time.sleep(wait)


def parse_time(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def current_entry(series):
    now = datetime.now(timezone.utc)
    current = series[0]
    for entry in series:
        if parse_time(entry["time"]) <= now:
            current = entry
        else:
            break
    return current


def symbol(entry):
    d = entry["data"]
    for key in ("next_1_hours", "next_6_hours", "next_12_hours"):
        if key in d:
            return d[key]["summary"]["symbol_code"]
    return "cloudy"


def rain(entry):
    d = entry["data"]
    for key in ("next_1_hours", "next_6_hours"):
        if key in d:
            return d[key]["details"].get("precipitation_amount", 0.0)
    return 0.0


# ---------- Norwegian text ----------

LABELS = {
    "clearsky": "Klarvær", "fair": "Lettskyet", "partlycloudy": "Delvis skyet",
    "cloudy": "Skyet", "fog": "Tåke",
    "lightrain": "Lett regn", "rain": "Regn", "heavyrain": "Kraftig regn",
    "lightrainshowers": "Lette regnbyger", "rainshowers": "Regnbyger",
    "heavyrainshowers": "Kraftige regnbyger",
    "lightsleet": "Lett sludd", "sleet": "Sludd", "heavysleet": "Kraftig sludd",
    "lightsleetshowers": "Lette sluddbyger", "sleetshowers": "Sluddbyger",
    "heavysleetshowers": "Kraftige sluddbyger",
    "lightsnow": "Lett snø", "snow": "Snø", "heavysnow": "Kraftig snø",
    "lightsnowshowers": "Lette snøbyger", "snowshowers": "Snøbyger",
    "heavysnowshowers": "Kraftige snøbyger",
}

WEEKDAYS = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]
MONTHS = ["januar", "februar", "mars", "april", "mai", "juni", "juli",
          "august", "september", "oktober", "november", "desember"]
DIRECTIONS = ["N", "NØ", "Ø", "SØ", "S", "SV", "V", "NV"]


def label(code):
    base = code.split("_")[0]
    if base.endswith("andthunder"):
        return LABELS.get(base[:-10], base) + " og torden"
    return LABELS.get(base, base)


def wind_name(deg):
    return DIRECTIONS[int((deg + 22.5) // 45) % 8]


def fmt(x, decimals=1):
    return f"{x:.{decimals}f}".replace(".", ",")


# ---------- animation ----------

class Scene:
    def __init__(self):
        self.code = None
        self.t = 0.0
        self.flash = 0.0
        self.stars = [(random.randrange(W), random.randrange(H // 2), random.uniform(0, 6.28))
                      for _ in range(50)]
        self.fog_band = pygame.Surface((W + 200, 28), pygame.SRCALPHA)
        self.fog_band.fill((225, 225, 225, 55))
        self.white = pygame.Surface((W, H))
        self.white.fill((255, 255, 255))

    def new_cloud(self, x):
        # [x, y, speed px/s, size]
        return [x, random.uniform(20, 140), random.uniform(8, 20), random.uniform(0.7, 1.3)]

    def set_code(self, code):
        if code == self.code:
            return
        self.code = code
        base = code.split("_")[0]

        self.night = "_night" in code or "polartwilight" in code
        self.body = "_" in code          # codes with _day/_night have a sun or moon
        self.thunder = "thunder" in code
        self.fog = base == "fog"

        if base == "clearsky" or self.fog:
            n_clouds = 0
        elif base == "fair":
            n_clouds = 1
        elif base == "partlycloudy" or "showers" in base:
            n_clouds = 3
        else:
            n_clouds = 6
        self.dark = n_clouds >= 6

        amount = 250 if "heavy" in code else 60 if "light" in code else 140
        wet = "rain" in code or "sleet" in code
        white = "snow" in code or "sleet" in code

        self.clouds = [self.new_cloud(random.uniform(-100, W)) for _ in range(n_clouds)]
        self.drops = [[random.uniform(0, W + 50), random.uniform(0, H), random.uniform(350, 500)]
                      for _ in range(amount if wet else 0)]
        self.flakes = [[random.uniform(0, W), random.uniform(0, H), random.uniform(25, 55),
                        random.uniform(0, 6.28)]
                       for _ in range(amount // 2 if white else 0)]

    def update(self, dt):
        self.t += dt
        for c in self.clouds:
            c[0] += c[2] * dt
            if c[0] > W + 120:
                c[:] = self.new_cloud(-150)
        for d in self.drops:
            d[1] += d[2] * dt
            d[0] -= 60 * dt
            if d[1] > H:
                d[0] = random.uniform(0, W + 50)
                d[1] = random.uniform(-20, 0)
        for f in self.flakes:
            f[1] += f[2] * dt
            f[0] += math.sin(self.t + f[3]) * 20 * dt
            if f[1] > H:
                f[0] = random.uniform(0, W)
                f[1] = -5
        if self.thunder and random.random() < dt * 0.15:
            self.flash = 0.3
        self.flash = max(0.0, self.flash - dt)

    def draw(self, surf):
        if self.night:
            sky = (25, 28, 40) if self.dark else (10, 15, 40)
        elif self.dark or self.fog:
            sky = (110, 120, 135)
        else:
            sky = (90, 160, 230)
        surf.fill(sky)

        # stars
        if self.night and not self.dark:
            for x, y, p in self.stars:
                b = int(150 + 100 * math.sin(self.t * 2 + p))
                pygame.draw.circle(surf, (b, b, b), (x, y), 1)

        # sun or moon
        if self.body:
            cx, cy = W - 110, 90
            if self.night:
                pygame.draw.circle(surf, (235, 235, 210), (cx, cy), 36)
                pygame.draw.circle(surf, sky, (cx + 16, cy - 10), 32)
            else:
                for i in range(12):
                    a = self.t * 0.5 + i * math.pi / 6
                    outer = 62 + 6 * math.sin(self.t * 3 + i)
                    start = (cx + math.cos(a) * 48, cy + math.sin(a) * 48)
                    end = (cx + math.cos(a) * outer, cy + math.sin(a) * outer)
                    pygame.draw.line(surf, (255, 210, 60), start, end, 4)
                pygame.draw.circle(surf, (255, 200, 40), (cx, cy), 40)

        # clouds
        if self.night:
            col = (70, 75, 95)
        elif self.dark:
            col = (180, 185, 195)
        else:
            col = (235, 238, 242)
        for x, y, _, s in self.clouds:
            for ox, oy, r in ((0, 0, 30), (30, -12, 36), (65, 0, 28), (32, 10, 30)):
                pygame.draw.circle(surf, col, (int(x + ox * s), int(y + oy * s)), int(r * s))

        # rain
        for x, y, _ in self.drops:
            pygame.draw.line(surf, (170, 200, 255), (x, y), (x + 2, y - 12), 2)

        # snow
        for x, y, _, _ in self.flakes:
            pygame.draw.circle(surf, (255, 255, 255), (int(x), int(y)), 2)

        # fog
        if self.fog:
            for i in range(6):
                x = -100 + math.sin(self.t * 0.3 + i) * 80
                surf.blit(self.fog_band, (x, 40 + i * 50))

        # lightning
        if self.flash > 0:
            self.white.set_alpha(int(self.flash / 0.3 * 180))
            surf.blit(self.white, (0, 0))


# ---------- drawing helpers ----------

def draw_text(surf, font, text, pos, color=(255, 255, 255), center=False):
    img = font.render(text, True, color)
    shadow = font.render(text, True, (0, 0, 0))
    x, y = pos
    if center:
        x -= img.get_width() // 2
    surf.blit(shadow, (x + 2, y + 2))
    surf.blit(img, (x, y))


def draw_arrow(surf, center, from_deg, size=9, color=(255, 255, 255)):
    # Wind "from" direction, so the arrow points the way the wind blows
    a = math.radians(from_deg + 180)
    dx, dy = math.sin(a), -math.cos(a)
    px, py = -dy, dx
    cx, cy = center
    tip = (cx + dx * size, cy + dy * size)
    tail = (cx - dx * size, cy - dy * size)
    pygame.draw.line(surf, color, tail, tip, 2)
    head = [tip,
            (tip[0] - dx * 6 + px * 4, tip[1] - dy * 6 + py * 4),
            (tip[0] - dx * 6 - px * 4, tip[1] - dy * 6 - py * 4)]
    pygame.draw.polygon(surf, color, head)


def draw_forecast(canvas, series, i0, small, mid, panel):
    canvas.blit(panel, (0, PANEL_Y))
    for i in range(COLS):
        group = series[i0 + 1 + i * STEP:i0 + 1 + (i + 1) * STEP]
        if not group:
            break
        first = group[0]
        det = first["data"]["instant"]["details"]
        t = parse_time(first["time"]).astimezone(TZ)
        mm = sum(rain(e) for e in group)
        cx = 10 + i * COL_W + COL_W // 2

        # time and temperature
        draw_text(canvas, small, f"{t:%H:%M}", (cx, PANEL_Y + 8), center=True)
        draw_text(canvas, mid, f"{det['air_temperature']:.0f}°", (cx, PANEL_Y + 30), center=True)

        # precipitation bar (full height = 2.5 mm or more)
        bar = min(30, mm * 12)
        if mm > 0:
            bar = max(2, bar)
            pygame.draw.rect(canvas, (90, 170, 255), (cx - 12, PANEL_Y + 95 - bar, 24, bar))
            draw_text(canvas, small, fmt(mm), (cx, PANEL_Y + 99), color=(170, 210, 255), center=True)
        pygame.draw.line(canvas, (120, 140, 170), (cx - 14, PANEL_Y + 95), (cx + 14, PANEL_Y + 95), 1)

        # wind arrow and speed
        draw_arrow(canvas, (cx - 12, PANEL_Y + 138), det["wind_from_direction"])
        draw_text(canvas, small, f"{det['wind_speed']:.0f}", (cx + 2, PANEL_Y + 129))

# ---------- monitor on/off (HDMI-CEC) ----------

CEC = ["cec-ctl", "-d", "/dev/cec0"]


def cec(*args):
    try:
        subprocess.run(CEC + list(args), stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10)
    except Exception as e:
        print(f"CEC command failed: {e}")


def monitor_on():
    cec("--playback")                     # needed after every reboot/power cut
    cec("--to", "0", "--text-view-on")


def monitor_off():
    cec("--to", "0", "--standby")



# ---------- main loop ----------

def main():
    threading.Thread(target=fetch_loop, daemon=True).start()

    pygame.init()
    screen = Screen()
    canvas = screen.canvas(W, H)
    clock = pygame.time.Clock()

    big = pygame.font.Font(None, 120)
    mid = pygame.font.Font(None, 36)
    small = pygame.font.Font(None, 26)

    panel = pygame.Surface((W, H - PANEL_Y), pygame.SRCALPHA)
    panel.fill((0, 0, 0, 110))

    scene = Scene()
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    monitor_on()

    try:
        while True:
            dt = clock.tick(FPS) / 1000

            series = weather["series"]
            now = current_entry(series) if series else None
            code = FORCE or (symbol(now) if now else "cloudy")
            scene.set_code(code)

            scene.update(dt)
            scene.draw(canvas)

            n = datetime.now(TZ)
            draw_text(canvas, small,
                      f"{WEEKDAYS[n.weekday()]} {n.day}. {MONTHS[n.month - 1]}   {n:%H:%M}",
                      (36, 12))

            if now:
                d = now["data"]["instant"]["details"]
                draw_text(canvas, big, f"{d['air_temperature']:.0f}°", (30, 35))
                draw_text(canvas, mid, label(code), (36, 122))
                draw_text(canvas, small,
                          f"Vind {d['wind_speed']:.0f} m/s fra {wind_name(d['wind_from_direction'])}"
                          f"   Nedbør {fmt(rain(now))} mm",
                          (36, 158))
                draw_forecast(canvas, series, series.index(now), small, mid, panel)
            elif weather["error"]:
                draw_text(canvas, mid, "Feil: " + weather["error"], (36, 60))
            else:
                draw_text(canvas, mid, "Henter værdata...", (36, 60))

            screen.show(canvas)
    except KeyboardInterrupt:
        pass
    finally:
        screen.clear()
        monitor_off()
        print("\nStopped. Monitor in standby.")

if __name__ == "__main__":
    main()
