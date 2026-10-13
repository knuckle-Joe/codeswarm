"""P13 gate: very busy histories settle (folders, land and stick for every file, pace limit).

Usage:
  python tools/p13_check.py SOURCE [--small SOURCE2] [--cache-dir DIR] [--report p13_report.txt]

SOURCE should be busy and cached (ggml-org/llama.cpp); it is played at
2 frames per day to reach the density of a very large project.  --small is a
quieter repository for the frame-count check (default: SOURCE).
ASCII output; the report is never overwritten (p13_report_1.txt ...).
"""
import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np                                                  # noqa: E402
from codeswarm.app import sim_cfg                                  # noqa: E402
from codeswarm.colors import auto_rules                            # noqa: E402
from codeswarm.config import build_config                          # noqa: E402
from codeswarm.folders import aggregate, choose_depth, folder_of   # noqa: E402
from codeswarm.identity import build_people                        # noqa: E402
from codeswarm.ingest import Event, load_many                      # noqa: E402
from codeswarm.sim import HUB_LOCK, Swarm                          # noqa: E402
from codeswarm.util import default_cache_dir, unique_path          # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("source")
ap.add_argument("--small", default=None)
ap.add_argument("--cache-dir", default=default_cache_dir())
ap.add_argument("--report", default="p13_report.txt")
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
base = build_config("default", overrides={"seed": 5, "avatars": "none", "fps": 30})
ok &= check("defaults", base["folders"] == "auto" and base["file_motion"] == "settle" and base["pace"] == 8,
            "folders auto, settle, 8 commits/s")

# folders
ok &= check("folder of a deep file", folder_of("drivers/net/e1000/main.c", 2) == "drivers/net/")
ok &= check("shallow file -> its folder", folder_of("fs/inode.c", 2) == "fs/")
ok &= check("top-level file keeps its name", folder_of("Makefile", 2) == "Makefile")
fake = lambda n: [Event(0, "x", "d%d/f%d.c" % (i % 50, i), "M", "c") for i in range(n)]   # noqa: E731
ok &= check("auto: files for ordinary projects", choose_depth(fake(5000)) == 0)
ok &= check("auto: 3 levels above 10,000 files", choose_depth(fake(15000)) == 3)
ok &= check("auto: 2 levels above 30,000 files", choose_depth(fake(40000)) == 2)

ev, _ = load_many([a.source], base, a.cache_dir, refresh=False)
ev, _, _ = build_people(ev, base)
base["color_rules"] = auto_rules(ev)
agg = aggregate(ev, 2)
ok &= check("one change per commit and folder", len(agg) == len(set((e.commit, e.path, e.author) for e in agg)),
            "%s file changes -> %s folder changes" % ("{:,}".format(len(ev)), "{:,}".format(len(agg))))
from codeswarm.sim import ColorRules   # noqa: E402
rules = ColorRules(base["color_rules"], np.random.default_rng(0))
kinds = sum(1 for e in agg[:2000] if tuple(rules.color_for(e.kind or e.path)) != tuple(rules.color_for("zz/unknown.zzz")))
ok &= check("folders keep the colour of their files", kinds > 1000, "%d of 2000 coloured by kind" % kinds)


def run(events, **o):
    cfg = dict(base, frames_per_day=2, **o)
    sw = Swarm(events, sim_cfg(cfg), seed=5)
    sw.track = set()
    nf, sp, off, prev, state = [], [], [], None, {}
    while sw.frame < 2400 and not sw.done:
        alive = np.nonzero(sw.files.life[:sw.files.n] > 0)[0]
        sw.track, sw.track_target = set(int(i) for i in alive), {}
        sw.step()
        if sw.frame < 600:
            continue
        alive = np.nonzero(sw.files.life[:sw.files.n] > 0)[0]
        nf.append(len(alive))
        if prev is not None:
            com = alive[alive < len(prev)]
            sp.append(np.linalg.norm(sw.files.pos[com] - prev[com], axis=1))
        prev = sw.files.pos[:sw.files.n].copy()
        for fi, tgt in sw.track_target.items():
            d = float(np.hypot(*(sw.files.pos[fi] - np.array(tgt))))
            s_ = state.get(fi)
            if s_ is None or s_[0] != sw.file_editor[fi]:
                s_ = state[fi] = [sw.file_editor[fi], False]
            if s_[1]:
                off.append(d)
            elif d < 6:
                s_[1] = True
    sp = np.concatenate(sp) if sp else np.zeros(1)
    secs = sw.frame / float(cfg["fps"])
    return np.mean(nf), sp, np.array(off or [0.0]), len(sw.commits_seen) / secs


n0, sp0, off0, r0 = run(ev, folders=0, file_motion="original", pace=0)
n1, sp1, off1, r1 = run(agg, folders=2)
out("  before: %4.0f spheres, %4.1f%% of them moving, %5.1f commits per second of video" % (n0, 100 * (sp0 > 2).mean(), r0))
out("  after : %4.0f spheres, %4.1f%% of them moving, %5.1f commits per second of video" % (n1, 100 * (sp1 > 2).mean(), r1))
ok &= check("far fewer spheres", n1 <= n0 / 5, "%.0f -> %.0f" % (n0, n1))
ok &= check("far fewer spheres moving", (sp1 > 2).mean() <= 0.6 * (sp0 > 2).mean(),
            "%.0f%% -> %.0f%%" % (100 * (sp0 > 2).mean(), 100 * (sp1 > 2).mean()))
ok &= check("pace limit holds", r1 <= 8 * 1.05, "%.1f commits per second (limit 8)" % r1)
ok &= check("files stick once they arrive", (off1 > 6).mean() < 0.10 and (off1 > 6).mean() < 0.2 * (off0 > 6).mean(),
            "%.1f%% of the time off their place (springy: %.0f%%)" % (100 * (off1 > 6).mean(), 100 * (off0 > 6).mean()))

# the frame estimate matches the simulation exactly
small = a.small or a.source
sev, _ = load_many([small], base, a.cache_dir, refresh=False)
sev, _, _ = build_people(sev, base)
sev = sev[:4000]
cfg = dict(base, frames_per_day=25)
est = Swarm.paced_frames(sev, int(86400000 / 25), 8 / 30.0)
sw = Swarm(sev, sim_cfg(cfg), seed=5)
while not sw.done:
    sw.step()
ok &= check("frame estimate = frames simulated", est == sw.frame, "%d vs %d" % (est, sw.frame))

# all off = the previous motion
c0 = dict(base, folders=0, file_motion="original", pace=0)
s1, s2 = Swarm(ev, sim_cfg(c0), seed=5), Swarm(ev, sim_cfg(dict(c0, hub_min_people=2)), seed=5)
while s1.frame < 500 and not s1.done:
    s1.step()
    s2.step()
ok &= check("--folders 0 --file-motion original --pace 0 = before",
            np.array_equal(s1.files.pos[:s1.files.n], s2.files.pos[:s2.files.n]))

out("RESULT: %s" % ("PASS" if ok else "FAIL"))
rp = unique_path(a.report)
os.makedirs(os.path.dirname(os.path.abspath(rp)), exist_ok=True)
open(rp, "w", encoding="ascii").write("\n".join(L) + "\n")
print("Report: %s" % rp)
sys.exit(0 if ok else 1)
