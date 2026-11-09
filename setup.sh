#!/usr/bin/env bash
set -Eeuo pipefail

# Run from any directory: setup always targets this repository.
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if [[ ! -f requirements.txt ]]; then
  echo "ERROR: requirements.txt not found in $PROJECT_DIR" >&2
  exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "ERROR: This setup requires Raspberry Pi OS / Debian with apt-get." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found." >&2
  exit 1
fi

if [[ $(id -u) -eq 0 ]]; then
  APT=(apt-get)
elif command -v sudo >/dev/null 2>&1; then
  APT=(sudo apt-get)
else
  echo "ERROR: apt packages require sudo/root. Run on Raspberry Pi OS with sudo available." >&2
  exit 1
fi

echo '[1/5] Installing system packages (apt)...'
"${APT[@]}" update
"${APT[@]}" install -y \
  python3-venv python3-pip \
  python3-numpy python3-opencv python3-gpiozero python3-lgpio

echo '[2/5] Creating virtual environment...'
if [[ ! -d .venv ]]; then
  python3 -m venv --system-site-packages .venv
elif [[ ! -x .venv/bin/python ]]; then
  echo 'ERROR: .venv exists but has no executable Python. Rename/delete .venv and rerun.' >&2
  exit 1
else
  if ! grep -Eq '^include-system-site-packages = true$' .venv/pyvenv.cfg; then
    echo 'ERROR: Existing .venv lacks system-site-packages.' >&2
    echo 'Rename/delete .venv and rerun setup.sh to recreate it.' >&2
    exit 1
  fi
  echo 'Using existing .venv.'
fi

echo '[3/5] Installing project pip requirements...'
.venv/bin/python -m pip install -r requirements.txt

echo '[4/5] Checking imports...'
.venv/bin/python - <<'PY'
import cv2
import numpy
import gpiozero
import flask
import tifffile
print('OK: cv2, numpy, gpiozero, flask, tifffile import successfully')
print('OpenCV:', cv2.__version__)
PY

echo '[5/5] Installing the service camera-api.service...'
sudo cp camera-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now camera-api.service
echo 'Waiting for service to initialize...'

for i in {1..10}; do
    if curl -fsS http://localhost:8000/status > /dev/null; then
        echo 'FastAPI is ready!'
        break
    fi
    sleep 1
done

sudo systemctl status camera-api.service --no-pager

echo
echo 'Setup complete.'
