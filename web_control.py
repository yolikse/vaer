#!/usr/bin/env python3
"""Small web page for controlling the weather display from a phone."""
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

PORT = 8080
DIR = os.path.dirname(os.path.abspath(__file__))
ANIM = os.path.join(DIR, "weather_anim.py")
SCENE_FILE = os.path.join(DIR, "scene.txt")

# Test scenes shown as buttons: weather code -> button text
SCENES = {
    "clearsky_day": "Sol",
    "clearsky_night": "Måne og stjerner",
    "partlycloudy_day": "Delvis skyet",
    "cloudy": "Skyet",
    "fog": "Tåke",
    "rain": "Regn",
    "heavyrain": "Kraftig regn",
    "sleet": "Sludd",
    "heavysnow": "Snø",
    "heavyrainandthunder": "Torden",
}


# ---------- controlling the display ----------

def running():
    return subprocess.run(["pgrep", "-f", "weather_anim.py"],
                          stdout=subprocess.DEVNULL).returncode == 0


def start():
    if not running():
        subprocess.run(f'nohup python3 "{ANIM}" > /dev/null 2>&1 &', shell=True)


def stop():
    if running():
        subprocess.run(["pkill", "-f", "weather_anim.py"])   # script paints black itself
    else:
        subprocess.run("dd if=/dev/zero of=/dev/fb0 2>/dev/null", shell=True)


def standby():
    subprocess.run(["pkill", "-f", "weather_anim.py"])
    subprocess.run(["cec-ctl", "-d", "/dev/cec0", "--to", "0", "--standby"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def set_scene(code):
    with open(SCENE_FILE, "w") as f:
        f.write(code + "\n")
    start()


def current_scene():
    try:
        with open(SCENE_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


# ---------- the web page ----------

PAGE = """<!doctype html>
<html lang="no">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Værskjerm</title>
<style>
  body { font-family: system-ui, sans-serif; background: #10141f; color: #eee;
         margin: 0 auto; padding: 16px; max-width: 480px; }
  h1 { font-size: 1.4em; margin: 8px 0 4px; }
  h2 { font-size: 1em; color: #9ab; margin: 8px 0; }
  #status { color: #9ab; margin-bottom: 16px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 20px; }
  button { font-size: 1.1em; padding: 18px 8px; border: 0; border-radius: 12px;
           background: #24304a; color: #fff; }
  button:active { background: #3a4d75; }
  .on { background: #2e7d4f; }
  .off { background: #7d2e2e; }
</style>
</head>
<body>
<h1>Værskjerm</h1>
<div id="status">Henter status...</div>

<div class="grid">
  <button class="on" onclick="send('/on')">På</button>
  <button class="off" onclick="send('/off')">Av</button>
  <button onclick="send('/scene?code=')">Ekte vær</button>
  <button onclick="send('/standby')">Standby</button>
</div>

<h2>Testscener</h2>
<div class="grid">
__SCENES__
</div>

<script>
async function status() {
  const el = document.getElementById('status');
  try {
    const s = await (await fetch('/status')).json();
    el.textContent = (s.running ? 'Skjermen er på' : 'Skjermen er av')
                   + (s.scene ? ' · testscene: ' + s.scene : '');
  } catch (e) {
    el.textContent = 'Får ikke kontakt med Pi-en';
  }
}
async function send(path) {
  await fetch(path, { method: 'POST' });
  setTimeout(status, 1500);
}
status();
</script>
</body>
</html>
"""

SCENE_BUTTONS = "\n".join(
    '  <button onclick="send(\'/scene?code=%s\')">%s</button>' % (code, name)
    for code, name in SCENES.items()
)
PAGE = PAGE.replace("__SCENES__", SCENE_BUTTONS)


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, body, ctype="text/plain; charset=utf-8"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self.reply(200, PAGE, "text/html; charset=utf-8")
        elif path == "/status":
            body = json.dumps({"running": running(), "scene": current_scene()})
            self.reply(200, body, "application/json")
        else:
            self.reply(404, "Not found")

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/on":
            start()
        elif url.path == "/off":
            stop()
        elif url.path == "/standby":
            standby()
        elif url.path == "/scene":
            code = parse_qs(url.query).get("code", [""])[0]
            if code and code not in SCENES:
                return self.reply(400, "Unknown scene")
            set_scene(code)
        else:
            return self.reply(404, "Not found")
        self.reply(200, "ok")

    def log_message(self, *args):
        pass   # keep the log quiet


if __name__ == "__main__":
    print(f"Web control running on port {PORT}")
    HTTPServer(("", PORT), Handler).serve_forever()