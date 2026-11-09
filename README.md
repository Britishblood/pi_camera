# pi_camera – Raspberry Pi Camera Service

A FastAPI-based camera controller for Raspberry Pi, providing continuous camera acquisition, a low-resolution MJPEG live stream, and full-resolution TIFF snapshots triggered by GPIO or HTTP requests.

The application supports two configurable capture modes (`bed` and `fill_level`), each with an independent trigger delay. A WebSocket provides real-time status updates for integration with an external dashboard.

The camera is accessed by a single OpenCV capture process, allowing live streaming and high-resolution snapshots to operate simultaneously.

## 1. Project Structure

| File | Description |
|---|---|
| `main.py` | Command-line arguments, application initialization, and Uvicorn startup |
| `camera.py` | Continuous OpenCV frame acquisition and camera management |
| `capture.py` | Capture scheduling, GPIO cooldown, capture delays, and TIFF image storage |
| `server.py` | FastAPI endpoints, MJPEG streaming, and WebSocket status updates |
| `requirements.txt` | Python dependencies |
| `setup.sh` | Automated installation of dependencies, virtual environment, and systemd service |
| `camera-api.service` | systemd configuration for background operation |

## 2. Installation

### Prerequisites

- Raspberry Pi running Raspberry Pi OS
- Python 3 and Git
- USB/UVC-compatible camera
- Internet connection during initial installation
- GPIO-connected trigger button (optional)

The application uses OpenCV, NumPy, GPIO Zero, FastAPI, Uvicorn, and tifffile.

### Automatic Setup

**The entire installation is handled by `setup.sh`. No manual installation of Python packages or systemd services is required.**

Clone the repository:

```bash
cd /home/poim
git clone https://github.com/USERNAME/pi_camera.git
cd pi_camera
```

Execute the setup script:

```bash
bash setup.sh
```

The setup script automatically:

1. Installs the required Raspberry Pi OS system packages.
2. Creates the `.venv` Python environment if it does not already exist.
3. Installs the required Python dependencies from `requirements.txt`.
4. Verifies the Python environment and installed packages.
5. Copies `camera-api.service` into `/etc/systemd/system/`, reloads systemd, and enables and starts the service.

After installation, **the FastAPI server runs automatically in the background and starts again whenever the Raspberry Pi boots.**

The script can be executed again when dependencies or installation settings change.

**Note:** The systemd service is specifically configured for user `poim` and the directory `/home/poim/pi_camera`. These paths are intentionally hardcoded in `camera-api.service`.

### Verify Installation

Check whether the service is running:

```bash
sudo systemctl status camera-api.service
```

Test the FastAPI server:

```bash
curl http://localhost:8000/status
```

A successful response indicates that the API is available.

By default, the API starts without activating the camera. The camera starts when a `POST /start` request is received.

## 3. Application Startup

### Automatic Startup

The recommended way to run the application is through the systemd service installed by `setup.sh`.

The service starts the application automatically during system boot and keeps the API available in the background.

The camera itself remains inactive until it is started through the API, unless automatic camera startup has been configured.

### Manual Startup

For development and troubleshooting, the application can also be started manually:

```bash
cd /home/poim/pi_camera

.venv/bin/python main.py \
    --port 8000 \
    --width 1920 \
    --height 1080 \
    --fps 30 \
    --preview-width 640 \
    --preview-fps 15
```

Available options include:

| Argument | Description |
|---|---|
| `--port` | FastAPI server port |
| `--width` | Full-resolution camera width |
| `--height` | Full-resolution camera height |
| `--fps` | Requested camera acquisition FPS |
| `--preview-width` | Width of the transmitted MJPEG stream |
| `--preview-fps` | Maximum preview transmission FPS |
| `--bed-delay` | Delay for bed captures, in seconds |
| `--fill-delay` | Delay for fill-level captures, in seconds |
| `--autostart` | Automatically start the camera with the API |
| `--no-gpio` | Disable GPIO functionality for development |

**Important:** Stop the systemd service before starting the application manually to avoid port conflicts and simultaneous camera access.

```bash
sudo systemctl stop camera-api.service
```

Do not run multiple Uvicorn workers or use `--reload` for normal camera operation.

## 4. FastAPI Interface

The FastAPI server provides HTTP and WebSocket endpoints for controlling the application.

Default port: **8000**

### Available Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/start` | POST | Start camera acquisition and GPIO monitoring |
| `/stop` | POST | Stop camera acquisition and GPIO monitoring while keeping FastAPI running |
| `/status` | GET | Return camera status, stream availability, capture settings, and PID |
| `/ws/status` | WebSocket | Send status updates to connected clients |
| `/video` | GET | Provide the low-resolution MJPEG stream |
| `/config` | POST | Change the active capture mode and delays during operation |
| `/snapshot` | POST | Queue an immediate full-resolution TIFF snapshot |
| `/docs` | GET | FastAPI interactive API documentation |

