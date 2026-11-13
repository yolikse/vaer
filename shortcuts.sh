# Shortcuts for the weather display. Loaded from ~/.bashrc on the Pi.
WEATHER_DIR="$HOME/weather"

# Start the display (if not already running)
skjerm-paa() {
    if ! pgrep -f weather_anim.py > /dev/null; then
        nohup python3 "$WEATHER_DIR/weather_anim.py" > /dev/null 2>&1 &
    fi
}

# Stop the display and put the monitor in standby
skjerm-av() {
    pkill -f weather_anim.py || cec-ctl -d /dev/cec0 --to 0 --standby > /dev/null
}

# Show a test scene without restarting. "skjerm-test" alone = real weather
skjerm-test() {
    echo "$1" > "$WEATHER_DIR/scene.txt"
    skjerm-paa
}

# Get the newest code from git and restart the display
skjerm-oppdater() {
    git -C "$WEATHER_DIR" pull && skjerm-av && sleep 2 && skjerm-paa
}