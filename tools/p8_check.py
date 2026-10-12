"""P8 gate: commit messages, ranked-ring details, release tags, name overlap, fonts.

Usage:
  python tools/p8_check.py SOURCE [--crowded SOURCE2] [--cache-dir DIR] [--report p8_report.txt]

SOURCE should have version tags (pallets/flask is a good one).  --crowded is
a busy repository for the name-overlap test (default: SOURCE; a big one such
as ggml-org/llama.cpp shows the difference best).  Both should be cached
(run `codeswarm SOURCE --stats` once).  ASCII output; the report is never
overwritten (p8_report_1.txt ...).
"""
import argparse
import os
import subprocess
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
from codeswarm.ingest import load_many, read_meta                  # noqa: E402
from codeswarm.render import Renderer                              # noqa: E402
from codeswarm.sim import Swarm, select_tags                       # noqa: E402
from codeswarm.util import default_cache_dir, unique_path          # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("source")
ap.add_argument("--crowded", default=None)
ap.add_argument("--cache-dir", default=default_cache_dir())
ap.add_argument("--report", default="p8_report.txt")
a = ap.parse_args()
L = []


def out(m):
    m = str(m).encode("ascii", "backslashreplace").decode("ascii")
    print(m)
    L.append(m)


def check(name, ok, detail=""):
    out("  [%s] %-46s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def prepare(source, **over):
    cfg = build_config("default", overrides=dict({"seed": 5, "avatars": "none"}, **over))
    ev, infos = load_many([source], cfg, a.cache_dir, refresh=False)
    ev, _, _ = build_people(ev, cfg)
    cfg["color_rules"] = auto_rules(ev)
    return cfg, ev, infos


ok = True
cfg, ev, infos = prepare(a.source)
meta = infos[0]["meta_all"]
repo = infos[0].get("repo")
out("source %s: %d events, %d subjects, %d tags" % (a.source, len(ev), len(meta["subjects"]), len(meta["tags"])))

# ---- 1. commit details read from git, checked with different git commands
out("COMMIT DETAILS")
if repo:
    shas = subprocess.run(["git", "rev-list", "--no-merges", "HEAD"], cwd=repo, stdout=subprocess.PIPE).stdout.split()
    ok &= check("one subject per non-merge commit", len(shas) == len(meta["subjects"]),
                "%d commits, %d subjects" % (len(shas), len(meta["subjects"])))
    probe = shas[len(shas) // 2].decode()
    subj = subprocess.run(["git", "show", "-s", "--format=%s", probe], cwd=repo,
                          stdout=subprocess.PIPE).stdout.decode("utf-8", "replace").strip()
    ok &= check("subject text matches git show", meta["subjects"].get(probe) == subj, repr(subj[:50]))
    tags = subprocess.run(["git", "tag"], cwd=repo, stdout=subprocess.PIPE).stdout.split()
    ok &= check("every tag read", len(tags) == len(meta["tags"]), "%d tags" % len(tags))
    again = read_meta(repo)
    ok &= check("cache round trip identical", again == meta)
missing = [e.commit for e in ev if e.commit not in meta["subjects"]]
ok &= check("every animated commit has a subject", not missing, "%d without" % len(set(missing)))

sample = [[n, "x", 0] for n in ("0.1", "v1.2.3", "pkg-2.0rc1", "b1234", "master-abc", "backup/x", "latest")]
got = [t[0] for t in select_tags(sample)]
ok &= check("auto picks version-like tags", got == ["0.1", "v1.2.3", "pkg-2.0rc1"], ", ".join(got))
got = [t[0] for t in select_tags([t for t in sample if t[0] in ("b1234", "master-abc", "latest")])]
ok &= check("auto falls back to build numbers", got == ["b1234"], ", ".join(got))

# ---- 2. simulation: new data is right and changes nothing else
out("SIMULATION")
scfg = sim_cfg(cfg)
plain = Swarm(ev, scfg, seed=5)
sw = Swarm(ev, scfg, seed=5, meta=meta)
same = True
authors_ok = status_ok = True
checked = 0
last = {}
by_commit = {}
for e in ev:
    by_commit.setdefault(e.commit, e.author)
gap = sw._banner_gap
while not sw.done:
    sw.step()
    plain.step()
    for e in sw.events[checked:sw.ev_i]:
        last[e.path] = e
    checked = sw.ev_i
    if sw.frame % 97 == 0:
        same &= bool(np.array_equal(sw.files.pos[:sw.files.n], plain.files.pos[:plain.files.n]) and
                     np.array_equal(sw.people.pos[:sw.people.n], plain.people.pos[:plain.people.n]))
        lo = sw.prev_date - sw.window_ms
        win = {}
        for e in sw.events[:sw.ev_i]:
            if e.date >= lo:
                win.setdefault(e.path, set()).add(e.author)
        for path, fi in list(sw.file_index.items())[:400]:
            authors_ok &= sw.file_authors(fi) == len(win.get(path, ()))
            status_ok &= sw.file_status[fi] == (last[path].status or "?")
ok &= check("swarm identical with and without details", same, "positions every 97 frames")
ok &= check("people per file = brute-force count", authors_ok, "last %d days" % sw.window_days)
ok &= check("last change per file = last event", status_ok)
feed_commits = [c for _, _, c, _ in sw.commit_feed]
ok &= check("commit feed: right person per commit",
            all(sw.person_names[pi] == by_commit[c] for _, pi, c, _ in sw.commit_feed), "%d recent" % len(feed_commits))
ok &= check("every release tag reached", sw.tag_i == len(sw.tags), "%d of %d" % (sw.tag_i, len(sw.tags)))
ok &= check("release banners for the releases", len(sw.bannered) >= 1 if sw.tags else True,
            "%d tags, %d banners" % (len(sw.tags), len(sw.bannered)))

# ---- 3. rendering
out("RENDERING")
ctx = _standalone_context()


def frame_pair(frame, key, on_cfg=None, off_cfg=None, st_on=None, st_off=None):
    """Same swarm frame drawn twice (option on / off)."""
    imgs = []
    for c_, s_ in ((on_cfg or cfg, st_on), (off_cfg or cfg, st_off)):
        r = Renderer(ctx, c_)
        s = Swarm(ev, sim_cfg(c_), seed=5, meta=meta)
        st = initial_state(c_)
        st.update(s_ or {})
        while s.frame < frame:
            s.step()
            if s.frame >= frame - 30:          # names glide over a few frames
                r.draw(s, st)
        r.draw(s, st)
        imgs.append((r.read_rgb().copy(), r, s))
    return imgs


# a frame just after a release banner
sw2 = Swarm(ev, scfg, seed=5, meta=meta)
bframe = None
while not sw2.done and bframe is None:
    sw2.step()
    if sw2.release_banner and sw2.frame == sw2.release_banner[0] + 30:
        bframe = sw2.frame
if bframe:
    (on, _, _), (off, _, _) = frame_pair(bframe, "rel", st_off={"show_releases": False})
    h, w = on.shape[:2]
    band = np.abs(on[: h // 8, w // 3: 2 * w // 3].astype(int) - off[: h // 8, w // 3: 2 * w // 3].astype(int)).max(axis=2)
    ok &= check("release banner top centre", (band > 60).sum() > 300, "frame %d, %d px" % (bframe, (band > 60).sum()))
    hist = np.abs(on[int(h * 0.7):, : w // 2].astype(int) - off[int(h * 0.7):, : w // 2].astype(int)).max(axis=2)
    ok &= check("release marker over the histogram", (hist > 60).sum() > 50, "%d px" % (hist > 60).sum())
else:
    out("  [SKIP] no release in this history")

# subjects: under names and in the ticker
target = min(sw.frame - 5, 3000)
(on, r_on, s_on), (off, _, _) = frame_pair(target, "txt", st_off={"commit_text": False})
h, w = on.shape[:2]
tick = np.abs(on[int(h * 0.8):, w // 2:].astype(int) - off[int(h * 0.8):, w // 2:].astype(int)).max(axis=2)
ok &= check("ticker bottom right", (tick > 60).sum() > 300, "%d px" % (tick > 60).sum())
subj_people = set(r_on._subjects)
labelled = {p for *_, p in r_on.drawn_labels}
ok &= check("subjects drawn under the newest committers", subj_people and subj_people <= labelled,
            "%d people" % len(subj_people))

# status flash + author ticks change the ring
(on, r_on, s_on), (off, _, _) = frame_pair(target, "ring", off_cfg=dict(cfg, status_flash=False, author_ticks=False))
diff = (np.abs(on.astype(int) - off.astype(int)).max(axis=2) > 40)
marks = r_on._pop_marks or []
zone = np.zeros_like(diff)
for _, fi in marks:
    x, y = (s_on.files.pos[fi] * r_on.k).astype(int)
    zone[max(0, y - 60):y + 60, max(0, x - 60):x + 60] = True
near = int((diff & zone).sum())
ok &= check("ring flash / ticks drawn at the ranked files", near > 0 and near >= 0.9 * diff.sum(),
            "%d of %d changed px near rings" % (near, diff.sum()))

# flash colour follows the change: render the frame of a fresh "A" or "D" on a marked file
sw3 = Swarm(ev, scfg, seed=5, meta=meta)
r3 = Renderer(ctx, dict(cfg, author_ticks=False))
st3 = initial_state(cfg)
for k_ in ("show_edges", "draw_names_halos", "draw_names_sharp", "draw_files_fuzzy", "draw_files_jelly",
           "draw_files_sharp", "show_history", "ripples", "commit_text", "show_releases"):
    st3[k_] = False
found = None
while not sw3.done and found is None and sw3.frame < 20000:
    sw3.step()
    if sw3.frame % 3:
        continue
    r3.draw(sw3, st3)
    for _, fi in (r3._pop_marks or []):
        if sw3.file_touch_frame[fi] == sw3.frame and sw3.file_status[fi] in ("A", "D"):
            found = (fi, sw3.file_status[fi])
            break
if found:
    img = r3.read_rgb()
    fi, code = found
    x, y = (sw3.files.pos[fi] * r3.k).astype(int)
    patch = img[max(0, y - 50):y + 50, max(0, x - 50):x + 50].reshape(-1, 3).astype(int)
    lit = patch[patch.max(axis=1) > 80]
    mean = lit.mean(axis=0) if len(lit) else np.zeros(3)
    good = (mean[1] > mean[0]) if code == "A" else (mean[0] > mean[1] * 1.3)
    ok &= check("flash colour: green added / red deleted", good,
                "status %s, mean RGB %d,%d,%d" % (code, mean[0], mean[1], mean[2]))
else:
    out("  [SKIP] no fresh add/delete on a ranked file")

# ---- 4. names do not overlap
out("NAMES")
src = a.crowded or a.source
ccfg, cev, cinf = prepare(src) if a.crowded else (cfg, ev, infos)


def overlap_run(spread):
    r = Renderer(ctx, ccfg)
    s = Swarm(cev, sim_cfg(ccfg), seed=5, meta=cinf[0]["meta_all"])
    st = initial_state(ccfg)
    st["name_spread"] = spread
    pairs = frames = 0
    moves = []
    far = [0.0, 0.0]                         # largest sideways / vertical offset of a name
    prev = {}
    start = min(2000, max(10, len(cev) // 40))
    while not s.done and s.frame < start + 400:
        s.step()
        if s.frame < start:
            continue
        r.draw(s, st)
        lab = [q for q in r.drawn_labels if q[4] >= 100]
        for i in range(len(lab)):
            for j in range(i + 1, len(lab)):
                A, B = lab[i], lab[j]
                if A[5] != B[5] and A[0] < B[2] and B[0] < A[2] and A[1] < B[3] and B[1] < A[3]:
                    pairs += 1
        if spread and r._layout:
            for pi, v in r._layout.items():
                dx, dy = v[0], v[1]
                far[0], far[1] = max(far[0], abs(dx)), max(far[1], abs(dy))
                if pi in prev:
                    moves.append(abs(dx - prev[pi][0]) + abs(dy - prev[pi][1]))
            prev = {pi: v[:2] for pi, v in r._layout.items()}
        frames += 1
    return pairs, frames, (float(np.mean(moves)) if moves else 0.0), far, r


p_off, n_off, _, _, _ = overlap_run(False)
p_on, n_on, move, far, r_on = overlap_run(True)
out("  %s: %d frames; overlapping visible labels: original %d, spread %d" % (src, n_on, p_off, p_on))
ok &= check("overlaps cut by at least 80%", p_on <= max(2, 0.2 * p_off), "%d -> %d" % (p_off, p_on))
ok &= check("labels glide (no jitter)", move < 3.0, "mean move %.2f px per frame" % move)
line = r_on.fonts.bold.get_linesize()
ok &= check("names stay with their avatar", far[0] <= 30 * r_on.k + 1 and far[1] <= 3 * 0.6 * line + 1,
            "farthest %.0f px aside, %.0f px down (subject lines never move a name)" % (far[0], far[1]))

# ---- 5. fonts
out("FONTS")
r = Renderer(ctx, cfg)
F = r.fonts
for text in ("Jiří Podivín", "Przemysław Pawełczyk", "Şahin Çelik",
             "Святослав", "Σωκράτης"):
    f = F._fallback(F.normal, text)
    miss = [ch for ch in set(text) if not ch.isspace() and F._missing(f, ch)]
    ok &= check("all letters drawn: " + text, not miss, "main font" if f is F.normal else "fallback font")
f = F._fallback(F.normal, "苦涩")
cjk = not any(F._missing(f, ch) for ch in "苦涩")
out("  [%s] %-46s %s" % ("PASS" if cjk else "INFO", "CJK name", "fallback font found" if cjk else
                          "no CJK font installed (install noto-fonts-cjk)"))
tex, w_, _ = F.texture("ok \U0001F642 ok", F.normal)
tex2, w2, _ = F.texture("ok ok", F.normal)
ok &= check("emoji without a font is left out (no box)", abs(w_ - w2) <= 2 or not F._missing(F.normal, "\U0001F642"),
            "%d px vs %d px" % (w_, w2))
ok &= check("bundled DejaVu Sans used for names", os.path.basename(F._SANS_FILES[0]) == "DejaVuSans.ttf"
            and os.path.isfile(F._SANS_FILES[0]))
ctx.release()

# ---- 6. documentation
out("DOCUMENTATION")
p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "flags_table.py"), "--check"],
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
ok &= check("README flag table matches the program", p.returncode == 0, p.stdout.decode().strip())
from codeswarm.cli import build_parser                     # noqa: E402
readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
missing = [o for act in build_parser()._actions for o in act.option_strings
           if o.startswith("--") and not o.startswith("--no-") and "`%s`" % o not in readme]
ok &= check("every flag documented", not missing, ", ".join(missing[:5]))

out("RESULT: %s" % ("PASS" if ok else "FAIL"))
rp = unique_path(a.report)
os.makedirs(os.path.dirname(os.path.abspath(rp)), exist_ok=True)
open(rp, "w", encoding="ascii").write("\n".join(L) + "\n")
print("Report: %s" % rp)
sys.exit(0 if ok else 1)
