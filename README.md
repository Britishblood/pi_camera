# pi_camera – FastAPI camera service

A single Raspberry Pi process owns the OpenCV UVC camera. It provides a low-resolution MJPEG preview and full-resolution losslessly written TIFF snapshots. The Pi can be controlled by GPIO 27 or HTTP requests. A WebSocket reports status changes.

## Files

- `main.py`: CLI arguments and Uvicorn startup
- `camera.py`: continuous OpenCV capture thread
- `capture.py`: capture scheduling, independent `bed` and `fill_level` delays, GPIO cooldown, TIFF writer
- `server.py`: FastAPI lifecycle, MJPEG preview and control/status endpoints

## Install

On Raspberry Pi OS, use your existing `setup.sh` if it installs `requirements.txt`. This version needs **FastAPI** and **Uvicorn**, **not Flask**. `cv2`, `numpy`, `gpiozero`, and `tifffile` must also be available in the virtual environment; the earlier `setup.sh` can supply OpenCV/NumPy/GPIO from system packages.

```bash
cd /home/poim/pi_camera
bash setup.sh
```

Or, if `.venv` already exists:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

## Start

Run a single process, without `uvicorn --reload` or multiple workers:

```bash
.venv/bin/python main.py --port 8080 --width 1920 --height 1080 --fps 30 --preview-width 640 --preview-fps 5
```

By default, **the API starts but the camera does not**. Call `POST /start` to begin capture. Add `--autostart` to start the camera automatically with the API. Use `--no-gpio` for development where GPIO isn't available.

If the port is occupied, stop the previous Flask/other camera service first.

## Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/start` | POST | Start camera and GPIO monitoring |
| `/stop` | POST | Stop camera/GPIO, keep API online |
| `/status` | GET | Status JSON, including `running`, `stream_ready`, `pid` |
| `/ws/status` | WebSocket | Push status changes; this is **not** the video stream |
| `/video` | GET | Low-resolution MJPEG HTTP stream; same browser URL as before |
| `/config` | POST | Change mode and delays while running |
| `/snapshot` | POST | Queue an immediate full-resolution TIFF snapshot |
| `/docs` | GET | FastAPI interactive API documentation |

### Linux examples

```bash
curl -X POST http://PI_IP:8080/start
curl http://PI_IP:8080/status
curl -X POST http://PI_IP:8080/config -H 'Content-Type: application/json' -d '{"mode":"fill_level","fill_level_delay_s":8}'
curl -X POST http://PI_IP:8080/snapshot -H 'Content-Type: application/json' -d '{}'
curl -X POST http://PI_IP:8080/stop
```

### Dashboard integration

- Show video via an `<img src="/camera/video">` or another HTTP MJPEG viewer, using your Nginx reverse proxy path.
- Use WebSocket `ws(s)://.../ws/status` for `running` / `stream_ready` state changes.
- Update Nginx's proxy configuration if the old `/camera/` mapping pointed directly to `/video` instead of the new API server root. With `location /camera/ { proxy_pass http://PI_IP:8080/; }`, requests to `/camera/video`, `/camera/status` and `/camera/ws/status` are routed to the corresponding endpoints. WebSocket proxying needs HTTP/1.1 and Upgrade/Connection headers.

## Trigger behavior

GPIO 27 schedules a snapshot using the currently active mode's delay. After an accepted GPIO event, the GPIO button ignores new events for `max(10 seconds, bed_delay_s, fill_level_delay_s)`, computed at that moment. Manual `/snapshot` requests bypass this cooldown. Images are saved under `images/bed/` or `images/fill_level/` as **uncompressed TIFF** with full camera frame resolution. The stream remains reduced to the configured preview width.

The files are lossless *from the decoded OpenCV frames onward*: UVC MJPEG input itself may already have lossy compression.

## Network safety

The service binds to all network interfaces by default (`--host 0.0.0.0`). Set environment variable `PI_CAMERA_TOKEN` to require the `X-API-Token` header for mutating HTTP endpoints. Status and video endpoints are not token protected; restrict them using firewall/VPN or reverse-proxy auth. For the WebSocket, the optional token is read from `?token=...`; use network-level access controls rather than putting sensitive tokens in public URLs. Do not expose the service directly to the internet.

No live hardware validation has been performed. Test UVC camera and GPIO on your Pi before production use.
