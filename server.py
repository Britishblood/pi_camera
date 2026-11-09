"""FastAPI controller for a single UVC camera, MJPEG preview and status WebSocket."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hmac
import os
from pathlib import Path
import threading
import time

import cv2
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from camera import CameraManager
from capture import CaptureController


class ConfigUpdate(BaseModel):
    mode: str | None = None
    bed_delay_s: float | None = Field(default=None, ge=0, le=3600)
    fill_level_delay_s: float | None = Field(default=None, ge=0, le=3600)


class SnapshotRequest(BaseModel):
    mode: str | None = None


class CameraService:
    """Own camera/GPIO/capture lifecycle; only one instance may access the camera."""

    def __init__(self, *, device, width, height, fps, output_dir, bed_delay, fill_delay, no_gpio):
        self.options = dict(device=device, width=width, height=height, fps=fps)
        self.output_dir = Path(output_dir)
        self.no_gpio = no_gpio
        self.delays = dict(bed=bed_delay, fill_level=fill_delay)
        self.mode = "bed"
        self.lock = threading.RLock()
        self.camera: CameraManager | None = None
        self.capture: CaptureController | None = None
        self.button = None

    def start(self):
        with self.lock:
            if self.camera is not None:
                return {"status": "already_running", **self.status()}
            camera = CameraManager(**self.options)
            capture = CaptureController(camera, self.output_dir, self.delays["bed"], self.delays["fill_level"])
            button = None
            try:
                camera.start()
                capture.start()
                capture.configure(mode=self.mode)
                if not self.no_gpio:
                    from gpiozero import Button
                    button = Button(27, pull_up=False, bounce_time=0.05)
                    button.when_pressed = capture.button_pressed
                self.camera, self.capture, self.button = camera, capture, button
            except Exception:
                if button is not None:
                    button.close()
                # stop() is only safe after capture.start() succeeded.
                if capture._scheduler.is_alive():
                    capture.stop()
                camera.stop()
                raise
            return {"status": "started", **self.status()}

    def stop(self):
        with self.lock:
            if self.camera is None:
                return {"status": "already_stopped"}
            if self.button is not None:
                self.button.close()
                self.button = None
            if self.capture is not None:
                previous = self.capture.status()
                self.mode = previous["mode"]
                self.delays = previous["delays_s"]
                self.capture.stop()
                self.capture = None
            self.camera.stop()
            self.camera = None
            return {"status": "stopped"}

    def status(self):
        with self.lock:
            camera = self.camera
            capture = self.capture
            camera_status = camera.status() if camera else None
            capture_status = capture.status() if capture else None
            stream_ready = bool(camera_status and camera_status["frame_sequence"] is not None)
            return {
                "ready": True,
                "running": camera is not None,
                "stream_ready": stream_ready,
                "pid": os.getpid() if camera else None,
                "camera": camera_status,
                "capture": capture_status,
                "configured": {"mode": self.mode, "delays_s": dict(self.delays)} if not capture_status else None,
            }

    def configure(self, update: ConfigUpdate):
        with self.lock:
            if self.capture:
                return self.capture.configure(**update.model_dump(exclude_none=True))
            if update.mode is not None:
                if update.mode not in CaptureController.MODES:
                    raise ValueError("invalid mode")
                self.mode = update.mode
            if update.bed_delay_s is not None:
                self.delays["bed"] = update.bed_delay_s
            if update.fill_level_delay_s is not None:
                self.delays["fill_level"] = update.fill_level_delay_s
            return {"mode": self.mode, "delays_s": dict(self.delays)}

    def snapshot(self, mode: str | None):
        with self.lock:
            if self.capture is None:
                raise RuntimeError("Camera is stopped")
            return self.capture.manual_snapshot(mode=mode)

    def trigger(self):
        """Simulate a GPIO button press."""
        with self.lock:
            if self.capture is None:
                raise RuntimeError("Camera is stopped")

            return self.capture.button_pressed()


def create_app(service: CameraService, *, preview_width=640, preview_fps=5, jpeg_quality=65, autostart=False):
    token = os.environ.get("PI_CAMERA_TOKEN", "")
    if preview_width <= 0 or preview_fps <= 0 or not 1 <= jpeg_quality <= 100:
        raise ValueError("Invalid preview parameters")

    def authenticate(value: str | None):
        if token and not hmac.compare_digest(value or "", token):
            raise HTTPException(status_code=401, detail="Invalid API token")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if autostart:
            await asyncio.to_thread(service.start)
        try:
            yield
        finally:
            await asyncio.to_thread(service.stop)

    app = FastAPI(title="Pi Camera", lifespan=lifespan)

    @app.post("/start")
    async def start(x_api_token: str | None = Header(default=None)):
        authenticate(x_api_token)
        try:
            return await asyncio.to_thread(service.start)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/stop")
    async def stop(x_api_token: str | None = Header(default=None)):
        authenticate(x_api_token)
        return await asyncio.to_thread(service.stop)

    @app.get("/status")
    def status():
        return service.status()

    @app.post("/config")
    def config(update: ConfigUpdate, x_api_token: str | None = Header(default=None)):
        authenticate(x_api_token)
        try:
            return service.configure(update)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/snapshot", status_code=202)
    def snapshot(payload: SnapshotRequest, x_api_token: str | None = Header(default=None)):
        authenticate(x_api_token)
        try:
            return {"queued": True, "request_id": service.snapshot(payload.mode)}
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/trigger", status_code=202)
    def trigger(x_api_token: str | None = Header(default=None)):
        authenticate(x_api_token)

        try:
            accepted = service.trigger()

            return {
                "accepted": accepted,
                "status": "scheduled" if accepted else "cooldown_active"
            }

        except RuntimeError as exc:
            raise HTTPException(
                status_code=409,
                detail=str(exc)
            ) from exc

    @app.get("/video")
    def video():
        if not service.status()["stream_ready"]:
            raise HTTPException(status_code=503, detail="Camera stream not ready")

        def frames():
            last_sequence = -1
            interval = 1.0 / preview_fps
            while True:
                t0 = time.monotonic()
                with service.lock:
                    camera = service.camera
                if camera is None:
                    break
                frame = camera.latest_frame()
                if frame is not None and frame.sequence != last_sequence:
                    last_sequence = frame.sequence
                    height, width = frame.image.shape[:2]
                    preview_height = max(1, round(height * preview_width / width))
                    small = cv2.resize(frame.image, (preview_width, preview_height), interpolation=cv2.INTER_AREA)
                    ok, jpeg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
                    if ok:
                        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")
                time.sleep(max(0, interval - (time.monotonic() - t0)))

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.websocket("/ws/status")
    async def websocket_status(websocket: WebSocket):
        if token and not hmac.compare_digest(websocket.query_params.get("token", ""), token):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        previous = None
        try:
            while True:
                current = service.status()
                # Exclude fast-changing frame telemetry to avoid 5 messages per second.
                comparable = dict(current)
                if current["camera"]:
                    comparable["camera"] = dict(current["camera"])
                    comparable["camera"].pop("frame_sequence", None)
                    comparable["camera"].pop("fps_estimate", None)
                if current["capture"]:
                    comparable["capture"] = dict(current["capture"])
                    comparable["capture"].pop("cooldown_remaining_s", None)
                if comparable != previous:
                    await websocket.send_json(current)
                    previous = comparable
                await asyncio.sleep(0.2)
        except (WebSocketDisconnect, RuntimeError):
            pass

    return app
