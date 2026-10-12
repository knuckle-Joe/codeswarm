"""People: merge duplicate identities, drop bots, apply aliases.

git history often has one person under several names or emails
("Jane Doe <jane@work>", "jane <jane@home>", "Jane Doe <123+jane@users.noreply.github.com>").
.mailmap is applied by git first; this module then links identities that
share an email, a normalised name, or a GitHub login (from noreply emails),
and shows each group under its most used name.
"""

import fnmatch
import re
import unicodedata
from collections import Counter, defaultdict

_NOREPLY = re.compile(r"^(?:(\d+)\+)?([A-Za-z0-9-]+)@users\.noreply\.github\.com$", re.I)
_GENERIC_EMAIL = re.compile(r"^(root|nobody|none|noreply|no-reply|unknown|user|admin|git|you|your\.?email)@|"
                            r"@(localhost|example\.(com|org)|none|\(none\))$|^$", re.I)
_GENERIC_NAME = {"", "unknown", "root", "admin", "user", "github", "your name", "none", "anonymous",
                 "nobody", "ubuntu", "administrator"}
# fnmatch patterns ("[bot]" itself is handled separately: in fnmatch it is a character class)
BOT_PATTERNS = ["*-bot", "* bot", "*robot", "dependabot*", "renovate*", "pre-commit-ci*", "github-actions*",
                "greenkeeper*", "snyk-bot*", "imgbot*", "allcontributors*", "web-flow"]


def norm_name(name):
    """Casefold, collapse spaces, drop accents: 'Stephane' == 'St\u00e9phane'."""
    n = unicodedata.normalize("NFKD", re.sub(r"\s+", " ", (name or "").strip()))
    return "".join(c for c in n if not unicodedata.combining(c)).casefold()


def github_login(email):
    """Login (and numeric id) from a GitHub noreply email, else (None, None)."""
    m = _NOREPLY.match((email or "").strip())
    if not m:
        return None, None
    return m.group(2), (int(m.group(1)) if m.group(1) else None)


def is_bot(name, email=""):
    n = (name or "").strip().casefold()
    e = (email or "").strip().casefold()
    if n.endswith("[bot]") or "[bot]" in e:
        return True
    for pat in BOT_PATTERNS:
        if fnmatch.fnmatch(n, pat) or fnmatch.fnmatch(e.split("@")[0], pat):
            return True
    return False


class _UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


class Person:
    """One merged identity."""

    def __init__(self, display):
        self.display = display
        self.names = Counter()
        self.emails = Counter()
        self.logins = Counter()
        self.github_ids = set()
        self.events = 0
        self.commit_sample = None     # one commit sha, for API avatar lookups
        self.commit_repo = ""         # ...and the repository it belongs to

    def best_email(self):
        for e, _ in self.emails.most_common():
            if not _GENERIC_EMAIL.search(e) and not github_login(e)[0]:
                return e
        return self.emails.most_common(1)[0][0] if self.emails else ""


def build_people(events, cfg):
    """Return (new_events, people dict display->Person, report dict)."""
    merge = cfg.get("merge_identities", True)
    author_key = cfg.get("author_key", "name")
    aliases = {}
    for a in cfg.get("aliases") or []:
        if "=" in a:
            src, dst = a.split("=", 1)
            aliases[norm_name(src)] = dst.strip()
    excl = [p.casefold() for p in (cfg.get("exclude_authors") or [])]
    drop_bots = cfg.get("exclude_bots", True)

    # raw identity = (name, email) as git gave it (after .mailmap)
    counts = Counter((e.name or e.author, e.email) for e in events)
    uf = _UF()
    by_email, by_name, by_login = {}, {}, {}
    for (name, email) in counts:
        node = (name, email)
        uf.find(node)
        if not merge:
            continue
        nn = norm_name(aliases.get(norm_name(name), name))
        el = (email or "").strip().casefold()
        login, _ = github_login(el)
        keys = []
        if el and not _GENERIC_EMAIL.search(el) and not login:
            keys.append(("e", el))
        if nn and nn not in _GENERIC_NAME:
            keys.append(("n", nn))
        if login:
            keys.append(("n", login.casefold()))       # login often equals a name used elsewhere
            keys.append(("l", login.casefold()))
        for k in keys:
            table = {"e": by_email, "n": by_name, "l": by_login}[k[0]]
            if k[1] in table:
                uf.union(table[k[1]], node)
            else:
                table[k[1]] = node

    groups = defaultdict(list)
    for node in counts:
        groups[uf.find(node)].append(node)

    people = {}
    node_to_display = {}
    for members in groups.values():
        names, emails = Counter(), Counter()
        for (n, e) in members:
            names[n] += counts[(n, e)]
            emails[e] += counts[(n, e)]
        if author_key == "email":
            display = emails.most_common(1)[0][0] or names.most_common(1)[0][0]
        else:
            display = names.most_common(1)[0][0] or emails.most_common(1)[0][0]
        display = unicodedata.normalize("NFC", aliases.get(norm_name(display), display))
        # two different groups could end up with the same display string
        base, k = display, 2
        while display in people:
            display = "%s (%d)" % (base, k)
            k += 1
        p = Person(display)
        p.names, p.emails = names, emails
        for e in emails:
            login, gid = github_login(e)
            if login:
                p.logins[login] += emails[e]
                if gid:
                    p.github_ids.add(gid)
        people[display] = p
        for m in members:
            node_to_display[m] = display

    out = []
    dropped = Counter()
    for e in events:
        disp = node_to_display[(e.name or e.author, e.email)]
        p = people[disp]
        if (drop_bots and any(is_bot(n, em) for n in p.names for em in p.emails)) or \
                any(fnmatch.fnmatch(disp.casefold(), pat) for pat in excl):
            dropped[disp] += 1
            continue
        p.events += 1
        if p.commit_sample is None and e.commit:
            p.commit_sample = e.commit
            p.commit_repo = getattr(e, "repo", "")
        out.append(e._replace(author=disp))
    for d in dropped:
        people.pop(d, None)
    people = {k: v for k, v in people.items() if v.events}

    report = {
        "raw_identities": len(counts),
        "people": len(people),
        "merged_groups": sorted(((p.display, sorted(p.names), sorted(p.emails)) for p in people.values()
                                 if len(p.names) + len(p.emails) > 2), key=lambda t: t[0].casefold()),
        "dropped": dict(dropped),
    }
    return out, people, report
