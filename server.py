from __future__ import annotations

import hmac
import os
import time

import cv2
from flask import Flask, Response, abort, jsonify, request

from camera import CameraManager
from capture import CaptureController


def create_app(camera: CameraManager, capture: CaptureController,
               preview_width=640, preview_fps=10, jpeg_quality=65):
    app = Flask(__name__)
    api_token = os.environ.get("PI_CAMERA_TOKEN", "")

    def require_token():
        # Set PI_CAMERA_TOKEN to protect remote control on network interfaces.
        if api_token and not hmac.compare_digest(
            request.headers.get("X-API-Token", ""), api_token
        ):
            abort(401)

    @app.get("/video")
    def video():
        def frames():
            interval = 1.0 / preview_fps
            while True:
                start = time.monotonic()
                frame = camera.latest_frame()
                if frame is not None:
                    height, width = frame.image.shape[:2]
                    preview_height = max(1, round(height * preview_width / width))
                    resized = cv2.resize(frame.image, (preview_width, preview_height), interpolation=cv2.INTER_AREA)
                    ok, encoded = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
                    if ok:
                        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + encoded.tobytes() + b"\r\n")
                time.sleep(max(0, interval - (time.monotonic() - start)))
        return Response(frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.get("/status")
    def status():
        return jsonify({"camera": camera.status(), "capture": capture.status()})

    @app.post("/config")
    def config():
        require_token()
        data = request.get_json(silent=True) or {}
        try:
            return jsonify(capture.configure(
                mode=data.get("mode"),
                bed_delay_s=data.get("bed_delay_s"),
                fill_level_delay_s=data.get("fill_level_delay_s"),
            ))
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/snapshot")
    def snapshot():
        require_token()
        data = request.get_json(silent=True) or {}
        try:
            request_id = capture.manual_snapshot(mode=data.get("mode"))
            return jsonify({"queued": True, "request_id": request_id}), 202
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    return app
