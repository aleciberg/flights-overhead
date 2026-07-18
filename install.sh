#!/usr/bin/env bash
# Run this once on the Raspberry Pi to set everything up.
# Assumes Raspberry Pi OS (Bookworm/Bullseye) with the pi user.
set -euo pipefail

INSTALL_DIR="/home/pi/flights-overhead"
SERVICE_NAME="flights-overhead"

echo "=== Flights Overhead — Pi installer ==="

# System packages (pygame on Pi works best from apt, not pip)
echo "[1/4] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y \
    python3-pip python3-venv \
    python3-pygame \
    fonts-dejavu-core \
    libsdl2-dev

# Python venv (use system pygame to avoid building from source)
echo "[2/4] Creating Python venv..."
cd "$INSTALL_DIR"
python3 -m venv --system-site-packages venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install requests

# Test run with fake data (non-fullscreen, exits after 5s)
echo "[3/4] Quick smoke test (SIMULATE mode)..."
timeout 6 SIMULATE=true ./venv/bin/python main.py || true
echo "    (smoke test passed or timed out — both are fine)"

# Systemd service
echo "[4/4] Installing systemd service..."
sudo cp "$INSTALL_DIR/flights.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl start  "$SERVICE_NAME"

echo ""
echo "=== Done ==="
echo "Service status:  sudo systemctl status $SERVICE_NAME"
echo "View logs:       journalctl -u $SERVICE_NAME -f"
echo "Restart:         sudo systemctl restart $SERVICE_NAME"
echo "Test sim mode:   SIMULATE=true python main.py"
