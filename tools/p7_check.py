"""P7 gate: histogram size, engine label, default caption, 20 ranked files,
repository panel numbers, and the README flag reference.

Usage: python tools/p7_check.py SOURCE [--cache-dir DIR] [--workdir p7_work] [--report p7_report.txt]
SOURCE should be cached (run `codeswarm SOURCE --stats` once). ASCII output,
report and work files never overwrite earlier ones.
"""
import argparse
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _deps import require  # noqa: E402
require("numpy", "pygame", "moderngl")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import numpy as np                                        # noqa: E402
from codeswarm.app import run_headless, sim_cfg          # noqa: E402
from codeswarm.colors import auto_rules                  # noqa: E402
from codeswarm.config import build_config                # noqa: E402
from codeswarm.ingest import load_many                   # noqa: E402
from codeswarm.sim import Swarm                          # noqa: E402
from codeswarm.util import default_cache_dir, unique_path  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("source")
ap.add_argument("--cache-dir", default=default_cache_dir())
ap.add_argument("--workdir", default="p7_work")
ap.add_argument("--report", default="p7_report.txt")
a = ap.parse_args()
os.makedirs(a.workdir, exist_ok=True)
L = []


def out(m):
    m = str(m).encode("ascii", "backslashreplace").decode("ascii")
    print(m)
    L.append(m)


def check(name, ok, detail=""):
    out("  [%s] %-46s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


ok = True
cfg = build_config("default", overrides={"seed": 4, "frames_per_day": 2})
ev, _ = load_many([a.source], cfg, a.cache_dir, refresh=False)
cfg["color_rules"] = auto_rules(ev)
ok &= check("defaults", cfg["histogram_scale"] == 2 and cfg["popular_count"] == 20 and cfg["show_stats"]
            and cfg["auto_caption"], "histogram x2, 20 files, panel on, caption on")

# ---- numbers in the panel vs a brute-force count
sw = Swarm(ev, sim_cfg(cfg), seed=4)
good, checked = True, 0
W = sw.window_ms
while not sw.done and sw.frame < 4000:
    sw.step()
    if sw.frame % 211:
        continue
    seen = sw.events[:sw.ev_i]
    lo = sw.prev_date - W
    win = [e for e in seen if e.date >= lo]
    st = sw.stats()
    exp = {"commits": len(set(e.commit for e in seen)), "people": len(set(e.author for e in seen)),
           "files": len(set(e.path for e in seen)), "w_commits": len(set(e.commit for e in win)),
           "w_people": len(set(e.author for e in win)), "w_files": len(set(e.path for e in win)),
           "w_changes": len(win)}
    good &= all(st[k] == v for k, v in exp.items())
    status = {}
    for e in win:
        status[e.status or "?"] = status.get(e.status or "?", 0) + 1
    good &= st["w_status"] == status
    act = sw.active_people(5)
    cnt = {}
    for e in win:
        cnt[e.author] = cnt.get(e.author, 0) + 1
    good &= [n for _, n, _ in act] == sorted(cnt.values(), reverse=True)[:5]
    checked += 1
ok &= check("panel numbers = brute-force count", good, "%d frames checked" % checked)
ok &= check("totals", sw.totals == {"commits": len(set(e.commit for e in ev)), "people": len(set(e.author for e in ev)),
                                    "files": len(set(e.path for e in ev))}, str(sw.totals))

# ---- rendering: histogram, engine, caption, list fits
frames = {}
target = min(3000, sw.frame)
for label, extra in (("default", {"show_engine": True, "caption": "test"}),
                     ("hist1", {"histogram_scale": 1, "histogram_max": None}),
                     ("hcap", {"show_popular": False, "show_names": False}),
                     ("hnone", {"show_popular": False, "show_names": False, "show_history": False})):
    run_headless(ev, dict(cfg, keep_clear=False, **extra), max_frames=target,   # same swarm in every variant
                 frame_callback=lambda n, img, lab=label: frames.__setitem__(lab, img.copy()) if n == target else None)
img = frames["default"]
h, w = img.shape[:2]
k = h / 720.0


def hist_extent(im):
    band = im[int(h * 0.6):, : w // 2]
    lit = band.max(axis=2) > 40
    cols = np.nonzero(lit[-6:].any(axis=0))[0]
    rows = np.nonzero(lit.any(axis=1))[0]
    return (cols.max() if len(cols) else 0), (band.shape[0] - rows.min() if len(rows) else 0)


w2, _ = hist_extent(img)
w1, _ = hist_extent(frames["hist1"])
# height: only the pixels the histogram itself adds (same frame drawn with and without it)
diff = np.abs(frames["hcap"].astype(int) - frames["hnone"].astype(int)).max(axis=2) > 30
drows = np.nonzero(diff[:, : w // 2].any(axis=1))[0]
h2 = (h - drows.min()) if len(drows) else 0
ok &= check("histogram twice as wide", 1.7 < w2 / float(max(w1, 1)) < 2.3, "%d px vs %d px" % (w2, w1))
ok &= check("histogram capped at 22% of height", h2 <= h * 0.22 + 6 * k, "%d px of %d" % (h2, h))
br = img[int(h - 3 * 20 * k):, int(w * 0.75):]
rows = np.nonzero((br.max(axis=2) > 120).any(axis=1))[0]
gaps = np.nonzero(np.diff(rows) > 3)[0]
ok &= check("engine name and date on separate lines", len(gaps) >= 1, "%d text bands" % (len(gaps) + 1))

# default caption through the command line
png_dir = unique_path(os.path.join(a.workdir, "cap"))
env = dict(os.environ, PYTHONPATH=ROOT)
subprocess.run([sys.executable, "-m", "codeswarm", a.source, "--cache-dir", a.cache_dir, "--offline", "--avatars",
                "none", "--frames", png_dir, "--start-frame", "50", "--max-frames", "50"], env=env, check=True,
               stdout=subprocess.PIPE)
import pygame                                              # noqa: E402
cap_img = pygame.surfarray.array3d(pygame.image.load(os.path.join(png_dir, "cs-00050.png"))).transpose(1, 0, 2)
band = cap_img[5:int(50 * k), 5:int(400 * k)]
cyan = ((band[..., 2] > 150) & (band[..., 1] > 150) & (band[..., 0] < 160)).sum()
ok &= check("repository name caption on by default", cyan > 200, "%d caption pixels" % cyan)

# ---- README reference table in sync with the program
p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "flags_table.py"), "--check"],
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
ok &= check("README flag table matches the program", p.returncode == 0, p.stdout.decode().strip())
from codeswarm.cli import build_parser                     # noqa: E402
readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
missing = [o for act in build_parser()._actions for o in act.option_strings
           if o.startswith("--") and not o.startswith("--no-") and "`%s`" % o not in readme]
ok &= check("every flag documented", not missing, ", ".join(missing[:5]))

out("RESULT: %s" % ("PASS" if ok else "FAIL"))
rp = unique_path(a.report)
os.makedirs(os.path.dirname(os.path.abspath(rp)), exist_ok=True)
open(rp, "w", encoding="ascii").write("\n".join(L) + "\n")
print("Report: %s" % rp)
sys.exit(0 if ok else 1)
