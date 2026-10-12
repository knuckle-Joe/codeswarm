"""P4 gate: quiet-period compression, target duration, intro/credits cards,
several repositories in one swarm, clean failures.

Usage:
  python tools/p4_check.py SOURCE_A SOURCE_B [--cache-dir DIR] [--workdir p4_work] [--report p4_report.txt]

Uses cached histories when available (run codeswarm SOURCE --stats once first).
ASCII output; report and work files never overwrite earlier ones.
"""
import argparse
import json
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _deps import require  # noqa: E402
require("numpy", "pygame", "moderngl")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import numpy as np                                            # noqa: E402
from codeswarm.app import ShowSpec, run_headless, estimate_frames   # noqa: E402
from codeswarm.colors import repo_rules                       # noqa: E402
from codeswarm.config import build_config                     # noqa: E402
from codeswarm.identity import build_people                   # noqa: E402
from codeswarm.ingest import load_many                        # noqa: E402
from codeswarm.sim import Swarm                               # noqa: E402
from codeswarm.timeline import DAY_MS, compress_gaps          # noqa: E402
from codeswarm.util import default_cache_dir, unique_path     # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("a")
ap.add_argument("b")
ap.add_argument("--cache-dir", default=default_cache_dir())
ap.add_argument("--workdir", default="p4_work")
ap.add_argument("--report", default="p4_report.txt")
a = ap.parse_args()
os.makedirs(a.workdir, exist_ok=True)
L = []


def out(m):
    m = str(m).encode("ascii", "backslashreplace").decode("ascii")
    print(m)
    L.append(m)


def check(name, ok, detail=""):
    out("  [%s] %-42s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


ok = True
cfg = build_config("default", overrides={"seed": 5, "frames_per_day": 2})
ENV = dict(os.environ, PYTHONPATH=ROOT)
CLI = [sys.executable, "-m", "codeswarm"]

# ------------------------------------------------------------- gaps
out("QUIET PERIODS (%s)" % a.a)
ev, _ = load_many([a.a], cfg, a.cache_dir, refresh=False)
G = 14
cev, tmap = compress_gaps(ev, G)
gaps = [cev[i + 1].date - cev[i].date for i in range(len(cev) - 1)]
ok &= check("order kept, same events", [e.path for e in cev] == [e.path for e in ev], "%d events" % len(cev))
ok &= check("no gap longer than %d days" % G, max(gaps) <= G * DAY_MS, "longest %.1f days" % (max(gaps) / DAY_MS))
ok &= check("real dates recovered exactly", all(tmap.real(c.date) == o.date for c, o in zip(cev, ev)),
            "%d quiet periods shortened" % len(tmap.skips))
f_before = estimate_frames(ev, cfg)
f_after = estimate_frames(cev, cfg)
ok &= check("fewer frames", f_after < f_before, "%d -> %d frames" % (f_before, f_after))
sw = Swarm(cev, dict(cfg, color_rules=[]), seed=1, time_map=tmap)
mono, last, notes, expect = True, -1, 0, 0
while not sw.done:
    expect += 1 if tmap.skips_between(sw.prev_date, sw.prev_date + sw.update_delta) else 0
    sw.step()
    r = tmap.real(sw.prev_date)
    mono &= r >= last
    last = r
    notes += 1 if sw.last_skip and sw.last_skip[0] == sw.frame else 0
ok &= check("on-screen date never goes backwards", mono, "")
ok &= check("'... later' note at each jump", notes == expect and notes > 0,
            "%d notes for %d frames with a jump (%d jumps)" % (notes, expect, len(tmap.skips)))

# ------------------------------------------------------------- duration
out("DURATION")
for secs in (8, 20):
    mp4 = unique_path(os.path.join(a.workdir, "dur%d.mp4" % secs))
    subprocess.run(CLI + [a.a, "--cache-dir", a.cache_dir, "--offline", "--avatars", "none",
                          "--max-gap", "14", "--duration", str(secs), "--linger", "1", "-o", mp4],
                   env=ENV, check=True, stdout=subprocess.DEVNULL)
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4],
                             stdout=subprocess.PIPE, check=True).stdout)
    ok &= check("--duration %d" % secs, abs(d - secs) <= 1.0, "video is %.2f s" % d)

# ------------------------------------------------------------- cards
out("INTRO AND CREDITS")
short = [e for e in ev if e.date <= ev[0].date + 60 * DAY_MS]
c2 = dict(cfg, color_rules=[])
plain = []
run_headless(short, c2, frame_callback=lambda n, img: plain.append(img.copy()))
spec = ShowSpec(c2, title="Test title", subtitle=["line one", "line two"],
                credits=[("Somebody", 10), ("Somebody Else", 3)], intro_seconds=2, credits_seconds=1)
