"""P6 gate: 1920x1080 default and the ui scale.

Usage: python tools/p6_check.py SOURCE [--cache-dir DIR] [--report p6_report.txt]

Checks that at 1920x1080 the swarm behaves exactly like the tested 1280x720
layout (same simulation, drawn 1.5x larger), that text and avatars grow with
the frame, and that --ui-scale overrides it. ASCII output, report never
overwritten.
"""
import argparse
import os
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
from codeswarm.render import sim_size, ui_scale          # noqa: E402
from codeswarm.sim import Swarm                          # noqa: E402
from codeswarm.util import default_cache_dir, unique_path  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("source")
ap.add_argument("--cache-dir", default=default_cache_dir())
ap.add_argument("--report", default="p6_report.txt")
a = ap.parse_args()
L = []


def out(m):
    m = str(m).encode("ascii", "backslashreplace").decode("ascii")
    print(m)
    L.append(m)


def check(name, ok, detail=""):
    out("  [%s] %-46s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


ok = True
base = build_config("default", overrides={"seed": 3, "frames_per_day": 2})
ok &= check("default size is 1920x1080", (base["width"], base["height"]) == (1920, 1080), "")
ok &= check("auto ui scale at 1080 = 1.5", abs(ui_scale(base) - 1.5) < 1e-9, "simulation canvas %dx%d" % sim_size(base))
for h, k in ((720, 1.0), (1440, 2.0), (2160, 3.0)):
    ok &= check("auto ui scale at %d = %g" % (h, k), abs(ui_scale(dict(base, height=h)) - k) < 1e-9, "")
ok &= check("--ui-scale 1 overrides", ui_scale(dict(base, ui_scale="1")) == 1.0, "")

ev, _ = load_many([a.source], base, a.cache_dir, refresh=False)
ev = ev[:1500]
base["color_rules"] = auto_rules(ev)
small = dict(base, width=1280, height=720)
s1 = Swarm(ev, sim_cfg(small), seed=3)
s2 = Swarm(ev, sim_cfg(base), seed=3)
same = True
for _ in range(600):
    if s1.done:
        break
    s1.step()
    s2.step()
    same &= np.array_equal(s1.files.pos[: s1.files.n], s2.files.pos[: s2.files.n]) and \
        np.array_equal(s1.people.pos[: s1.people.n], s2.people.pos[: s2.people.n])
ok &= check("1080 swarm = 720 swarm (same simulation)", same, "%d frames compared" % s1.frame)

frames = {}
for label, c in (("720", small), ("1080", base), ("1080 scale 1", dict(base, ui_scale="1"))):
    run_headless(ev, c, max_frames=300, frame_callback=lambda n, img, lab=label: frames.__setitem__(lab, img.copy()) if n == 300 else None)
a720, a1080 = frames["720"], frames["1080"]
lit = lambda im: (im.max(axis=2) > 60).sum()
ratio = lit(a1080) / float(max(lit(a720), 1))
ok &= check("lit pixels grow ~1.5^2 = 2.25x", 1.6 < ratio < 3.0, "ratio %.2f" % ratio)
ratio1 = lit(frames["1080 scale 1"]) / float(max(lit(a720), 1))
ok &= check("--ui-scale 1 keeps the small look", ratio1 < ratio, "ratio %.2f" % ratio1)

from codeswarm.render import Fonts                          # noqa: E402
import moderngl                                             # noqa: E402
try:
    ctx = moderngl.create_standalone_context(require=330)
except Exception:
    ctx = moderngl.create_standalone_context(require=330, backend="egl")
f720, f1080 = Fonts(ctx, small), Fonts(ctx, base)
hr = f1080.normal.get_height() / float(f720.normal.get_height())
ok &= check("text height grows with the frame", 1.3 < hr < 1.7, "%d px -> %d px" % (f720.normal.get_height(),
                                                                                  f1080.normal.get_height()))

out("RESULT: %s" % ("PASS" if ok else "FAIL"))
rp = unique_path(a.report)
os.makedirs(os.path.dirname(os.path.abspath(rp)), exist_ok=True)
open(rp, "w", encoding="ascii").write("\n".join(L) + "\n")
print("Report: %s" % rp)
sys.exit(0 if ok else 1)
