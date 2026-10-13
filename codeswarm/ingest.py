"""Turn a repository into a sorted list of file events.

An event is (date_ms, author, path, status, commit), the same information
code_swarm's XML carried (filename, date, author) plus the change status
and commit id.  No intermediate XML: we read `git log` directly.
"""

import fnmatch
import gzip
import hashlib
import json
import os
import re
import subprocess
import xml.sax
from collections import namedtuple

from .util import say, warn

# author = display identity (after merging); name/email = raw values from git
# kind: the real file path when path is a folder (--folders), for the colours
Event = namedtuple("Event", "date author path status commit email name repo kind", defaults=("", "", "", ""))
CACHE_VERSION = "v3"          # v3: commit date read too (impossible author dates)

AUTHOR_DATE_SPAN = 10 * 365 * 86400  # an author date this far before the commit date is a broken clock
_URL_RE = re.compile(r"^(https?://|git@|ssh://|git://)")
_SHORT_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")   # owner/repo


# ---------------------------------------------------------------------------
# git plumbing
# ---------------------------------------------------------------------------
def _git(args, cwd=None, check=True):
    proc = subprocess.run(["git"] + args, cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)
    if check and proc.returncode != 0:
        raise RuntimeError("git %s failed:\n%s" % (" ".join(args),
                           proc.stderr.decode("utf-8", "replace")))
    return proc.stdout


def git_available():
    try:
        _git(["--version"])
        return True
    except (OSError, RuntimeError):
        return False


def _slug(url):
    s = re.sub(r"^(https?://|git@|ssh://|git://)", "", url)
    s = re.sub(r"\.git$", "", s.rstrip("/"))
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", s)
    return s[:80]


def resolve_source(source, cache_dir, refresh=True):
    """Return (git_dir_or_worktree, label) for a URL, owner/repo or local path."""
    if os.path.isdir(source):
        top = _git(["rev-parse", "--show-toplevel"], cwd=source, check=False).strip()
        if not top:
            # maybe a bare repository
            _git(["rev-parse", "--git-dir"], cwd=source)
            return os.path.abspath(source), os.path.basename(os.path.abspath(source))
        top = top.decode("utf-8")
        return top, os.path.basename(top)

    if _SHORT_RE.match(source) and not os.path.exists(source):
        url = "https://github.com/%s.git" % source
    elif _URL_RE.match(source):
        url = source
    else:
        raise ValueError("not a directory, URL or owner/repo: %s" % source)

    repos = os.path.join(cache_dir, "repos")
    os.makedirs(repos, exist_ok=True)
    dest = os.path.join(repos, _slug(url) + ".git")
    if os.path.isdir(dest):
        if refresh:
            say("Updating cached clone: %s" % dest)
            _git(["fetch", "--quiet", "--prune", "origin",
                  "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*"], cwd=dest)
    else:
        say("Cloning (history only, no file contents): %s" % url)
        # Blobless partial clone: commits + trees, no file contents.
        # --name-status only needs trees, so this is enough and much faster.
        _git(["clone", "--quiet", "--bare", "--filter=blob:none", url, dest])
    return dest, _slug(url).split("_")[-1]


def head_commit(repo, branch=None):
    return _git(["rev-parse", branch or "HEAD"], cwd=repo).decode("ascii").strip()


# ---------------------------------------------------------------------------
# Event extraction
# ---------------------------------------------------------------------------
def build_log_args(opts):
    args = ["-c", "core.quotepath=off", "log", "-z", "--name-status",
            "--use-mailmap", "--no-merges",
            "--format=%x1e%H%x1f%at%x1f%aN%x1f%aE%x1f%ct"]
    if opts.get("renames") == "legacy":
        args.append("--no-renames")
    elif opts.get("_partial_clone"):
        # Exact renames only: inexact detection would read file contents,
        # which a blobless clone does not have (git would fetch them one
        # by one from the server - very slow).
        args.append("-M100%")
    else:
        args.append("-M")
    if opts.get("since"):
        args.append("--since=%s" % opts["since"])
    if opts.get("until"):
        args.append("--until=%s" % opts["until"])
    args.append(opts.get("branch") or "HEAD")
    return args


