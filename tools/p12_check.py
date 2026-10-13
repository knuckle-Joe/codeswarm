"""P12 gate: crowded histories stay readable (crowd control, spacing, avatar focus).

Usage:
  python tools/p12_check.py SOURCE [--cache-dir DIR] [--report p12_report.txt]

SOURCE should be busy and cached (ggml-org/llama.cpp).  The crowded case is
made by playing it fast (2 frames per day: hundreds of people alive at once,
like a very large project); the normal case uses the default speed.
ASCII output; the report is never overwritten (p12_report_1.txt ...).
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

import numpy as np                                                  # noqa: E402
from codeswarm.app import _standalone_context, initial_state, sim_cfg  # noqa: E402
from codeswarm.config import build_config                          # noqa: E402
from codeswarm.identity import build_people                        # noqa: E402
from codeswarm.ingest import load_many                             # noqa: E402
from codeswarm.render import Renderer                              # noqa: E402
from codeswarm.sim import Swarm                                    # noqa: E402
from codeswarm.util import default_cache_dir, unique_path          # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("source")
ap.add_argument("--cache-dir", default=default_cache_dir())
ap.add_argument("--report", default="p12_report.txt")
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
# no pace and files only: this check is about crowd control on its own (see p13 for the pace limit)
base = build_config("default", overrides={"seed": 5, "avatars": "none", "pace": 0, "folders": 0})
ev, infos = load_many([a.source], base, a.cache_dir, refresh=False)
ev, people, _ = build_people(ev, base)
ok &= check("defaults", base["crowd_target"] == 60 and base["person_spacing"] == 70 and base["avatar_focus"] == 15,
            "crowd 60, spacing 70, 15 avatars")
OFF = {"crowd_target": 0, "person_spacing": 0}


def crowd(fpd, **over):
    cfg = dict(base, frames_per_day=fpd, **over)
    sw = Swarm(ev, sim_cfg(cfg), seed=5)
    alive, overlap = [], []
    while sw.frame < 1900 and not sw.done:
        sw.step()
        if sw.frame < 400 or sw.frame % 10:
            continue
        idx = np.nonzero(sw.people.life[:sw.people.n] > 0)[0]
        alive.append(len(idx))
        P = sw.people.pos[idx]
        D = np.sqrt(((P[:, None] - P[None]) ** 2).sum(-1))
        np.fill_diagonal(D, 1e9)
        overlap.append(int((D < 40).sum() // 2))
    return float(np.mean(alive)), float(np.mean(overlap)), sw


a0, o0, _ = crowd(2, **OFF)
a1, o1, _ = crowd(2)
out("  crowded: %.0f people alive, %.0f overlapping avatar pairs -> %.0f alive, %.1f pairs" % (a0, o0, a1, o1))
ok &= check("crowded: far fewer people at once", a1 <= 0.4 * a0, "%.0f -> %.0f" % (a0, a1))
ok &= check("crowded: avatars no longer stack", o1 <= 0.01 * o0 + 5, "%.0f -> %.1f pairs" % (o0, o1))
n0, q0, _ = crowd(25, **OFF)
n1, q1, _ = crowd(25)
out("  normal : %.0f people alive -> %.0f" % (n0, n1))
ok &= check("normal speed: about the same people", n1 >= 0.75 * n0, "%.0f -> %.0f" % (n0, n1))

s1 = Swarm(ev, sim_cfg(dict(base, **OFF)), seed=5)
s2 = Swarm(ev, sim_cfg(dict(base, crowd_target=0, person_spacing=0, hubs=10)), seed=5)
while s1.frame < 600 and not s1.done:
    s1.step()
    s2.step()
ok &= check("--crowd 0 --person-spacing 0 = previous motion", np.array_equal(s1.people.pos[:s1.people.n], s2.people.pos[:s2.people.n]))

# avatar focus: at most 15 + 6 pictures, faded in and out
ctx = _standalone_context()
cfg = dict(base, frames_per_day=2)
r = Renderer(ctx, cfg)
pix = np.zeros((4, 4, 4), np.uint8)
pix[..., 3] = 255
r.set_avatars({p: pix for p in people})
sw = Swarm(ev, sim_cfg(cfg), seed=5)
st = initial_state(cfg)
shown, chosen, jumps, prev = [], [], 0, {}
while sw.frame < 1000 and not sw.done:
    sw.step()
    if sw.frame < 400:
        continue
    r.draw(sw, st)
    f = r._focus or {}
    shown.append(sum(1 for v in f.values() if v > 0.5))
    chosen.append(len(r._focus_want))
    for pi, v in f.items():
        if pi in prev and abs(v - prev[pi]) > 0.5:
            jumps += 1
    prev = dict(f)
ctx.release()
ok &= check("at most 15 + 6 people chosen for a picture", max(chosen) <= 21, "max %d" % max(chosen))
ok &= check("pictures on screen about that many", np.mean(shown) <= 22,
            "mean %.1f (a few more while one fades out and another fades in)" % np.mean(shown))
ok &= check("pictures fade in and out (no pop)", jumps == 0, "%d jumps" % jumps)

out("RESULT: %s" % ("PASS" if ok else "FAIL"))
rp = unique_path(a.report)
os.makedirs(os.path.dirname(os.path.abspath(rp)), exist_ok=True)
open(rp, "w", encoding="ascii").write("\n".join(L) + "\n")
print("Report: %s" % rp)
sys.exit(0 if ok else 1)
