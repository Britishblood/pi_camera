"""Single owner of the UVC camera; capture frames continuously."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import threading
import time

import cv2
import numpy as np


@dataclass(frozen=True)
class Frame:
    image: np.ndarray
    monotonic_time: float
    captured_at: datetime
    sequence: int


class CameraManager:
    def __init__(self, device=0, width=1920, height=1080, fps=30):
        self.device = device
        self.width = width
        self.height = height
        self.target_fps = fps
        self._camera = None
        self._condition = threading.Condition()
        self._latest: Frame | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_error = None
        self._fps = 0.0

    def start(self):
        # OpenCV's MJPG setting is the *camera input format*, not the streaming format.
        self._camera = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        if not self._camera.isOpened():
            raise RuntimeError(f"Cannot open camera device {self.device}")

        self._camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self._camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._camera.set(cv2.CAP_PROP_FPS, self.target_fps)

        print(
            "Camera initialized:",
            int(self._camera.get(cv2.CAP_PROP_FRAME_WIDTH)), "x",
            int(self._camera.get(cv2.CAP_PROP_FRAME_HEIGHT)), "at requested",
            self.target_fps, "FPS", flush=True,
        )
        with self._condition:
            self._running = True
        self._thread = threading.Thread(target=self._capture_loop, name="camera", daemon=True)
        self._thread.start()

        if self.wait_for_frame_after(0, timeout=10) is None:
            self.stop()
            raise RuntimeError("Camera opened, but no frames arrived within 10 seconds")

    def _capture_loop(self):
        previous_time = None
        while True:
            with self._condition:
                if not self._running:
                    break

            ok, image = self._camera.read()
            now = time.monotonic()
            if not ok:
                with self._condition:
                    self._last_error = "Camera read failed"
                time.sleep(0.05)
                continue

            if previous_time is not None:
                interval = now - previous_time
                if interval > 0:
                    instant_fps = 1 / interval
                    self._fps = instant_fps if self._fps == 0 else 0.9 * self._fps + 0.1 * instant_fps
            previous_time = now

            with self._condition:
                next_sequence = 1 if self._latest is None else self._latest.sequence + 1
                self._latest = Frame(image, now, datetime.now(), next_sequence)
                self._last_error = None
                self._condition.notify_all()

    def latest_frame(self) -> Frame | None:
        with self._condition:
            frame = self._latest
            if frame is None:
                return None
            # Caller can freely resize/encode without modifying the shared frame.
            return Frame(frame.image.copy(), frame.monotonic_time, frame.captured_at, frame.sequence)

    def wait_for_frame_after(self, instant: float, timeout=5) -> Frame | None:
        """Get a frame received after an event time; never return an older buffered frame."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._running:
                if self._latest is not None and self._latest.monotonic_time >= instant:
                    f = self._latest
                    return Frame(f.image.copy(), f.monotonic_time, f.captured_at, f.sequence)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
        return None

    def status(self):
        with self._condition:
            latest = self._latest
            return {
                "running": self._running,
                "frame_shape": list(latest.image.shape) if latest else None,
                "frame_sequence": latest.sequence if latest else None,
                "fps_estimate": round(self._fps, 1),
                "last_error": self._last_error,
            }

    def stop(self):
        with self._condition:
            self._running = False
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=3)
        if self._camera is not None:
            self._camera.release()
