"""P9 gate: tracked files reach their editor fast and stick (no bounce), people unchanged, 8-line ticker.

Usage:
  python tools/p9_check.py SOURCE [--cache-dir DIR] [--report p9_report.txt]

SOURCE should be a busy repository (ggml-org/llama.cpp shows the problem
best; pallets/flask works too) and be cached (run `codeswarm SOURCE --stats`
once).  ASCII output; the report is never overwritten (p9_report_1.txt ...).
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
from codeswarm.colors import auto_rules                            # noqa: E402
from codeswarm.config import build_config                          # noqa: E402
from codeswarm.identity import build_people                        # noqa: E402
from codeswarm.ingest import load_many                             # noqa: E402
from codeswarm.render import Renderer                              # noqa: E402
from codeswarm import sim as simmod                                 # noqa: E402
from codeswarm.sim import Swarm                                    # noqa: E402
from codeswarm.util import default_cache_dir, unique_path          # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("source")
ap.add_argument("--cache-dir", default=default_cache_dir())
ap.add_argument("--report", default="p9_report.txt")
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
# springy files and no pace: this check compares the tracked files with the original motion (see p13)
cfg = build_config("default", overrides={"seed": 5, "avatars": "none", "file_motion": "original", "pace": 0})
ev, infos = load_many([a.source], cfg, a.cache_dir, refresh=False)
ev, _, _ = build_people(ev, cfg)
cfg["color_rules"] = auto_rules(ev)
meta = infos[0]["meta_all"]
ok &= check("defaults", cfg["hubs"] == 10 and cfg["ticker_lines"] == 8 and cfg["dim_idle_avatars"]
            and cfg["hub_follow"] == 1.0 and cfg["hub_rate"] == 0.3 and cfg["hub_speed"] == 20 and not cfg["hub_gather"],
            "10 hubs, follow 1, rate 0.3, max 20 px, 8 ticker lines")

start = min(2000, max(50, len(ev) // 40))
stop = start + 2500


def motion(hubs):
    """For the shared ranked files (changed by 2+ people, the ones that become
    hubs): frames from a change of editor until the file is on its ring slot
    (within 6 px), how far it strays from the slot once there, its speed."""
    sw = Swarm(ev, sim_cfg(dict(cfg, hubs=hubs)), seed=5, meta=meta)
    arrive, after, speeds, prev, state, offscreen = [], [], [], {}, {}, 0
    while not sw.done and sw.frame < stop:
        top = [fi for _, _, fi in sw.popular(10) if sw._recent_fauth.get(fi, 0) >= 2]
        sw.track, sw.track_target = set(top), {}
        sw.step()
        if sw.frame < start:
            continue
        for fi in top:
            if fi in prev:
                speeds.append(float(np.linalg.norm(sw.files.pos[fi] - prev[fi])))
            tgt = sw.track_target.get(fi) or sw._hub_slot.get(fi)
            if tgt is None:
                continue
            d = float(np.hypot(*(sw.files.pos[fi] - np.array(tgt))))
            s_ = state.get(fi)
            if s_ is None or s_[0] != sw.file_editor[fi]:
                s_ = state[fi] = [sw.file_editor[fi], sw.frame, None]
            if s_[2] is None:
                if d < 6:
                    s_[2] = sw.frame
                    arrive.append(sw.frame - s_[1])
            else:
                after.append(d)
            x, y = sw.files.pos[fi]
            offscreen += int(hubs and fi in sw.hubs and not (0 <= x <= sw.w and 0 <= y <= sw.h))
        prev = {fi: sw.files.pos[fi].copy() for fi in top}
    arr = np.array(arrive or [0], np.float64)
    aft = np.array(after or [0], np.float64)
    return arr, aft, np.array(speeds or [0], np.float64), offscreen, sw


arr0, aft0, sp0, _, sw0 = motion(0)
arr1, aft1, sp1, offscreen, sw1 = motion(10)
for lab, ar, af, sp in (("original", arr0, aft0, sp0), ("new     ", arr1, aft1, sp1)):
    out("  %s: arrives in %3.0f frames (median), %3.0f (slowest 10%%); after arriving %4.1f px off its slot "
        "on average, %4.1f%% of the time more than 6 px; top speed %4.1f px/frame"
        % (lab, np.median(ar), np.percentile(ar, 90), af.mean(), 100.0 * (af > 6).mean(), np.percentile(sp, 99)))
ok &= check("tracked files arrive at least as fast", np.median(arr1) <= np.median(arr0) and
            np.percentile(arr1, 90) <= np.percentile(arr0, 90),
            "median %.0f vs %.0f, slowest 10%% %.0f vs %.0f frames" % (np.median(arr1), np.median(arr0),
                                                                       np.percentile(arr1, 90), np.percentile(arr0, 90)))
ok &= check("and stick to their slot (no bounce)", (aft1 > 6).mean() < 0.05 and aft1.mean() < aft0.mean() / 4,
            "%.1f%% of the time off (original %.0f%%)" % (100.0 * (aft1 > 6).mean(), 100.0 * (aft0 > 6).mean()))
ok &= check("speed limit holds", np.percentile(sp1, 99) <= cfg["hub_speed"] * 1.05,
            "99th percentile %.1f px/frame (limit %.0f)" % (np.percentile(sp1, 99), cfg["hub_speed"]))
same_people = bool(np.array_equal(sw0.people.pos[:sw0.people.n], sw1.people.pos[:sw1.people.n]))
ok &= check("people move exactly as in the original", same_people, "positions at frame %d" % sw1.frame)
ok &= check("hubs stay on screen", offscreen == 0)

# hubs 0 = the original motion exactly
plain = Swarm(ev, sim_cfg(dict(cfg, hubs=0)), seed=5)
again = Swarm(ev, sim_cfg(dict(cfg, hubs=0)), seed=5, meta=meta)
same = True
while plain.frame < 600 and not plain.done:
    plain.step()
    again.step()
same &= bool(np.array_equal(plain.files.pos[:plain.files.n], again.files.pos[:again.files.n]))
ok &= check("--hubs 0 keeps the original motion", same)

# ticker: 8 lines, the last one just above the date
ctx = _standalone_context()
r = Renderer(ctx, cfg)
sw = Swarm(ev, sim_cfg(cfg), seed=5, meta=meta)
st = initial_state(cfg)
lines = 0
while not sw.done and sw.frame < start + 600:
    sw.step()
    if sw.frame > start:
        r.draw(sw, st)
        lines = max(lines, getattr(r, "ticker_drawn", 0))
f = r.fonts.normal
date_base = r.h - (2 + abs(f.get_descent()))
gap = (date_base - r.ticker_base) / float(f.get_linesize() + 2)
ok &= check("ticker shows 8 lines", lines == 8, "%d lines" % lines)
ok &= check("ticker sits on the line above the date", 0.9 < gap < 1.1,
            "%.1f lines above" % gap)
ctx.release()

out("RESULT: %s" % ("PASS" if ok else "FAIL"))
rp = unique_path(a.report)
os.makedirs(os.path.dirname(os.path.abspath(rp)), exist_ok=True)
open(rp, "w", encoding="ascii").write("\n".join(L) + "\n")
print("Report: %s" % rp)
sys.exit(0 if ok else 1)
