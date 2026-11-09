"""Run FastAPI and camera control in one process. Use one Uvicorn worker, no reload."""

import argparse
from pathlib import Path
import uvicorn

from server import CameraService, create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--preview-width", type=int, default=640)
    parser.add_argument("--preview-fps", type=int, default=15)
    parser.add_argument("--bed-delay", type=float, default=2.0)
    parser.add_argument("--fill-delay", type=float, default=5.0)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "images")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-gpio", action="store_true")
    parser.add_argument("--autostart", action="store_true")
    args = parser.parse_args()

    service = CameraService(device=args.device, width=args.width, height=args.height, fps=args.fps,
                            output_dir=args.output, bed_delay=args.bed_delay, fill_delay=args.fill_delay,
                            no_gpio=args.no_gpio)
    app = create_app(service, preview_width=args.preview_width, preview_fps=args.preview_fps,
                     autostart=args.autostart)
    uvicorn.run(app, host=args.host, port=args.port, workers=1, timeout_graceful_shutdown=5,)


if __name__ == "__main__":
    main()
