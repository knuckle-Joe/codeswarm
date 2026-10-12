"""P10 gate: the swarm keeps out of the panels; names stay with their avatars.

Usage:
  python tools/p10_check.py SOURCE [--cache-dir DIR] [--report p10_report.txt]

SOURCE should be busy (ggml-org/llama.cpp) and cached (run
`codeswarm SOURCE --stats` once).  ASCII output; the report is never
overwritten (p10_report_1.txt ...).
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
from codeswarm.colors import auto_rules                            # noqa: E402
from codeswarm.config import build_config                          # noqa: E402
from codeswarm.identity import build_people                        # noqa: E402
from codeswarm.ingest import load_many                             # noqa: E402
from codeswarm.render import Renderer                              # noqa: E402
from codeswarm.sim import Swarm                                    # noqa: E402
from codeswarm.util import default_cache_dir, unique_path          # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("source")
ap.add_argument("--cache-dir", default=default_cache_dir())
ap.add_argument("--report", default="p10_report.txt")
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
cfg = build_config("default", overrides={"seed": 5, "avatars": "none"})
ev, infos = load_many([a.source], cfg, a.cache_dir, refresh=False)
ev, _, _ = build_people(ev, cfg)
cfg["color_rules"] = auto_rules(ev)
meta = infos[0]["meta_all"]
ok &= check("default: keep clear on", cfg["keep_clear"] is True)
ctx = _standalone_context()
start = min(2000, max(50, len(ev) // 40))
stop = start + 1500


def run(keep, draw_every):
    """Share of living people (and ranked files) inside the panels; drawing
    every Nth frame (0 = never) must not change the swarm."""
    c = dict(cfg, keep_clear=keep)
    r = Renderer(ctx, c)
    sw = Swarm(ev, sim_cfg(c), seed=5, meta=meta)
    st = initial_state(c)
    keep_clear(sw, r, st, c)
    inside = total = 0
    k = r.k
    while not sw.done and sw.frame < stop:
        sw.step()
        if draw_every and sw.frame % draw_every == 0:
            r.draw(sw, st)
        if sw.frame >= start and sw.frame % 10 == 0:
            rects = r.panel_rects(sw, st)
            alive = np.nonzero(sw.people.life[:sw.people.n] > 0)[0]
            P = sw.people.pos[alive] * k
            for x0, y0, x1, y1 in rects:
                inside += int(((P[:, 0] > x0) & (P[:, 0] < x1) & (P[:, 1] > y0) & (P[:, 1] < y1)).sum())
            total += len(alive)
    return inside / float(max(total, 1)), sw


share_off, _ = run(False, 0)
share_on, sw_a = run(True, 1)
_, sw_b = run(True, 0)
out("  people inside a panel: %.1f%% without keep-clear, %.1f%% with it" % (100 * share_off, 100 * share_on))
ok &= check("people stay out of the panels", share_on <= 0.2 * share_off + 0.002,
            "%.1f%% -> %.1f%% of person-frames" % (100 * share_off, 100 * share_on))
same = (np.array_equal(sw_a.people.pos[:sw_a.people.n], sw_b.people.pos[:sw_b.people.n]) and
        np.array_equal(sw_a.files.pos[:sw_a.files.n], sw_b.files.pos[:sw_b.files.n]))
ok &= check("same swarm whether frames are drawn or not", same, "video = window = frames")

# keep-clear off: the swarm is the one from before this change
c0 = dict(cfg, keep_clear=False)
s1 = Swarm(ev, sim_cfg(c0), seed=5, meta=meta)
s2 = Swarm(ev, sim_cfg(c0), seed=5)
while s1.frame < 800 and not s1.done:
    s1.step()
    s2.step()
ok &= check("--no-keep-clear changes nothing else", np.array_equal(s1.people.pos[:s1.people.n], s2.people.pos[:s2.people.n]))

# names: only the name moves, a little; the subject never moves it
r = Renderer(ctx, cfg)
sw = Swarm(ev, sim_cfg(cfg), seed=5, meta=meta)
st = initial_state(cfg)
keep_clear(sw, r, st, cfg)
far_x = far_y = 0.0
jumps = 0
prev = {}
with_subject = 0
while not sw.done and sw.frame < start + 600:
    sw.step()
    if sw.frame < start:
        continue
    r.draw(sw, st)
    for pi, v in (r._layout or {}).items():
        far_x, far_y = max(far_x, abs(v[0])), max(far_y, abs(v[1]))
        if pi in prev and abs(v[0] - prev[pi][0]) + abs(v[1] - prev[pi][1]) > 40 * r.k:
            jumps += 1
    with_subject += len(r._subjects)
    prev = {pi: v[:2] for pi, v in (r._layout or {}).items()}
line = r.fonts.bold.get_linesize()
ok &= check("names stay with their avatar", far_x <= 30 * r.k + 1 and far_y <= 3 * 0.6 * line + 1,
            "farthest %.0f px aside, %.0f px down" % (far_x, far_y))
ok &= check("no name jumps away and back", jumps == 0, "%d jumps over %d subject-frames" % (jumps, with_subject))
ctx.release()

out("RESULT: %s" % ("PASS" if ok else "FAIL"))
rp = unique_path(a.report)
os.makedirs(os.path.dirname(os.path.abspath(rp)), exist_ok=True)
open(rp, "w", encoding="ascii").write("\n".join(L) + "\n")
print("Report: %s" % rp)
sys.exit(0 if ok else 1)