def parse_log(raw, opts):
    """Parse `git log -z --name-status --format=<RS>H<US>at<US>aN<US>aE<US>ct` output.

    The animation uses the author date (when the change was written), as the
    original did.  Some histories hold impossible author dates from a machine
    with a broken clock (1970, or decades ahead); when the author date is more
    than a day after the commit date, or more than AUTHOR_DATE_SPAN before it,
    the commit date (when the change was applied) is used instead."""
    author_key = opts.get("author_key", "name")
    renames = opts.get("renames", "new")
    include = opts.get("include") or []
    exclude = opts.get("exclude") or []

    def keep(path):
        if include and not any(fnmatch.fnmatch(path, p) for p in include):
            return False
        if exclude and any(fnmatch.fnmatch(path, p) for p in exclude):
            return False
        return True

    events = []
    bad_dates = []
    text = raw.decode("utf-8", "replace")
    for chunk in text.split("\x1e"):
        if not chunk:
            continue
        parts = chunk.split("\0")
        header = parts[0].split("\x1f")
        if len(header) == 4:                    # old format (no commit date)
            header = header + [header[1]]
        if len(header) != 5:
            warn("skipping malformed commit header: %r" % parts[0][:80])
            continue
        sha, at, name, email, ct = header
        a_s, c_s = int(at), int(ct or at)
        if a_s > c_s + 86400 or a_s < c_s - AUTHOR_DATE_SPAN:
            bad_dates.append((a_s, sha))
            a_s = c_s
        date_ms = a_s * 1000
        author = email if author_key == "email" else name
        toks = parts[1:]
        if toks and toks[0].startswith("\n"):
            toks[0] = toks[0][1:]
        i = 0
        while i < len(toks):
            status = toks[i]
            if not status:
                i += 1
                continue
            code = status[0]
            if code in "RC":
                old, new = toks[i + 1], toks[i + 2]
                i += 3
                paths = [new] if renames == "new" or code == "C" else [old, new]
            else:
                paths = [toks[i + 1]]
                i += 2
            for p in paths:
                if keep(p):
                    events.append(Event(date_ms, author, p, code, sha, email, name))
    # git --since/--until filter on the COMMITTER date; the animation uses
    # the AUTHOR date, so trim exactly here (rebased commits keep an older
    # author date and would otherwise leak in).
    lo = _date_ms(opts.get("since"))
    hi = _date_ms(opts.get("until"))
    if lo is not None or hi is not None:
        events = [e for e in events
                  if (lo is None or e.date >= lo) and (hi is None or e.date <= hi)]
    if bad_dates:
        import datetime
        lo, hi = min(a for a, _ in bad_dates), max(a for a, _ in bad_dates)
        fmt = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d")
        say("Dates    : %d commit%s had an impossible author date (%s ... %s); the commit date is used"
            % (len(bad_dates), "s" if len(bad_dates) > 1 else "", fmt(lo), fmt(hi)))
    # stable chronological order (git gives newest first)
    events.sort(key=lambda e: e.date)
    return events


def _date_ms(text):
    """ISO date (YYYY-MM-DD, optional time) -> ms since epoch UTC, else None."""
    if not text:
        return None
    import datetime
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S"):
        try:
            d = datetime.datetime.strptime(text.strip(), fmt).replace(tzinfo=datetime.timezone.utc)
            return int(d.timestamp() * 1000)
        except ValueError:
            pass
    warn("date %r is not YYYY-MM-DD; filtering by git's committer date only" % text)
    return None


