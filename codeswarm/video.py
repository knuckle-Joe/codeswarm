"""Video output: raw frames piped straight into ffmpeg (no PNGs on disk)."""

import os
import shutil
import subprocess

# container extension -> (video codec, extra args)
CODECS = {
    ".mp4": ("libx264", ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]),
    ".mkv": ("libx264", ["-pix_fmt", "yuv420p"]),
    ".mov": ("libx264", ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]),
    ".webm": ("libvpx-vp9", ["-pix_fmt", "yuv420p", "-b:v", "0", "-row-mt", "1"]),
}


def find_ffmpeg():
    """ffmpeg on PATH, else the binary shipped by the imageio-ffmpeg package."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


class VideoWriter:
    def __init__(self, path, width, height, fps, crf=18, preset="medium", ffmpeg=None):
        if width % 2 or height % 2:
            raise ValueError("video size must be even (got %dx%d); use e.g. --size %dx%d"
                             % (width, height, width + width % 2, height + height % 2))
        ext = os.path.splitext(path)[1].lower()
        if ext not in CODECS:
            raise ValueError("unsupported video type %r (use %s)" % (ext, ", ".join(sorted(CODECS))))
        exe = ffmpeg or find_ffmpeg()
        if not exe:
            raise RuntimeError("ffmpeg not found. Install it (pacman -S ffmpeg / winget install ffmpeg) "
                               "or: pip install imageio-ffmpeg")
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)          # -o some/new/folder/video.mp4
        codec, extra = CODECS[ext]
        quality = ["-crf", str(crf)]
        speed = ["-preset", preset] if codec.startswith("libx26") else ["-deadline", "good", "-cpu-used", "4"]
        self.cmd = [exe, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (width, height),
                    "-r", str(fps), "-i", "-",
                    "-an", "-c:v", codec] + quality + speed + extra + [path]
        self.path = path
        self.frames = 0
        self.proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    def write(self, rgb):
        try:
            self.proc.stdin.write(rgb.tobytes())
        except (BrokenPipeError, OSError):
            err = self.proc.stderr.read().decode("utf-8", "replace")
            raise RuntimeError("ffmpeg stopped: %s" % err.strip())
        self.frames += 1

    def close(self):
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode("utf-8", "replace")
        rc = self.proc.wait()
        if rc != 0:
            raise RuntimeError("ffmpeg failed (%d): %s" % (rc, err.strip()))
