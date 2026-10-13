"""P11 gate: impossible author dates, robots sharing a person's address, avatar limit.

Usage:
  python tools/p11_check.py [--workdir p11_work] [--report p11_report.txt] [--source owner/repo --cache-dir DIR]

Builds its own small git repository in the work folder (needs git):
  - ordinary commits in 2020
  - one commit whose author clock said 1970, one whose author clock said 2085
  - "Fengguang Wu" and "kbuild test robot" sending from the same address
--source additionally runs the date rule on a real cached repository.
ASCII output; the report and work folders are never overwritten.
"""
import argparse
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from codeswarm.config import build_config            # noqa: E402
from codeswarm.identity import build_people          # noqa: E402
from codeswarm.ingest import load_events, load_many  # noqa: E402
from codeswarm.util import unique_path               # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--workdir", default="p11_work")
ap.add_argument("--report", default="p11_report.txt")
ap.add_argument("--source", default=None)
ap.add_argument("--cache-dir", default=None)
a = ap.parse_args()
L = []


def out(m):
    m = str(m).encode("ascii", "backslashreplace").decode("ascii")
    print(m)
    L.append(m)


def check(name, ok, detail=""):
    out("  [%s] %-46s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


work = unique_path(a.workdir)
repo = os.path.join(work, "fixture")
os.makedirs(repo)


def git(*args, env=None):
    e = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", HOME=work)
    e.update(env or {})
    subprocess.run(["git"] + list(args), cwd=repo, check=True, env=e,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def commit(path, name, email, adate, cdate):
    with open(os.path.join(repo, path), "a") as fh:
        fh.write("x\n")
    git("add", path)
    git("commit", "-q", "-m", "change " + path,
        env={"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": adate,
             "GIT_COMMITTER_NAME": "Maintainer", "GIT_COMMITTER_EMAIL": "m@example.org",
             "GIT_COMMITTER_DATE": cdate})


git("init", "-q", "-b", "main")
commit("a.c", "Alice", "alice@example.org", "2020-01-01T10:00:00", "2020-01-01T10:00:00")
commit("b.c", "Bob", "bob@example.org", "1970-01-01T00:00:01", "2020-01-02T10:00:00")       # broken clock
commit("c.c", "Fengguang Wu", "fengguang.wu@example.org", "2020-01-03T10:00:00", "2020-01-03T10:00:00")
commit("d.c", "kbuild test robot", "fengguang.wu@example.org", "2020-01-04T10:00:00", "2020-01-04T10:00:00")
commit("e.c", "Carol", "carol@example.org", "2085-06-18T15:57:00", "2020-01-05T10:00:00")  # clock decades ahead
commit("f.c", "Dave", "dave@example.org", "2019-06-01T10:00:00", "2020-01-06T10:00:00")      # ordinary late merge

ok = True
cfg = build_config("default")
cache = os.path.join(work, "cache")
ev, _ = load_events(repo, cfg, cache, refresh=False)
years = sorted({int(e.date // 1000 // 86400 // 365.25) + 1970 for e in ev})
ok &= check("no event before 2019 or after 2020", years and years[0] >= 2019 and years[-1] <= 2020,
            "years %s" % years)
by = {e.path: e.date for e in ev}
day = 86400000
ok &= check("1970 author date -> commit date", abs(by["b.c"] - 1577959200000) < day)
ok &= check("2085 author date -> commit date", abs(by["e.c"] - 1578218400000) < day)
ok &= check("an ordinary late merge keeps its author date", by["f.c"] < 1577836800000, "authored mid-2019")

ev2, people, rep = build_people(ev, cfg)
names = sorted(people)
ok &= check("real person kept although a robot shares the address", "Fengguang Wu" in people, ", ".join(names))
ok &= check("the robot is hidden", "kbuild test robot" in rep["dropped"] and len(ev2) == len(ev) - 1,
            "hidden: %s" % rep["dropped"])

# avatar limit: only the N most active people get a picture
from codeswarm.avatars import AvatarStore   # noqa: E402
pics = os.path.join(work, "pics")
os.makedirs(pics)
import zlib, struct   # noqa: E401,E402


def tiny_png(path):
    raw = b"\x00\xff\x00\x00\xff"
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    open(path, "wb").write(data)


tiny_png(os.path.join(pics, "default.png"))
store = AvatarStore(dict(cfg, avatars="local", local_avatar_dir=pics, avatar_limit=2), cache, offline=True)
got = store.prefetch(people, progress=False)
ok &= check("--avatar-limit 2: two pictures", len(got) == 2, "%d of %d people" % (len(got), len(people)))
store = AvatarStore(dict(cfg, avatars="local", local_avatar_dir=pics, avatar_limit=0), cache, offline=True)
got = store.prefetch(people, progress=False)
ok &= check("--avatar-limit 0: everyone", len(got) == len(people), "%d of %d people" % (len(got), len(people)))

if a.source:
    evs, _ = load_many([a.source], cfg, a.cache_dir, refresh=False)
    lo, hi = evs[0].date, evs[-1].date
    import datetime
    f = lambda ms: datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%d")
    out("  %s: span %s -> %s" % (a.source, f(lo), f(hi)))

out("RESULT: %s" % ("PASS" if ok else "FAIL"))
rp = unique_path(a.report)
open(rp, "w", encoding="ascii").write("\n".join(L) + "\n")
print("Report: %s" % rp)
sys.exit(0 if ok else 1)
