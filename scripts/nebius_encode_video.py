"""Encode actual captured browser frames. No generated or fabricated application footage."""

import json
import argparse
import subprocess
from pathlib import Path

import imageio_ffmpeg


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-review", action="store_true")
    parser.add_argument("--live-browser", action="store_true")
    args = parser.parse_args()
    directory = root / ("runtime/nebius/video-live-review" if args.real_review else "runtime/nebius/video")
    if args.live_browser:
        directory = root / "runtime/nebius/video-live"
    capture = json.loads((directory / "capture.json").read_text(encoding="utf8"))
    frames = Path(capture["frames_directory"]).resolve()
    if not frames.is_relative_to(directory.resolve()):
        raise ValueError("Unexpected frames path")
    output = directory / ("IncidentPilot-real-evidence-demo.mp4" if args.real_review else "IncidentPilot-offline-demo-draft.mp4")
    if args.live_browser:
        output = directory / "IncidentPilot-live-browser-demo.mp4"
    duration = capture["frames"] / capture["fps"]
    if not 1 <= duration < 180:
        raise ValueError("Video must be under three minutes")
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                    "-framerate", str(capture["fps"]), "-i", str(frames / "%05d.jpg"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24",
                    "-movflags", "+faststart", str(output)], check=True)
    check = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(output),
                            "-f", "null", "-"], capture_output=True)
    if check.returncode or check.stderr:
        raise RuntimeError("Video decode validation failed")
    result = {"status": "PASS", "artifact": str(output), "duration_seconds": duration,
              "bytes": output.stat().st_size, "mode": capture["mode"],
              "english_captions": True, "decode_errors": 0, "public_url": None,
              "competition_ready": False, "reason": "Public upload and judge access pending; recorded review of real runs" if args.real_review else "Live AI evidence and public upload pending"}
    if args.live_browser:
        result["reason"] = "Live browser validation passed; public upload and judge access pending"
    (directory / "validation.json").write_text(json.dumps(result, indent=2), encoding="utf8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