def _cache_key(repo_label, head, opts):
    relevant = {k: opts.get(k) for k in
                ("author_key", "renames", "since", "until", "branch", "include", "exclude",
                  "_partial_clone")}
    relevant["_v"] = CACHE_VERSION
    blob = json.dumps(relevant, sort_keys=True).encode("utf-8")
    return "%s_%s_%s" % (repo_label, head[:12], hashlib.sha1(blob).hexdigest()[:8])


def load_events(source, opts, cache_dir, use_cache=True, refresh=True):
    """Main entry: source -> (events, info dict)."""
    if source.lower().endswith(".xml") and os.path.isfile(source):
        events = read_legacy_xml(source)
        return events, {"source": source, "kind": "legacy-xml", "cached": False, "meta": empty_meta()}

    repo, label = resolve_source(source, cache_dir, refresh=refresh)
    head = head_commit(repo, opts.get("branch"))
    partial = _git(["config", "--get", "remote.origin.partialclonefilter"],
                   cwd=repo, check=False).strip() != b""
    log_opts = dict(opts, _partial_clone=partial)
    ev_dir = os.path.join(cache_dir, "events")
    os.makedirs(ev_dir, exist_ok=True)
    cache_file = os.path.join(ev_dir, _cache_key(label, head, log_opts) + ".jsonl.gz")

    meta = load_meta(repo, head, label, ev_dir, opts, use_cache)
    if use_cache and os.path.isfile(cache_file):
        events = read_event_cache(cache_file)
        return events, {"source": source, "repo": repo, "head": head, "meta": meta,
                        "kind": "git", "cached": True, "cache_file": cache_file}

    raw = _git(build_log_args(log_opts), cwd=repo)
    events = parse_log(raw, opts)
    write_event_cache(cache_file, events)
    return events, {"source": source, "repo": repo, "head": head, "meta": meta,
                    "kind": "git", "cached": False, "cache_file": cache_file}


# ---------------------------------------------------------------------------
# Commit details: subject lines and release tags (both cheap: no file contents)
# ---------------------------------------------------------------------------
META_VERSION = "m1"


def empty_meta():
    return {"subjects": {}, "tags": []}


def read_meta(repo, branch=None):
    """{"subjects": {sha: first line of the message}, "tags": [[name, sha, date_ms]]}"""
    raw = _git(["-c", "core.quotepath=off", "log", "--no-merges", "-z", "--format=%H%x1f%s",
                branch or "HEAD"], cwd=repo)
    subjects = {}
    for rec in raw.decode("utf-8", "replace").split("\0"):
        rec = rec.strip("\n")
        if "\x1f" in rec:
            sha, subj = rec.split("\x1f", 1)
            subjects[sha] = subj.strip()
    tags = []
    raw = _git(["for-each-ref", "--format=%(refname:short)%1f%(objectname)%1f%(*objectname)%1f%(creatordate:unix)",
                "refs/tags"], cwd=repo, check=False)
    for line in raw.decode("utf-8", "replace").splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4 or not parts[3].strip().lstrip("-").isdigit():
            continue
        name, obj, peeled, date = parts
        tags.append([name, peeled or obj, int(date) * 1000])
    tags.sort(key=lambda t: (t[2], t[0]))
    return {"subjects": subjects, "tags": tags}


def load_meta(repo, head, label, ev_dir, opts, use_cache=True):
    """Commit subjects and tags, cached next to the events (never fatal)."""
    path = os.path.join(ev_dir, "%s_%s_%s_%s.json.gz" % (label, head[:12], META_VERSION,
                                                         hashlib.sha1(str(opts.get("branch")).encode()).hexdigest()[:6]))
    if use_cache and os.path.isfile(path):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            pass
    try:
        meta = read_meta(repo, opts.get("branch"))
    except RuntimeError as exc:
        warn("commit messages / tags not available: %s" % str(exc).splitlines()[0])
        return empty_meta()
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=True)
    os.replace(tmp, path)
    return meta


