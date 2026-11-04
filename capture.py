from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import heapq
from pathlib import Path
from queue import Queue, Full
import threading
import time
import uuid

import cv2
import tifffile

from camera import CameraManager, Frame


@dataclass(frozen=True)
class CaptureRequest:
    mode: str
    due_at: float
    triggered_at: datetime
    request_id: str


class CaptureController:
    MODES = ("bed", "fill_level")

    def __init__(self, camera: CameraManager, output_dir: Path,
                 bed_delay_s=2.0, fill_level_delay_s=5.0, cooldown_s=10.0):
        self.camera = camera
        self.output_dir = Path(output_dir)
        self.delays = {"bed": float(bed_delay_s), "fill_level": float(fill_level_delay_s)}
        self.mode = "bed"
        self._gpio_blocked_until = float("-inf")
        self._pending = []
        self._serial = 0
        self._condition = threading.Condition()
        self._save_queue = Queue(maxsize=8)
        self._stop = False
        self.saved_count = 0
        self.last_saved_file = None
        self.last_error = None
        self._scheduler = threading.Thread(target=self._schedule_loop, name="scheduler", daemon=True)
        self._writer = threading.Thread(target=self._save_loop, name="image-writer", daemon=True)

    def start(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._scheduler.start()
        self._writer.start()

    def configure(self, mode=None, bed_delay_s=None, fill_level_delay_s=None):
        # Validate before changing any state.
        if mode is not None and mode not in self.MODES:
            raise ValueError(f"mode must be one of {self.MODES}")
        for delay in (bed_delay_s, fill_level_delay_s):
            if delay is not None and not (0 <= float(delay) <= 3600):
                raise ValueError("delay must be between 0 and 3600 seconds")
        with self._condition:
            if mode is not None:
                self.mode = mode
            if bed_delay_s is not None:
                self.delays["bed"] = float(bed_delay_s)
            if fill_level_delay_s is not None:
                self.delays["fill_level"] = float(fill_level_delay_s)
        return self.status()

    def button_pressed(self):
        """GPIO callback: schedule a capture with dynamic cooldown."""

        with self._condition:
            now = time.monotonic()
            if now < self._gpio_blocked_until:
                print("GPIO ignored: cooldown active", flush=True)
                return False
            mode = self.mode
            delay = self.delays[mode]
            # Minimum 10 seconds, otherwise longest configured delay
            cooldown = max(10.0, self.delays["bed"], self.delays["fill_level"])
            self._gpio_blocked_until = now + cooldown
            self._enqueue_locked(mode, now + delay)
        print(f"GPIO: scheduled {mode} in {delay:.2f} s (cooldown: {cooldown:.2f} s)", flush=True)
        return True

    def manual_snapshot(self, mode=None):
        """Manual snapshots are immediate and do not consume the GPIO cooldown."""
        with self._condition:
            chosen_mode = mode or self.mode
            if chosen_mode not in self.MODES:
                raise ValueError(f"mode must be one of {self.MODES}")
            request = self._enqueue_locked(chosen_mode, time.monotonic())
        return request.request_id

    def _enqueue_locked(self, mode, due_at):
        self._serial += 1
        request = CaptureRequest(mode, due_at, datetime.now(), uuid.uuid4().hex[:8])
        heapq.heappush(self._pending, (due_at, self._serial, request))
        self._condition.notify_all()
        return request

    def _schedule_loop(self):
        while True:
            with self._condition:
                while not self._stop and not self._pending:
                    self._condition.wait()
                if self._stop:
                    return
                due_at, _, request = self._pending[0]
                remaining = due_at - time.monotonic()
                if remaining > 0:
                    self._condition.wait(timeout=remaining)
                    continue
                heapq.heappop(self._pending)

            frame = self.camera.wait_for_frame_after(request.due_at, timeout=5)
            if frame is None:
                self._report_error(f"No camera frame for trigger {request.request_id}")
                continue
            try:
                self._save_queue.put_nowait((request, frame))
            except Full:
                self._report_error(f"Save queue full: snapshot {request.request_id} NOT saved")

    def _save_loop(self):
        while True:
            item = self._save_queue.get()
            try:
                if item is None:
                    return
                request, frame = item
                self._save_frame(request, frame)
            except Exception as exc:
                self._report_error(f"Image save failed: {exc}")
            finally:
                self._save_queue.task_done()

    def _save_frame(self, request: CaptureRequest, frame: Frame):
        folder = self.output_dir / request.mode
        folder.mkdir(parents=True, exist_ok=True)
        filename = f"{request.mode}_{frame.captured_at:%Y%m%d_%H%M%S_%f}_{request.request_id}.tif"
        path = folder / filename
        temp_path = folder / (filename + ".partial")
        rgb = cv2.cvtColor(frame.image, cv2.COLOR_BGR2RGB)
        try:
            with temp_path.open("wb") as f:
                tifffile.imwrite(f, rgb, photometric="rgb", compression=None)
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)
        with self._condition:
            self.saved_count += 1
            self.last_saved_file = str(path)
        print(f"Saved {path}", flush=True)

    def _report_error(self, message):
        with self._condition:
            self.last_error = message
        print(f"ERROR: {message}", flush=True)

    def status(self):
        with self._condition:
            return {
                "mode": self.mode,
                "delays_s": dict(self.delays),
                "cooldown_s": max(10.0, *self.delays.values()),
                "cooldown_remaining_s": round(max(0, self._gpio_blocked_until - time.monotonic()), 2),
                "pending_snapshots": len(self._pending),
                "queued_saves": self._save_queue.qsize(),
                "saved_count": self.saved_count,
                "last_saved_file": self.last_saved_file,
                "last_error": self.last_error,
            }

    def stop(self):
        with self._condition:
            self._stop = True
            self._condition.notify_all()
        self._scheduler.join(timeout=6)
        # Complete any images already queued before shutdown.
        self._save_queue.put(None)
        self._writer.join()