### API Examples

Start the camera:

```bash
curl -X POST http://localhost:8000/start
```

Check the status:

```bash
curl http://localhost:8000/status
```

Change the active mode and capture delays:

```bash
curl -X POST http://localhost:8000/config \
    -H "Content-Type: application/json" \
    -d '{"mode":"fill_level","bed_delay_s":2,"fill_level_delay_s":8}'
```

Take a manual snapshot:

```bash
curl -X POST http://localhost:8000/snapshot \
    -H "Content-Type: application/json" \
    -d '{}'
```

Stop camera acquisition:

```bash
curl -X POST http://localhost:8000/stop
```

The API remains accessible after stopping the camera.

Configuration changes are applied during runtime but are not currently saved permanently. Restarting the application restores the startup defaults.

## 5. Camera Operation

### Continuous Camera Acquisition

A single OpenCV camera instance continuously acquires frames at the configured resolution and frame rate.

The application uses these frames for two independent purposes:

- **Live streaming:** Frames are resized and transmitted at the configured preview resolution and FPS.
- **Snapshots:** Full-resolution frames are selected following a trigger and saved as TIFF files.

The camera is not reopened when a snapshot is requested.

### Live Stream

The default streaming configuration is:

| Parameter | Value |
|---|---|
| Camera resolution | 1920 × 1080 |
| Camera FPS | 30 |
| Preview width | 640 pixels |
| Preview FPS | 15 |
| Stream format | HTTP MJPEG |

The camera acquisition rate and preview transmission rate are independent.

The transmitted stream resolution remains low even when a higher-resolution camera is installed.

The actual camera frame rate depends on the connected camera, USB adapter, and Raspberry Pi performance.

### Triggered Snapshots

The application supports two independent capture modes:

| Mode | Purpose | Configurable Delay |
|---|---|---|
| `bed` | Capture the printing bed after binder deposition | `bed_delay_s` |
| `fill_level` | Capture the powder fill level | `fill_level_delay_s` |

Only one capture mode is active at a time.

When GPIO 27 is triggered:

1. The current capture mode is identified.
2. Its configured delay is applied.
3. A full-resolution frame is selected after the delay.
4. The frame is queued for storage.
5. The image is saved in the corresponding directory.

### GPIO Cooldown

Repeated GPIO triggers are ignored for a configurable cooldown period.

The cooldown duration is calculated dynamically:

```python
cooldown = max(
    10.0,
    bed_delay_s,
    fill_level_delay_s
)
```

The cooldown begins with the accepted button press and prevents additional GPIO-triggered capture schedules during that period.

Manual snapshots requested through the API are independent of this cooldown.

Changing the active mode or delays does not modify an already scheduled capture.

## 6. Image Storage

Images are currently saved locally on the Raspberry Pi:

```text
images/
├── bed/
│   └── bed_YYYYMMDD_HHMMSS_ffffff.tif
└── fill_level/
    └── fill_level_YYYYMMDD_HHMMSS_ffffff.tif
```

Images are stored at the full resolution of the received camera frames.

The current implementation uses uncompressed RGB TIFF files through `tifffile`.

**Image quality:** TIFF storage is lossless from the decoded OpenCV frame onward. However, MJPEG input from a USB/UVC camera may already contain lossy compression.

Future development will include lossless TIFF compression and automatic transfer to an external Windows computer to minimize storage requirements on the Raspberry Pi.

## 7. Dashboard Integration

The camera service is designed to communicate with an external dashboard through Nginx.

The FastAPI server runs on the Raspberry Pi at port `8000`.

The dashboard uses the following proxy routes:

| Dashboard URL | Raspberry Pi Endpoint |
|---|---|
| `/camera-api/start` | `POST /start` |
| `/camera-api/stop` | `POST /stop` |
| `/camera-api/status` | `GET /status` |
| `/camera-api/ws/status` | `WS /ws/status` |
| `/camera-api/video` | `GET /video` |
| `/camera-stream/` | `GET /video` |

The `/camera-stream/` location is maintained for compatibility with the existing dashboard.

### Nginx Configuration

Example API reverse proxy:

```nginx
location /camera-api/ {
    proxy_pass http://PI_IP:8000/;

    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_buffering off;
    proxy_read_timeout 3600s;
}
```

The WebSocket configuration assumes that `$connection_upgrade` is defined in the Nginx HTTP context.

Example stream reverse proxy:

