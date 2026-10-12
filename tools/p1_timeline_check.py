"""P1 gate part 1: frame-by-frame bookkeeping vs the instrumented Java run.

Usage: python tools/p1_timeline_check.py EVENTS.xml JAVA_LOG CONFIG [--report FILE]

JAVA_LOG lines: F frame prevDate eventsThisFrame livingNodes livingPeople livingEdges maxTouches
Compares, for every frame: date, events consumed, living files/people/edges,
maxTouches. Physics positions are random in both, so they are not compared.
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _deps import require  # noqa: E402
require("numpy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from codeswarm.config import build_config
from codeswarm.ingest import read_legacy_xml
from codeswarm.sim import Swarm
from codeswarm.util import unique_path

ap = argparse.ArgumentParser()
ap.add_argument("xml"); ap.add_argument("javalog"); ap.add_argument("config")
ap.add_argument("--report", default="p1_timeline_report.txt")
a = ap.parse_args()
java = [list(map(int, l.split()[1:])) for l in open(a.javalog, encoding="latin-1") if l.startswith("F ")]
cfg = build_config(config_path=a.config, java_escapes=True)
sw = Swarm(read_legacy_xml(a.xml), cfg, seed=1)
ours = []
while True:
    sw.step()
    ours.append([sw.frame, sw.prev_date, sw.events_this_frame] + list(sw.living_counts) + [sw.max_touches])
    if sw.done:
        break
lines = ["frames: java=%d ours=%d" % (len(java), len(ours))]
names = ["frame", "date", "events", "files", "people", "edges", "maxTouches"]
bad = {n: 0 for n in names}
first = {}
for j, o in zip(java, ours):
    for k, n in enumerate(names):
        if j[k] != o[k]:
            bad[n] += 1
            first.setdefault(n, (j[0], j[k], o[k]))
for n in names:
    lines.append("  %-11s mismatched frames: %5d   first: %s" % (n, bad[n], first.get(n, "-")))
ok = len(java) == len(ours) and not any(bad.values())
lines.append("RESULT: %s" % ("PASS" if ok else "FAIL"))
path = unique_path(a.report)
os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
open(path, "w", encoding="ascii").write("\n".join(lines) + "\n")
print("\n".join(lines)); print("Report:", path)
sys.exit(0 if ok else 1)
