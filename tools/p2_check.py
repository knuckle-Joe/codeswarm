"""P2 gate: video export.

Usage: python tools/p2_check.py SOURCE [--since 2023-01-01] [--size 1280x720]
       [--frames-per-day 2] [--cache-dir DIR] [--workdir p2_work] [--report p2_report.txt]

Checks:
 1. determinism: same seed -> byte-identical frames; other seed -> different
 2. the MP4 holds exactly the rendered frames (count, size, duration)
 3. frames decoded back from the MP4 match the rendered frames (PSNR)
 4. a second export does not overwrite the first (name_1.mp4)
Needs ffmpeg and ffprobe on PATH. ASCII output; report never overwritten.
"""
import argparse, hashlib, json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _deps import require  # noqa: E402
require("numpy", "pygame", "moderngl")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from codeswarm.app import run_headless
from codeswarm.config import build_config
from codeswarm.ingest import load_events
from codeswarm.util import default_cache_dir, unique_path

ap = argparse.ArgumentParser()
ap.add_argument("source"); ap.add_argument("--since", default=None)
ap.add_argument("--size", default="1280x720"); ap.add_argument("--frames-per-day", type=float, default=2)
ap.add_argument("--cache-dir", default=default_cache_dir()); ap.add_argument("--workdir", default="p2_work")
ap.add_argument("--report", default="p2_report.txt")
a = ap.parse_args()
w, h = [int(v) for v in a.size.split("x")]
os.makedirs(a.workdir, exist_ok=True)
L = []
def out(m): print(m); L.append(m)
def check(name, ok, detail=""):
    out("  [%s] %-34s %s" % ("PASS" if ok else "FAIL", name, detail)); return ok

def cfg_for(seed):
    return build_config("classic", overrides={"width": w, "height": h, "frames_per_day": a.frames_per_day,
                                              "seed": seed, "since": a.since})
cfg = cfg_for(11)
events, _ = load_events(a.source, cfg, a.cache_dir, refresh=False)
# same people step as the command line (merged identities, bots hidden)
from codeswarm.identity import build_people  # noqa: E402
events, _people, _prep = build_people(events, cfg)
out("source %s: %d events" % (a.source, len(events)))
ok = True

# 1. determinism
def hashes(seed, keep=None):
    hs = []
    def cb(n, img):
        hs.append(hashlib.sha256(img.tobytes()).hexdigest())
        if keep is not None and n in keep: keep[n] = img.copy()
    run_headless(events, cfg_for(seed), frame_callback=cb)
    return hs
keep = {}
h1 = hashes(11); h2 = hashes(11); h3 = hashes(12)
ok &= check("same seed, identical frames", h1 == h2, "%d frames" % len(h1))
ok &= check("other seed, different frames", h1 != h3, "%d of %d differ" % (sum(x != y for x, y in zip(h1, h3)), len(h1)))

# 2/3. video
mp4 = os.path.join(a.workdir, "p2.mp4")
first = unique_path(mp4)
cmd = [sys.executable, "-m", "codeswarm", a.source, "--cache-dir", a.cache_dir, "--offline",
       "--preset", "classic", "--size", a.size, "--frames-per-day", str(a.frames_per_day),
       "--seed", "11", "-o", first] + (["--since", a.since] if a.since else [])
ENV = dict(os.environ, PYTHONPATH=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, env=ENV)
probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                                   "-show_entries", "stream=nb_read_frames,width,height,r_frame_rate,codec_name,pix_fmt",
                                   "-show_entries", "format=duration", "-of", "json", first],
                                  stdout=subprocess.PIPE, check=True).stdout)
st = probe["streams"][0]
ok &= check("frame count", int(st["nb_read_frames"]) == len(h1), "video=%s rendered=%d" % (st["nb_read_frames"], len(h1)))
ok &= check("size / codec", (st["width"], st["height"]) == (w, h) and st["codec_name"] == "h264" and st["pix_fmt"] == "yuv420p",
            "%sx%s %s %s" % (st["width"], st["height"], st["codec_name"], st["pix_fmt"]))
dur = float(probe["format"]["duration"]); exp = len(h1) / float(cfg["fps"])
ok &= check("duration", abs(dur - exp) < 2.0 / cfg["fps"], "%.2f s (expected %.2f)" % (dur, exp))

picks = sorted(set([1, len(h1) // 3, 2 * len(h1) // 3, len(h1)]))
ref = {n: None for n in picks}
run_headless(events, cfg_for(11), frame_callback=lambda n, img: ref.__setitem__(n, img.copy()) if n in ref else None)
# decode only the sampled frames (a whole long video would not fit in memory)
sel = "+".join("eq(n\\,%d)" % (n - 1) for n in picks)
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", first, "-vf", "select=" + sel, "-fps_mode", "passthrough",
                      "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, check=True).stdout
vid = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)
psnrs = []
for i, n in enumerate(picks):
    d = vid[i].astype(np.float64) - ref[n].astype(np.float64)
    mse = (d ** 2).mean()
    psnrs.append(99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse))
ok &= check("decoded frames match render", min(psnrs) > 35, "PSNR dB at frames %s: %s" % (picks, ", ".join("%.1f" % p for p in psnrs)))

# 4. no overwrite
second_expected = unique_path(mp4)
cmd2 = list(cmd); cmd2[cmd2.index("-o") + 1] = mp4
subprocess.run(cmd2, check=True, stdout=subprocess.DEVNULL, env=ENV)
ok &= check("second export not overwriting", os.path.exists(second_expected) and second_expected != first,
            "%s then %s" % (os.path.basename(first), os.path.basename(second_expected)))
out("RESULT: %s" % ("PASS" if ok else "FAIL"))
path = unique_path(a.report)
open(path, "w", encoding="ascii").write("\n".join(L) + "\n")
print("Report:", path)
sys.exit(0 if ok else 1)