```nginx
location /camera-stream/ {
    proxy_pass http://PI_IP:8000/video;

    proxy_http_version 1.1;
    proxy_set_header Host $host;

    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
}
```

Replace `PI_IP` with the Raspberry Pi's actual network address.

### Frontend Integration

The MJPEG stream can be displayed directly in React:

```tsx
<img
    src="/camera-stream/"
    alt="Raspberry Pi Camera"
/>
```

The WebSocket is used exclusively for camera status updates, not for transferring video frames.

```javascript
const protocol = window.location.protocol === "https:"
    ? "wss:"
    : "ws:";

const ws = new WebSocket(
    `${protocol}//${window.location.host}/camera-api/ws/status`
);
```

## 8. systemd Service – Reference

**The systemd service is installed automatically by `bash setup.sh`.**

The following information is provided for reference, troubleshooting, and manual maintenance. These steps are **not required during a normal installation**.

### Service Configuration

The file `camera-api.service` defines how the application runs in the background.

| Setting | Description |
|---|---|
| `Description` | Name displayed by systemd |
| `After=network.target` | Starts after basic network initialization |
| `Type=simple` | Runs the application as a foreground process managed by systemd |
| `User=poim` | Linux user executing the application |
| `WorkingDirectory` | Directory from which the application is executed |
| `ExecStart` | Starts the application using its virtual environment |
| `Restart=on-failure` | Automatically restarts the application after a failure |
| `RestartSec=5` | Waits 5 seconds before restarting |
| `WantedBy=multi-user.target` | Enables automatic startup during system boot |

The service configuration uses fixed paths:

```ini
[Unit]
Description=Raspberry Pi Camera API
After=network.target

[Service]
Type=simple
User=poim
WorkingDirectory=/home/poim/pi_camera
ExecStart=/home/poim/pi_camera/.venv/bin/python /home/poim/pi_camera/main.py --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

The installed service starts FastAPI but does not automatically activate camera acquisition.

### Manual Service Installation

These commands are already executed by `setup.sh` and are only needed when manually reinstalling or updating the service configuration.

```bash
sudo cp camera-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now camera-api.service
```

### Useful Commands

| Command | Description |
|---|---|
| `sudo systemctl start camera-api` | Start the service |
| `sudo systemctl stop camera-api` | Stop the service |
| `sudo systemctl restart camera-api` | Restart the service |
| `sudo systemctl status camera-api` | Display the current service status |
| `sudo systemctl enable camera-api` | Enable automatic startup |
| `sudo systemctl disable camera-api` | Disable automatic startup |
| `sudo journalctl -u camera-api -f` | Follow service logs in real time |
| `sudo journalctl -u camera-api -n 50` | Display the last 50 log entries |
| `sudo systemctl cat camera-api` | Display the installed service configuration |

### Updating the Application

After updating the repository on the development computer and pushing the changes to GitHub:

```bash
cd /home/poim/pi_camera
git pull
sudo systemctl restart camera-api.service
```

If Python dependencies have changed, execute:

```bash
bash setup.sh
```

This updates the installation using the existing setup process.

### Updating the Service Configuration

When `camera-api.service` has been modified, the updated file must be copied to systemd:

```bash
sudo cp camera-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart camera-api.service
```

Alternatively, run `bash setup.sh` again to reinstall the service and dependencies.

## 9. Troubleshooting

### Service Does Not Start

Check the status and logs:

```bash
sudo systemctl status camera-api.service
sudo journalctl -u camera-api.service -n 50 --no-pager
```

### Camera Stream Returns HTTP 503

This usually indicates that the camera has not been started or that no video frames are available.

Check the camera status:

```bash
curl http://localhost:8000/status
```

Start the camera:

```bash
curl -X POST http://localhost:8000/start
```

### Dashboard Returns HTTP 502

Check that Nginx forwards requests to the correct Raspberry Pi IP address and port `8000`.

Test the camera API directly:

```bash
curl http://localhost:8000/status
```

If the direct API works but the dashboard does not, check the Nginx proxy configuration.

### Camera Cannot Be Opened

Check whether another process is already using the camera:

```bash
sudo fuser -v /dev/video0
```

Make sure no previous camera scripts are running simultaneously.

## 10. Planned Improvements

- Automatic image transfer to a Windows computer
- Lossless TIFF compression
- PySide6 desktop application for configuration and monitoring
- Persistent configuration of capture settings
- Camera resolution and FPS configuration from the GUI
- Improved camera timing diagnostics and logging
- Integration with printer machine-status signals

---

**Note:** The project is intended to run within a trusted local network. Authentication and restricted network access should be implemented before exposing control endpoints through a VPN or other externally accessible network.