def merge_meta(infos, prefix):
    """One meta dict for several sources; tag names get the repo label when prefixed."""
    out = empty_meta()
    for inf in infos:
        m = inf.get("meta") or empty_meta()
        out["subjects"].update(m["subjects"])
        for name, sha, date in m["tags"]:
            out["tags"].append([("%s %s" % (inf["label"], name)) if prefix else name, sha, date])
    out["tags"].sort(key=lambda t: (t[2], t[0]))
    return out


def repo_label(source):
    """Short name for a source: 'flask' for pallets/flask or a URL, folder name for a path."""
    s = source.rstrip("/\\")
    if s.lower().endswith(".xml"):
        s = s[:-4]
    s = re.sub(r"\.git$", "", s)
    return re.split(r"[/\\:]", s)[-1] or s


def load_many(sources, opts, cache_dir, use_cache=True, refresh=True, prefix=None):
    """Load several sources into one chronological event list.

    Every event gets repo=<label>.  With more than one source the paths are
    prefixed with the label ("flask/src/app.py") so files from different
    repositories never collide; prefix=False turns that off.
    Returns (events, infos) where infos is one dict per source."""
    labels = []
    for src in sources:
        lab = repo_label(src)
        if lab in labels:                       # two repos with the same name
            lab = re.sub(r"[^A-Za-z0-9_.-]+", "_", src.rstrip("/"))[-40:]
        labels.append(lab)
    if prefix is None:
        prefix = len(sources) > 1
    allev, infos = [], []
    for src, lab in zip(sources, labels):
        ev, info = load_events(src, opts, cache_dir, use_cache=use_cache, refresh=refresh)
        info = dict(info, label=lab, events=len(ev))
        infos.append(info)
        if prefix:
            allev.extend(e._replace(repo=lab, path=lab + "/" + e.path) for e in ev)
        else:
            allev.extend(e._replace(repo=lab) for e in ev)
    allev.sort(key=lambda e: e.date)            # stable: keeps each repo's order on ties
    if infos:
        infos[0]["meta_all"] = merge_meta(infos, prefix)
    return allev, infos


def write_event_cache(path, events):
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(list(e)[:8], ensure_ascii=True) + "\n")
    os.replace(tmp, path)


def read_event_cache(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [Event(*json.loads(line)) for line in fh if line.strip()]


# ---------------------------------------------------------------------------
# Legacy XML (code_swarm <file_events>) - for comparison with the old tool
# ---------------------------------------------------------------------------
class _XmlHandler(xml.sax.ContentHandler):
    def __init__(self):
        super().__init__()
        self.events = []

    def startElement(self, name, attrs):
        if name == "event":
            who = attrs.get("author") or ""
            email = who if "@" in who else ""
            self.events.append(Event(int(attrs.get("date")), who,
                                     attrs.get("filename"), "?", "", email, who))


def read_legacy_xml(path):
    h = _XmlHandler()
    xml.sax.parse(path, h)
    h.events.sort(key=lambda e: e.date)
    return h.events


def write_legacy_xml(path, events):
    """Write events in code_swarm's XML format (for the old Java tool)."""
    from xml.sax.saxutils import quoteattr
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0"?>\n<file_events>\n')
        for e in events:
            fh.write('\t<event filename=%s date="%d" author=%s />\n'
                     % (quoteattr("/" + e.path), e.date, quoteattr(e.author)))
        fh.write("</file_events>\n")


def summarize(events):
    commits = set(e.commit for e in events)
    authors = set(e.author for e in events)
    files = set(e.path for e in events)
    status = {}
    for e in events:
        status[e.status] = status.get(e.status, 0) + 1
    first = events[0].date if events else None
    last = events[-1].date if events else None
    return {"events": len(events), "commits": len(commits), "authors": len(authors),
            "files": len(files), "status": status, "first_ms": first, "last_ms": last}