carded = []
run_headless(short, c2, frame_callback=lambda n, img: carded.append(img.copy()), spec=spec)
ni, nc = spec.intro_frames, spec.credits_frames
ok &= check("frame count = intro + swarm + credits", len(carded) == ni + len(plain) + nc,
            "%d = %d + %d + %d" % (len(carded), ni, len(plain), nc))
same = all(np.array_equal(x, y) for x, y in zip(carded[ni:ni + len(plain)], plain))
ok &= check("swarm frames identical with or without cards", same, "%d frames compared" % len(plain))
h, w = c2["height"], c2["width"]
mid = carded[ni // 2][int(h * 0.3):int(h * 0.6), int(w * 0.3):int(w * 0.7)]
ok &= check("intro shows the title", (mid.max(axis=2) > 100).sum() > 200, "")
ok &= check("intro fades in from black", carded[0].max() < carded[ni // 2].max(), "")
cr = carded[ni + len(plain) + nc // 2]
ok &= check("credits frame has text", (cr.max(axis=2) > 100).sum() > 200, "")

# ------------------------------------------------------------- several repositories
out("SEVERAL REPOSITORIES (%s + %s)" % (a.a, a.b))
ea, _ = load_many([a.a], cfg, a.cache_dir, refresh=False)
eb, _ = load_many([a.b], cfg, a.cache_dir, refresh=False)
both, infos = load_many([a.a, a.b], cfg, a.cache_dir, refresh=False)
ok &= check("events = sum of both", len(both) == len(ea) + len(eb), "%d = %d + %d" % (len(both), len(ea), len(eb)))
ok &= check("chronological", all(both[i].date <= both[i + 1].date for i in range(len(both) - 1)), "")
labs = [i["label"] for i in infos]
pa = set(e.path for e in both if e.repo == labs[0])
pb = set(e.path for e in both if e.repo == labs[1])
ok &= check("paths prefixed, no collisions", not (pa & pb) and all(p.startswith(labs[0] + "/") for p in pa),
            "%s: %d files, %s: %d files" % (labs[0], len(pa), labs[1], len(pb)))
_, pp_a, _ = build_people(ea, cfg)
_, pp_b, _ = build_people(eb, cfg)
_, pp, _ = build_people(both, cfg)
ok &= check("people merged across repositories", len(pp) <= len(pp_a) + len(pp_b),
            "%d + %d -> %d" % (len(pp_a), len(pp_b), len(pp)))
rules = repo_rules(both)
sw = Swarm(both, dict(cfg, color_rules=rules), seed=1)
colour_of = {r["repo"]: list(r["color"]) for r in rules}
for _ in range(400):
    if sw.done:
        break
    sw.step()
f = sw.files
right = all(list(f.color[i]) == colour_of[labs[0] if sw.file_names[i].startswith(labs[0] + "/") else labs[1]]
            for i in range(f.n))
ok &= check("--colors repo: each file has its repo colour", right, "%d files checked" % f.n)

# ------------------------------------------------------------- failures
out("CLEAN FAILURES")
newdir = unique_path(os.path.join(a.workdir, "new_folder"))
p = subprocess.run(CLI + [a.a, "--cache-dir", a.cache_dir, "--offline", "--avatars", "none", "--max-frames", "5",
                          "-o", os.path.join(newdir, "x.mp4")], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
ok &= check("-o into a folder that does not exist", p.returncode == 0 and os.path.isfile(os.path.join(newdir, "x.mp4")), "")
p = subprocess.run(CLI + [a.a, "--cache-dir", a.cache_dir, "--offline", "--avatars", "none", "--max-frames", "5",
                          "--encoder-preset", "no-such-preset", "-o", unique_path(os.path.join(a.workdir, "bad.mp4"))],
                   env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
err = p.stderr.decode("utf-8", "replace")
ok &= check("ffmpeg error: message, no traceback", p.returncode == 1 and "Traceback" not in err and "WARNING" in err,
            "rc=%d" % p.returncode)

out("RESULT: %s" % ("PASS" if ok else "FAIL"))
rp = unique_path(a.report)
os.makedirs(os.path.dirname(os.path.abspath(rp)), exist_ok=True)
open(rp, "w", encoding="ascii").write("\n".join(L) + "\n")
print("Report: %s" % rp)
sys.exit(0 if ok else 1)
