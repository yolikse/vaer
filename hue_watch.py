#!/usr/bin/env python3
import json
import ssl
import subprocess
import time
import urllib.request

import os
with open(os.path.expanduser("~/weather/hue_config.json")) as f:
    _cfg = json.load(f)
BRIDGE = _cfg["bridge"]
KEY = _cfg["key"]
ROOM = _cfg["room"]

POLL = 2                    # seconds between checks

URL = f"https://{BRIDGE}/api/{KEY}/groups/{ROOM}"
CTX = ssl._create_unverified_context()   # the bridge uses a self-signed certificate

START = "nohup python3 ~/weather/weather_anim.py > /dev/null 2>&1 &"
STOP = "pkill -f weather_anim.py"


def lights_on():
    with urllib.request.urlopen(URL, context=CTX, timeout=5) as r:
        return json.load(r)["state"]["any_on"]


def display_running():
    return subprocess.run(["pgrep", "-f", "weather_anim.py"],
                          stdout=subprocess.DEVNULL).returncode == 0


def main():
    last = None
    print("Watching Hue lights. Ctrl+C to stop.")
    while True:
        try:
            on = lights_on()
        except Exception as e:
            print(f"Could not reach the Hue bridge: {e}")
            time.sleep(10)
            continue

        if on != last:
            if on and not display_running():
                print("Lights on -> starting weather display")
                subprocess.run(START, shell=True)
            elif not on and display_running():
                print("Lights off -> stopping weather display")
                subprocess.run(STOP, shell=True)
            last = on

        time.sleep(POLL)


if __name__ == "__main__":
    main()
