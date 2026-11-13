#!/usr/bin/env python3
import json
import subprocess
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=63.43&lon=10.40"
HEADERS = {"User-Agent": "pilikse-weather/1.0 eskilhsb@gmail.com"}
TZ = ZoneInfo("Europe/Oslo")


def fetch():
    req = urllib.request.Request(URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def local_time(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)


def symbol(entry):
    d = entry["data"]
    for key in ("next_1_hours", "next_6_hours", "next_12_hours"):
        if key in d:
            return d[key]["summary"]["symbol_code"]
    return "?"


def rain(entry):
    d = entry["data"]
    for key in ("next_1_hours", "next_6_hours"):
        if key in d:
            return d[key]["details"].get("precipitation_amount", 0.0)
    return 0.0


def big(text, font="standard"):
    result = subprocess.run(
        ["figlet", "-w", "200", "-f", font, text],
        capture_output=True, text=True,
    )
    return result.stdout


def main():
    series = fetch()["properties"]["timeseries"]

    now = series[0]
    n = now["data"]["instant"]["details"]

    print(big(f"{n['air_temperature']:.1f} C"))
    print(f"  {symbol(now)}   wind {n['wind_speed']} m/s   humidity {n['relative_humidity']:.0f}%")
    print()
    print("  " + "-" * 40)

    for entry in series[1:13]:
        t = local_time(entry["time"])
        d = entry["data"]["instant"]["details"]
        print(f"  {t:%H:%M}  {d['air_temperature']:5.1f}°C  {rain(entry):4.1f} mm  {symbol(entry)}")


if __name__ == "__main__":
    main()
