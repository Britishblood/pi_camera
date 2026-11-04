import argparse
from pathlib import Path
import signal

from camera import CameraManager
from capture import CaptureController
from server import create_app

GPIO_PIN = 27

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--preview-width", type=int, default=640)
    parser.add_argument("--preview-fps", type=int, default=10)
    parser.add_argument("--bed-delay", type=float, default=2.0)
    parser.add_argument("--fill-delay", type=float, default=5.0)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "images")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-gpio", action="store_true", help="Test without a physical GPIO button")
    args = parser.parse_args()

    camera = CameraManager(args.device, args.width, args.height, args.fps)
    capture = CaptureController(camera, args.output, args.bed_delay, args.fill_delay)
    button = None
    camera.start()
    capture.start()

    try:
        if not args.no_gpio:
            from gpiozero import Button
            button = Button(GPIO_PIN, pull_up=False, bounce_time=0.05)
            button.when_pressed = capture.button_pressed
            print(f"GPIO {GPIO_PIN} ready (dynamic trigger cooldown)", flush=True)

        app = create_app(camera, capture, args.preview_width, args.preview_fps)
        print(f"Preview: http://<PI-IP>:{args.port}/video", flush=True)
        print(f"Status:  http://<PI-IP>:{args.port}/status", flush=True)
        app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)
    finally:
        if button is not None:
            button.close()
        capture.stop()
        camera.stop()


if __name__ == "__main__":
    main()
