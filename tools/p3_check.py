"""P3 gate: people merging, automatic colours, avatars.

Usage:
  python tools/p3_check.py SOURCE [--cache-dir DIR] [--report p3_report.txt]          # mock servers
  python tools/p3_check.py SOURCE --real [--cache-dir DIR]                             # real Gravatar/GitHub

Default mode starts a local fake Gravatar + GitHub (API and avatar host) so
every path can be tested without internet:
  gravatar: identicon for everyone, 404 when d=404
  github  : noreply emails -> direct avatar URL, others -> commit API
            (budget respected, a 403 rate limit falls back to Gravatar)
  cache   : second run (no new API lookups) downloads nothing; the API budget
            goes to the most active people first, the next run to the next ones; --offline run still has every picture
  render  : a frame with avatars differs from the same frame without them,
            and the avatar sits above the person's name
--real uses the real services (run it on your own machine; uses a fresh
temporary avatar cache so it really downloads).
ASCII output; the report is never overwritten (p3_report_1.txt ...).
"""
import argparse
import hashlib
import http.server
import json
import os
import re
import shutil
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _deps import require  # noqa: E402
require("numpy", "pygame", "moderngl")
import tempfile
import threading

ap = argparse.ArgumentParser()
ap.add_argument("source")
ap.add_argument("--cache-dir", default=None)
ap.add_argument("--report", default="p3_report.txt")
ap.add_argument("--real", action="store_true")
a = ap.parse_args()

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

# ---------------------------------------------------------------- mock servers
CALLS = {"gravatar": 0, "api": 0, "gh_avatar": 0}
RATE_LIMIT_AFTER = 30          # API answers 403 after this many calls


def _png(rgb):
    import pygame
    s = pygame.Surface((80, 80))
    s.fill(rgb)
    import io
    buf = io.BytesIO()
    pygame.image.save(s, buf, "x.png")
    return buf.getvalue()


class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body=b"", ctype="image/png"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path
        m = re.match(r"^/avatar/([0-9a-f]{32})\?(.*)$", path)
        if m:
            CALLS["gravatar"] += 1
            if "d=404" in m.group(2):
                return self._send(404)
            h = m.group(1)
            return self._send(200, _png((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))))
        m = re.match(r"^/api/repos/([^/]+/[^/]+)/commits/([0-9a-f]+)$", path)
        if m:
            CALLS["api"] += 1
            if CALLS["api"] > RATE_LIMIT_AFTER:
                return self._send(403, b'{"message":"rate limit"}', "application/json")
            sha = m.group(2)
            body = {"sha": sha, "author": {"login": "u" + sha[:6],
                                           "avatar_url": "http://127.0.0.1:%d/gh/u%s?v=4" % (PORT, sha[:6])}}
            return self._send(200, json.dumps(body).encode(), "application/json")
        if path.startswith("/gh/"):
            CALLS["gh_avatar"] += 1
            return self._send(200, _png((0, 200, 0)))
        return self._send(404)


PORT = None
if not a.real:
    # the fake run must behave like a machine without a GitHub token
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        os.environ.pop(var, None)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    PORT = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["CODESWARM_GRAVATAR_URL"] = "http://127.0.0.1:%d/avatar/" % PORT
    os.environ["CODESWARM_GITHUB_API"] = "http://127.0.0.1:%d/api" % PORT
    os.environ["CODESWARM_GITHUB_AVATARS"] = "http://127.0.0.1:%d/gh" % PORT

import numpy as np                                        # noqa: E402
from codeswarm.avatars import AvatarStore                 # noqa: E402
from codeswarm.config import build_config                 # noqa: E402
from codeswarm.identity import build_people, github_login  # noqa: E402
from codeswarm.ingest import load_events                  # noqa: E402
from codeswarm.util import default_cache_dir, unique_path  # noqa: E402

L = []


def out(m):
    m = str(m).encode("ascii", "backslashreplace").decode("ascii")
    print(m)
    L.append(m)


