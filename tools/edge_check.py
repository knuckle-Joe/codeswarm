"""Measure how much of the swarm ends up off screen.

Usage: python tools/edge_check.py SOURCE [--preset classic] [--size 1280x720]
       [--frames-per-day 2] [--seed 1] [--report edge_report.txt]

For every frame: share of living files whose centre lies outside the frame,
and share of living people pinned at the edge clamp.  Runs bounds=legacy
and bounds=auto on the same seed and prints both. No rendering needed.
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _deps import require  # noqa: E402
require("numpy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from codeswarm.config import build_config
from codeswarm.ingest import load_events
from codeswarm.sim import Swarm
from codeswarm.util import default_cache_dir, unique_path

ap = argparse.ArgumentParser()
ap.add_argument("source"); ap.add_argument("--preset", default="classic")
ap.add_argument("--size", default="1280x720"); ap.add_argument("--frames-per-day", type=float, default=2)
ap.add_argument("--seed", type=int, default=1); ap.add_argument("--cache-dir", default=default_cache_dir())
ap.add_argument("--report", default="edge_report.txt")
a = ap.parse_args()
w, h = [int(v) for v in a.size.split("x")]
lines = []
for mode in ("legacy", "auto"):
    cfg = build_config(a.preset, overrides={"width": w, "height": h, "frames_per_day": a.frames_per_day,
                                            "seed": a.seed, "bounds": mode})
    ev, _ = load_events(a.source, cfg, a.cache_dir, refresh=False)
    sw = Swarm(ev, cfg, seed=a.seed)
    tot_files = off_files = 0
    worst = 0.0
    while not sw.done:
        sw.step()
        f = sw.files
        alive = f.life[: f.n] > 0
        if alive.any():
            P = f.pos[: f.n][alive]
            out = (P[:, 0] < 0) | (P[:, 0] > w) | (P[:, 1] < 0) | (P[:, 1] > h)
            tot_files += int(alive.sum()); off_files += int(out.sum())
            worst = max(worst, out.mean())
    lines.append("%-6s frames=%d  files off screen: %.2f%% of file-frames, worst frame %.0f%%"
                 % (mode, sw.frame, 100.0 * off_files / max(tot_files, 1), 100 * worst))
path = unique_path(a.report)
open(path, "w", encoding="ascii").write("\n".join(lines) + "\n")
print("\n".join(lines)); print("Report:", path)
