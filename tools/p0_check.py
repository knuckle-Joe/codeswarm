"""P0 gate: check codeswarm ingest against independent git queries.

Usage (from the codeswarm_py folder):
    python tools/p0_check.py SOURCE [SOURCE ...] [--cache-dir DIR] [--report FILE]

SOURCE = local repository folder, GitHub URL or owner/repo.

For each source it compares what codeswarm extracted with numbers
obtained from separate, differently-formatted git commands:
  - commit count, author set, file-touch count, rename count, date span
  - cache round trip (second load must be identical)
  - legacy recipe (the Stack Exchange git log + convert_logs.py path[2:]
    parsing) to show what the old pipeline got wrong.
Console and report are pure ASCII. The report never overwrites an
existing file: report.txt -> report_1.txt -> report_2.txt ...
"""

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from codeswarm.ingest import load_events, resolve_source, summarize   # noqa: E402
from codeswarm.config import DEFAULTS                                   # noqa: E402
from codeswarm.util import default_cache_dir, unique_path               # noqa: E402

LINES = []


def out(msg=""):
    text = str(msg).encode("ascii", "backslashreplace").decode("ascii")
    print(text)
    LINES.append(text)


def git(repo, *args):
    p = subprocess.run(["git", "-c", "core.quotepath=off"] + list(args), cwd=repo,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8", "replace"))
    return p.stdout.decode("utf-8", "replace")


def check(name, ok, detail):
    out("  [%s] %-28s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


def run_one(source, cache_dir):
    out("=" * 72)
    out("SOURCE: %s" % source)
    opts = dict(DEFAULTS)
    events, info = load_events(source, opts, cache_dir, use_cache=False)
    repo = info["repo"]
    partial = subprocess.run(["git", "config", "--get", "remote.origin.partialclonefilter"],
                             cwd=repo, stdout=subprocess.PIPE).returncode == 0
    rename_flag = "-M100%" if partial else "-M"
    s = summarize(events)
    out("  extracted: %d events, %d commits, %d authors, %d files"
        % (s["events"], s["commits"], s["authors"], s["files"]))

    # Independent query: newline format, --name-only, plain parsing.
    raw = git(repo, "log", "--no-merges", "--use-mailmap", rename_flag, "--name-only",
              "--format=@@%H|%at|%aN", "HEAD")
    commits_with_files = set()
    authors = set()
    touches = 0
    dates = []
    cur = None
    cur_has = False
    for line in raw.splitlines():
        if line.startswith("@@"):
            sha, at, nm = line[2:].split("|", 2)
            cur = (sha, int(at) * 1000, nm)
            continue
        if line.strip() and cur:
            touches += 1
            commits_with_files.add(cur[0])
            authors.add(cur[2])
            dates.append(cur[1])
    all_commits = int(git(repo, "rev-list", "--count", "--no-merges", "HEAD").strip())
    merges = int(git(repo, "rev-list", "--count", "--merges", "HEAD").strip())

    ok = True
    ok &= check("file touches", touches == s["events"], "git=%d ours=%d" % (touches, s["events"]))
    ok &= check("commits with files", len(commits_with_files) == s["commits"],
                "git=%d ours=%d (non-merge total %d, merges skipped %d)"
                % (len(commits_with_files), s["commits"], all_commits, merges))
    ours_auth = set(e.author for e in events)
    ok &= check("author set", authors == ours_auth,
                "git=%d ours=%d diff=%s" % (len(authors), len(ours_auth),
                                            sorted(authors ^ ours_auth)[:5]))
    ok &= check("date span", (min(dates), max(dates)) == (s["first_ms"], s["last_ms"]),
                "first/last match" if dates else "no dates")
    sorted_ok = all(events[i].date <= events[i + 1].date for i in range(len(events) - 1))
    ok &= check("chronological order", sorted_ok, "")

    ns = git(repo, "log", "--no-merges", rename_flag, "--name-status", "--format=", "HEAD")
    git_r = sum(1 for l in ns.splitlines() if l[:1] == "R")
    ok &= check("renames", git_r == s["status"].get("R", 0),
                "git=%d ours=%d" % (git_r, s["status"].get("R", 0)))

    ev2, info2 = load_events(source, opts, cache_dir, use_cache=True, refresh=False)
    ok &= check("cache round trip", info2.get("cached") and ev2 == events,
                "from cache=%s identical=%s" % (info2.get("cached"), ev2 == events))

    non_ascii = sorted(a for a in ours_auth if any(ord(c) > 127 for c in a))
    out("  info: authors with non-ASCII names: %d %s" % (len(non_ascii), non_ascii[:3]))

    # Legacy recipe: the git log from the Stack Exchange answer, parsed the
    # way convert_logs.py does it (path = line[2:]).
    legacy = git(repo, "log", "--name-status",
                 "--pretty=format:%n------------------------------------------------------------------------%nr%h | %ae | %ai (%aD) | x lines%nChanged paths:",
                 "HEAD")
    leg_paths = []
    leg_authors = set()
    for line in legacy.splitlines():
        if line.startswith("r") and " | " in line:
            leg_authors.add(line.split(" | ")[1])
        elif re.match(r"[ACDMRTUX][0-9]*\t", line):
            leg_paths.append(line[2:].replace('"', ""))
    garbled = [p for p in leg_paths if "\t" in p]
    out("  legacy recipe: %d events, %d identities (by email); garbled rename paths: %d"
        % (len(leg_paths), len(leg_authors), len(garbled)))
    if garbled:
        out("    example: %r" % garbled[0])
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--cache-dir", default=default_cache_dir())
    ap.add_argument("--report", default="p0_report.txt")
    a = ap.parse_args()
    results = []
    for src in a.sources:
        try:
            results.append((src, run_one(src, a.cache_dir)))
        except Exception as exc:   # report and carry on with the next source
            out("  [FAIL] exception: %s" % exc)
            results.append((src, False))
    out("=" * 72)
    for src, ok in results:
        out("%s  %s" % ("PASS" if ok else "FAIL", src))
    folder = os.path.dirname(os.path.abspath(a.report))
    os.makedirs(folder, exist_ok=True)
    path = unique_path(a.report)
    with open(path, "w", encoding="ascii") as fh:
        fh.write("\n".join(LINES) + "\n")
    print("Report: %s" % path)
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
