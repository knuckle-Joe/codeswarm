"""P14 gate: neighbourhoods (--neighborhoods): people gather by the part of the project they work on.

Usage:
  python tools/p14_check.py SOURCE [--cache-dir DIR] [--report p14_report.txt]

SOURCE should be cached and have several top folders (ggml-org/llama.cpp).
ASCII output; the report is never overwritten (p14_report_1.txt ...).
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
from codeswarm.app import _standalone_context, initial_state, keep_clear, sim_cfg  # noqa: E402
from codeswarm.config import build_config                          # noqa: E402
from codeswarm.identity import build_people                        # noqa: E402
from codeswarm.ingest import Event, load_many                      # noqa: E402
from codeswarm.render import Renderer                              # noqa: E402
from codeswarm.sim import Swarm                                    # noqa: E402
from codeswarm.util import default_cache_dir, unique_path          # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("source")
ap.add_argument("--cache-dir", default=default_cache_dir())
ap.add_argument("--report", default="p14_report.txt")
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
cfg = build_config("default", overrides={"seed": 5, "avatars": "none", "fps": 30})
ok &= check("off by default", not cfg["neighborhoods"])
cfg["neighborhoods"] = 9
cfg["keep_clear"] = False   # what the command line does when --neighborhoods is given
ev, _ = load_many([a.source], cfg, a.cache_dir, refresh=False)
ev, _, _ = build_people(ev, cfg)
from codeswarm.colors import auto_rules   # noqa: E402
cfg["color_rules"] = auto_rules(ev)

# a monorepo with everything under src/ uses the next level
mono = [Event(i, "p%d" % (i % 7), "src/%s/f%d.c" % (("core", "net", "ui", "db")[i % 4], i), "M", "c%d" % i)
        for i in range(400)]
sm = Swarm(mono, sim_cfg(cfg), seed=1)
ok &= check("monorepo: one level deeper", sm.region_depth == 2 and "src/core/" in sm.regions, ", ".join(sm.regions))


def run(pull):
    sw = Swarm(ev, sim_cfg(cfg), seed=5)
    if not pull:
        sw._pull_to_regions = lambda alive: None
    same, other = [], []
    while sw.frame < 3000 and not sw.done:
        sw.step()
        if sw.frame < 800 or sw.frame % 20:
            continue
        al = [int(i) for i in np.nonzero(sw.people.life[:sw.people.n] > 0)[0] if int(i) in sw.person_region]
        if len(al) < 4:
            continue
        P = sw.people.pos[al]
        R = [sw.person_region[i] for i in al]
        D = np.sqrt(((P[:, None] - P[None]) ** 2).sum(-1))
        for i in range(len(al)):
            for j in range(i + 1, len(al)):
                (same if R[i] == R[j] else other).append(D[i, j])
    return float(np.mean(same)), float(np.mean(other)), sw


s0, o0, _ = run(False)
s1, o1, sw = run(True)
out("  regions: %s" % ", ".join(sw.regions))
out("  same-region / other-region distance: without the drift %.2f, with it %.2f" % (s0 / o0, s1 / o1))
ok &= check("people of one region gather", s1 / o1 <= 0.6 * (s0 / o0), "%.2f -> %.2f" % (s0 / o0, s1 / o1))

# grid layout (default): 3 x 3 cells side by side, each in its folder's legend colour
rects = list(sw.region_rect.values())
inside = all(0 <= q[0] < q[2] <= sw.w and 0 <= q[1] < q[3] <= sw.h for q in rects)
overlap = any(p_[0] < q[2] - 1 and q[0] < p_[2] - 1 and p_[1] < q[3] - 1 and q[1] < p_[3] - 1
              for i, p_ in enumerate(rects) for q in rects[i + 1:])
ok &= check("grid: cells on screen, side by side", len(rects) == len(sw.regions) and inside and not overlap,
            "%d cells" % len(rects))
legend = {tuple(c) for _, c in sw.colors.legend}
ok &= check("each cell glows in a legend colour", all(tuple(c) in legend for c in sw.region_color.values())
            and sum(1 for c in sw.region_color.values() if tuple(c) != (128, 128, 128)) >= len(sw.regions) // 2,
            ", ".join("%s %s" % (n, sw.region_color[n]) for n in sw.regions[:3]) + " ...")
mid = sw.region_rect[sw.regions[0]]
ok &= check("busiest folder in the middle cell", abs(mid[0] - sw.w / 3.0) < 1 and abs(mid[1] - sw.h / 3.0) < 1,
            "%s at %.0f,%.0f" % (sw.regions[0], mid[0], mid[1]))
ok &= check("grid covers the whole frame", abs(sum((q[2] - q[0]) * (q[3] - q[1]) for q in rects) - sw.w * sw.h) < 1)
cr = dict(cfg, neighborhood_layout="ring")
sr = Swarm(ev, sim_cfg(cr), seed=5)
ok &= check("ring layout still available", sr.regions and not sr.region_rect)

# the names: drawn in their own cell, clear of every panel (also on the very first frame)
ctx = _standalone_context()
r = Renderer(ctx, cfg)
st = initial_state(cfg)
import contextlib, io   # noqa: E401,E402
from codeswarm.cli import main as cli_main   # noqa: E402
kc = {}
for args in (["--neighborhoods"], [], ["--neighborhoods", "--keep-clear"]):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli_main(["--print-config"] + args)
    kc[" ".join(args) or "(none)"] = "keep_clear = true" in buf.getvalue()
ok &= check("keep-clear off with zones, on without, flag wins",
            kc == {"--neighborhoods": False, "(none)": True, "--neighborhoods --keep-clear": True}, str(kc))
def reach(n):
    """The cell, grown half a cell toward the screen centre (where a crowded cell's name may go)."""
    x0, y0, x1, y1 = [v * r.k for v in sw.region_rect[n]]
    hw, hh, cx, cy = (x1 - x0) / 2, (y1 - y0) / 2, (x0 + x1) / 2, (y0 + y1) / 2
    return (x0 - hw * (cx > r.w * 0.6), y0 - hh * (cy > r.h * 0.6), x1 + hw * (cx < r.w * 0.4), y1 + hh * (cy < r.h * 0.4))


def hit(b, q):
    return b[0] < q[2] and q[0] < b[2] and b[1] < q[3] and q[1] < b[3]


under, outside, edge, clash, named, looks = set(), set(), set(), 0, True, 0
for rep in range(8):                     # 8 frames, 150 apart: the panels change, the names follow
    for _ in range(150 if rep else 0):
        if not sw.done:
            sw.step()
    r.draw(sw, st)
    looks += 1
    rects = r.panel_rects(sw, st)
    labels = getattr(r, "region_labels", {})
    named &= len(labels) == len(sw.regions)
    under |= {n for n, b in labels.items() if any(hit(b, q) for q in rects)}
    outside |= {n for n, b in labels.items()
                if not (reach(n)[0] - 1 <= b[0] and b[2] <= reach(n)[2] + 1 and reach(n)[1] - 1 <= b[1] and b[3] <= reach(n)[3] + 1)}
    edge |= {n for n, b in labels.items()
             if b[0] < 0.03 * r.w - 1 or b[2] > 0.97 * r.w + 1 or b[1] < 0.05 * r.h - 1 or b[3] > 0.95 * r.h + 1}
    lb = list(labels.values())
    clash += sum(1 for i, p_ in enumerate(lb) for q in lb[i + 1:] if hit(p_, q))
under, outside, edge = sorted(under), sorted(outside), sorted(edge)
# drawn frame after frame: the names stay put or glide, never jump
step_max, moves, prev_l = 0.0, 0, {}
for _ in range(600):
    if sw.done:
        break
    sw.step()
    r.draw(sw, st)
    for n, b in r.region_labels.items():
        if n in prev_l:
            d = float(np.hypot(b[0] - prev_l[n][0], b[1] - prev_l[n][1]))
            step_max = max(step_max, d)
            moves += d > 0.5
    prev_l = dict(r.region_labels)

ok &= check("every zone named", named, "%d names, %d frames looked at" % (len(sw.regions), looks))
ok &= check("zone names clear of the panels", not under, ", ".join(under) or "all clear")
ok &= check("zone names in their cell (or reaching toward the centre)", not outside, ", ".join(outside) or "all inside")
ok &= check("zone names off the screen edge (inner 90%)", not edge, ", ".join(edge) or "all inside")
ok &= check("zone names do not cover each other", clash == 0, "%d overlaps" % clash)
ok &= check("zone names glide, never jump", step_max <= 0.2 * r.w / 3,
            "largest step %.0f px in one frame, %d name-frames moving of %d" % (step_max, moves, 600 * len(sw.regions)))

# drawn or not, same swarm (the names are only drawn)
sa = Swarm(ev, sim_cfg(cfg), seed=5)
sb = Swarm(ev, sim_cfg(cfg), seed=5)
keep_clear(sa, r, st, cfg)
keep_clear(sb, r, st, cfg)
while sa.frame < 400:
    sa.step()
    sb.step()
    r.draw(sa, st)
ok &= check("same swarm whether frames are drawn or not", np.array_equal(sa.people.pos[:sa.people.n], sb.people.pos[:sb.people.n]))
ctx.release()
c0 = dict(cfg, neighborhoods=0)
s1_, s2_ = Swarm(ev, sim_cfg(c0), seed=5), Swarm(ev, sim_cfg(dict(c0, neighborhoods=None)), seed=5)
while s1_.frame < 400:
    s1_.step()
    s2_.step()
ok &= check("off: nothing changes", not s1_.regions and np.array_equal(s1_.people.pos[:s1_.people.n], s2_.people.pos[:s2_.people.n]))

out("RESULT: %s" % ("PASS" if ok else "FAIL"))
rp = unique_path(a.report)
os.makedirs(os.path.dirname(os.path.abspath(rp)), exist_ok=True)
open(rp, "w", encoding="ascii").write("\n".join(L) + "\n")
print("Report: %s" % rp)
sys.exit(0 if ok else 1)