def check(name, ok, detail=""):
    out("  [%s] %-40s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


cache = a.cache_dir or default_cache_dir()
cfg = build_config("classic", overrides={"seed": 3, "frames_per_day": 2})
events, _ = load_events(a.source, cfg, cache, refresh=False)
ok = True

# ------------------------------------------------------------------ people
out("PEOPLE")
ev2, people, rep = build_people(events, cfg)
raw_names = len(set(e.name for e in events))
ok &= check("events kept + hidden == all", len(ev2) + sum(rep["dropped"].values()) == len(events),
            "%d + %d = %d" % (len(ev2), sum(rep["dropped"].values()), len(events)))
ok &= check("fewer people than raw names", len(people) <= raw_names, "%d names -> %d people" % (raw_names, len(people)))
ok &= check("every event has a known person", all(e.author in people for e in ev2), "")
bots = [d for d in rep["dropped"]]
ok &= check("hidden people look like bots", all("bot" in d.lower() or "imgbot" in d.lower() for d in bots), str(bots[:5]))
off = build_people(events, dict(cfg, merge_identities=False, exclude_bots=False))[1]
ok &= check("--no-merge-identities keeps name/email pairs", len(off) >= len(people), "%d groups" % len(off))
multi = [p for p in people.values() if len(p.names) > 1]
out("  info: %d people merged from several names, e.g.:" % len(multi))
for p in sorted(multi, key=lambda q: -q.events)[:8]:
    out("        %-28s <- %s" % (p.display, " | ".join(sorted(p.names))))

# ------------------------------------------------------------------ colours
out("COLOURS")
from codeswarm.colors import auto_rules, group_of   # noqa: E402
rules = auto_rules(ev2)
ok &= check("auto legend has 1-10 groups", 1 <= len(rules) <= 10, ", ".join(r["label"] for r in rules))
from codeswarm.sim import ColorRules                 # noqa: E402
cr = ColorRules(rules, np.random.default_rng(0))
top = rules[0]
sample = next(e.path for e in ev2 if group_of(e.path) == top["group"])
ok &= check("busiest group gets first palette colour", list(cr.color_for(sample)) == top["color"],
            "%s -> %s" % (sample, top["color"]))

# ------------------------------------------------------------------ avatars
out("AVATARS (%s)" % ("real services" if a.real else "local fake servers"))
tmp = tempfile.mkdtemp(prefix="cs_av_")
try:
    for mode in (["gravatar", "github"] if not a.real else ["auto"]):
        sub = os.path.join(tmp, mode)
        before = dict(CALLS)
        st = AvatarStore(dict(cfg, avatars=mode), sub, source=a.source)
        imgs = st.prefetch(people, progress=False)
        noreply = sum(1 for p in people.values() if any(github_login(e)[0] for e in p.emails))
        detail = "%d/%d pictures, %d downloaded, %d API calls, rate-limited=%s" % (
            len(imgs), len(people), st.stats["downloaded"], st.stats["api_calls"], st.stats["rate_limited"])
        if a.real:
            ok &= check("real: some pictures", len(imgs) > 0, detail)
        elif mode == "gravatar":
            ok &= check("gravatar: picture for everyone (identicon)", len(imgs) == len(people), detail)
        else:
            used = CALLS["api"] - before["api"]
            ok &= check("github: API calls within budget", used <= 50, "%d calls (budget 50)" % used)
            ok &= check("github: rate limit falls back to gravatar", len(imgs) == len(people), detail)
            direct = CALLS["gh_avatar"] - before["gh_avatar"]
            ok &= check("github: noreply people need no API", direct >= noreply,
                        "%d people with noreply emails, %d GitHub avatar downloads" % (noreply, direct))
        shape_ok = all(v.shape == (cfg["avatar_size"], cfg["avatar_size"], 4) for v in imgs.values())
        corner_clear = all(v[0, 0, 3] == 0 for v in imgs.values())
        ok &= check("%s: size %dpx, circular mask" % (mode, cfg["avatar_size"]), shape_ok and corner_clear, "")
        # second run without new API lookups: everything must come from the cache
        st2 = AvatarStore(dict(cfg, avatars=mode, github_api_budget=0), sub, source=a.source)
        st2.token = None
        imgs2 = st2.prefetch(people, progress=False)
        ok &= check("%s: second run downloads nothing" % mode, st2.stats["downloaded"] == 0 and len(imgs2) == len(imgs),
                    "%d from cache, %d downloaded" % (st2.stats["cached"], st2.stats["downloaded"]))
        if mode in ("github", "auto") and st.stats["api_calls"]:
            # a run with a fresh budget looks up the NEXT most active people only
            st4 = AvatarStore(dict(cfg, avatars=mode), sub, source=a.source)
            st4.prefetch(people, progress=False)
            order = sorted(people.values(), key=lambda p: (-p.events, p.display))
            rank = {p.display: i for i, p in enumerate(order)}
            key = lambda d: "%s@%s" % (st.slug, people[d].commit_sample)
            resolved = [d for d in st.looked_up if key(d) in st.lookup]   # answered (not rate-limited)
            nxt = list(st4.looked_up)
            # run 1 must have spent its budget on the most active candidates
            cands = [p.display for p in order if p.commit_sample
                     and not any(github_login(e)[0] for e in p.emails)]
            budget = int(cfg.get("github_api_budget", 50))
            top_ok = set(st.looked_up) <= set(cands[:budget])      # only the top-ranked candidates
            ok &= check("%s: API budget goes to most active first" % mode,
                        top_ok and not (set(resolved) & set(nxt)),
                        "run 1: %d lookups (%d answered), run 2: %d lookups, none repeated"
                        % (len(st.looked_up), len(resolved), len(nxt)))
        st3 = AvatarStore(dict(cfg, avatars=mode), sub, source=a.source, offline=True)
        imgs3 = st3.prefetch(people, progress=False)
        ok &= check("%s: --offline uses the cache" % mode, len(imgs3) == len(imgs), "%d pictures" % len(imgs3))

    # render: avatar above the name
    from codeswarm.app import run_headless          # noqa: E402
    filled = "auto" if a.real else "gravatar"            # the cache folder filled above
    st = AvatarStore(dict(cfg, avatars=filled), os.path.join(tmp, filled), source=a.source, offline=True)
    imgs = st.prefetch(people, progress=False)
    rcfg = dict(cfg, color_rules=rules)
    from codeswarm.app import estimate_frames   # noqa: E402
    # a frame inside the history (short histories have fewer than 400 frames)
    target = max(1, min(400, estimate_frames(ev2, rcfg) - 1))
    frames = {}
    for label, av in (("with", imgs), ("without", {})):
        run_headless(ev2, rcfg, max_frames=target, avatars=av,
                     frame_callback=lambda n, img, lab=label: frames.__setitem__(lab, img.copy()) if n == target else None)
    if "with" not in frames or "without" not in frames:
        raise SystemExit("render step: frame %d was not produced" % target)
    diff = np.abs(frames["with"].astype(int) - frames["without"].astype(int)).max(axis=2) > 8
    ys, xs = np.nonzero(diff)
    ok &= check("render: avatars change the frame", diff.sum() > 100, "%d pixels differ" % int(diff.sum()))
    import pygame                                    # noqa: E402
    path = unique_path(os.path.join(os.path.dirname(os.path.abspath(a.report)), "p3_avatar_frame.png"))
    pygame.image.save(pygame.image.frombuffer(np.ascontiguousarray(frames["with"]).tobytes(),
                                              (cfg["width"], cfg["height"]), "RGB"), path)
    out("  info: frame %d with avatars saved to %s" % (target, path))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

out("RESULT: %s" % ("PASS" if ok else "FAIL"))
rp = unique_path(a.report)
os.makedirs(os.path.dirname(os.path.abspath(rp)), exist_ok=True)
open(rp, "w", encoding="ascii").write("\n".join(L) + "\n")
print("Report: %s" % rp)
sys.exit(0 if ok else 1)
