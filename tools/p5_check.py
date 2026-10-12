"""P5 gate: file groups, accents (ranked files, ripples), caption font, packaging.

Usage:
  python tools/p5_check.py SOURCE [--cache-dir DIR] [--workdir p5_work] [--report p5_report.txt]

SOURCE should be cached already (run `codeswarm SOURCE --stats` once).
The packaging part builds a wheel and, if pipx is installed, installs it into
a throw-away pipx home, runs it and uninstalls it again.
ASCII output; report and work files never overwrite earlier ones.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _deps import require  # noqa: E402
require("numpy", "pygame", "moderngl")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import numpy as np                                                       # noqa: E402
from codeswarm import filetypes                                          # noqa: E402
from codeswarm.colors import FIXED, auto_rules                          # noqa: E402
from codeswarm.config import build_config                               # noqa: E402
from codeswarm.ingest import Event, load_many                           # noqa: E402
from codeswarm.sim import Swarm                                         # noqa: E402
from codeswarm.util import default_cache_dir, unique_path               # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("source")
ap.add_argument("--cache-dir", default=default_cache_dir())
ap.add_argument("--workdir", default="p5_work")
ap.add_argument("--report", default="p5_report.txt")
a = ap.parse_args()
os.makedirs(a.workdir, exist_ok=True)
L = []


def out(m):
    m = str(m).encode("ascii", "backslashreplace").decode("ascii")
    print(m)
    L.append(m)


def bool_check(name, ok, detail=""):
    return check(name, bool(ok), detail)


def check(name, ok, detail=""):
    out("  [%s] %-44s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


ok = True
# ------------------------------------------------------------------ groups
out("FILE GROUPS")
CASES = {
    "AGENTS.md": "AI agents", "CLAUDE.md": "AI agents", "sub/CLAUDE.md": "AI agents", "GEMINI.md": "AI agents",
    ".cursor/rules/python.mdc": "AI agents", ".github/copilot-instructions.md": "AI agents",
    ".claude/commands/review.md": "AI agents", ".claude/settings.json": "AI agents", ".cursorrules": "AI agents",
    ".github/prompts/fix.prompt.md": "AI agents", "llms.txt": "AI agents", ".codex/config.toml": "AI agents",
    ".github/workflows/ci.yml": "CI", ".gitlab-ci.yml": "CI", "Jenkinsfile": "CI", "tox.ini": "CI",
    ".gitignore": "Repo tooling", ".pre-commit-config.yaml": "Repo tooling", ".github/CODEOWNERS": "Repo tooling",
    ".eslintrc.json": "Repo tooling", ".vscode/settings.json": "Repo tooling", ".github/ISSUE_TEMPLATE.md": "Repo tooling",
    "package.json": "Dependencies", "Cargo.lock": "Dependencies", "requirements-dev.txt": "Dependencies",
    "requirements/dev.in": "Dependencies", "go.sum": "Dependencies", "uv.lock": "Dependencies",
    "Makefile": "Build", "CMakeLists.txt": "Build", "pyproject.toml": "Build", "setup.py": "Build",
    "build.rs": "Build", "tsconfig.json": "Build", "installer.wxs": "Build",
    "Dockerfile": "Infra", "docker-compose.yml": "Infra", "main.tf": "Infra", "flake.nix": "Infra",
    "k8s/deploy.yaml": "Infra", "deploy/app.py": "Python",
    "tests/test_app.py": "Tests", "src/foo_test.go": "Tests", "web/app.spec.ts": "Tests",
    "src/Button.test.jsx": "Tests", "conftest.py": "Tests", "src/test/java/FooTest.java": "Tests",
    "src/main/java/Latest.java": "Java", "features/login.feature": "Tests",
    "db/migrations/0001_init.py": "Database", "schema.sql": "Database", "api/service.proto": "Schemas/API",
    "openapi.yaml": "Schemas/API", "ref/a.rnc": "Schemas/API",
    "README.md": "Docs", "LICENSE": "Docs", "CHANGES.rst": "Docs", "docs/index.rst": "Docs",
    "src/history.py": "Python", "README.md.in": "Docs", "docs/x.rst~": "Docs",
    "notebooks/a.ipynb": "Notebooks", "locale/fr/app.po": "Localization", "src/i18n/es.tsv": "Localization",
    "src/i18n/loader.rs": "Rust", "src/app.py": "Python", "src/pkg/py.typed": "Python", "src/lib.rs": "Rust",
    "index.ts": "TypeScript", "App.vue": "Web", "a.css_t": "Web", "shader.wgsl": "Shaders",
    "config.yaml": "Config", ".env.example": "Config", "data/sales.csv": "Data", "logo.png": "Images",
    "fonts/Inter.woff2": "Fonts", "dist/app.wasm": "Binaries", "src/components/charts/Bar.tsx": "TypeScript",
    "script.ps1": "PowerShell", "weird.xyz": ".xyz", "NOEXT": "(no extension)",
}
c = filetypes.Classifier()
wrong = [(p, e, c.group(p)) for p, e in CASES.items() if c.group(p) != e]
ok &= bool_check("%d classification cases" % len(CASES), not wrong, "; ".join("%s->%s" % (p, g) for p, _, g in wrong[:4]))
coarse = filetypes.Classifier(granularity="coarse")
fams = set(coarse.group(p) for p in CASES)
ok &= bool_check("coarse = at most 8 families", len(fams) <= 8, ", ".join(sorted(fams)))
toml = unique_path(os.path.join(a.workdir, "groups.toml"))
with open(toml, "w", encoding="ascii") as fh:
    fh.write('[[group]]\nname = "Specs"\nmatch = ["docs/*", "*.spec.md"]\ncolor = [255, 120, 0]\n')
custom, colors = filetypes.load_custom_groups(toml)
cc = filetypes.Classifier(custom)
ok &= bool_check("custom group beats built-in", cc.group("docs/index.rst") == "Specs" and cc.group("a.spec.md") == "Specs"
            and cc.group("README.md") == "Docs", "")
ev, _ = load_many([a.source], build_config(), a.cache_dir, refresh=False)
filetypes.set_active(filetypes.Classifier())
from codeswarm.colors import file_type_report      # noqa: E402
rows = file_type_report(ev)
unk = sum(r[2] for r in rows if r[0].startswith(".") or r[0] == "(no extension)")
ok &= bool_check("%s: unclassified share small" % a.source, unk < 5.0, "%.1f%% unclassified, %d groups" % (unk, len(rows)))
fake = [Event(i * 3600000, "a", "src/f%d.py" % (i % 50), "M", "c%d" % i) for i in range(2000)]
fake.append(Event(10 ** 9, "b", "AGENTS.md", "M", "x"))
rules = auto_rules(fake)
ag = [r for r in rules if r["group"] == "AI agents"]
ok &= bool_check("AI agents always listed, fixed colour", bool(ag) and ag[0]["color"] == list(FIXED["AI agents"]),
            ag[0]["label"] if ag else "missing")

# ------------------------------------------------------------------ accents
out("ACCENTS")
cfg = build_config("default", overrides={"seed": 2, "frames_per_day": 2})
cfg["color_rules"] = auto_rules(ev)
sw = Swarm(ev, cfg, seed=2)
W = cfg["popular_window_days"] * 86400000
win_ok, rip_ok, frames = True, True, 0
checked = 0
while not sw.done and frames < 4000:
    start = sw.prev_date
    i0 = sw.ev_i
    sw.step()
    frames += 1
    consumed = sw.events[i0:sw.ev_i]
    people_now = set(sw.person_index[e.author] for e in consumed)
    started = [r for r in sw.ripples if r[1] == sw.frame]
    rip_ok &= set(r[0] for r in started) == people_now
    if frames % 97 == 0:
        lo = sw.prev_date - W
        brute = {}
        for e in sw.events[:sw.ev_i]:
            if e.date >= lo:
                fi = sw.file_index[e.path]
                brute[fi] = brute.get(fi, 0) + 1
        win_ok &= brute == sw._recent_count
        top = sw.popular(10)
        best = sorted(brute.values(), reverse=True)[:10]
        win_ok &= [n for _, n, _ in top] == best
        checked += 1
rip_ok &= all(sw.frame - r[1] < sw.ripple_frames for r in sw.ripples)
ok &= bool_check("ranked files = changes in the last %g days" % cfg["popular_window_days"], win_ok,
            "%d frames checked against a brute-force count" % checked)
ok &= bool_check("one ripple per committing person", rip_ok, "%d frames" % frames)
classic = build_config("classic")
ok &= bool_check("classic preset unchanged (no accents)", classic["popular_style"] == "classic"
            and not classic["ripples"] and classic["popular_window_days"] is None, "")

# ------------------------------------------------------------------ caption
out("CAPTION FONT")
import pygame                                       # noqa: E402
from codeswarm.render import styled_text_rgba, ASSETS   # noqa: E402
pygame.font.init()
fpath = os.path.join(ASSETS, "fonts", "Orbitron-Medium.ttf")
ok &= bool_check("Orbitron bundled", os.path.isfile(fpath) and os.path.isfile(os.path.join(ASSETS, "fonts", "OFL.txt")), "")
font = pygame.font.Font(fpath, 48)
outline, _ = styled_text_rgba(font, "CODESWARM", (110, 230, 255), "outline", glow=False)
solid, _ = styled_text_rgba(font, "CODESWARM", (110, 230, 255), "solid", glow=False)
# hollow = the middle of each stroke is dark in the outline style
sa = solid[..., 3] > 200
inner = sa & np.roll(sa, 1, 0) & np.roll(sa, -1, 0) & np.roll(sa, 1, 1) & np.roll(sa, -1, 1)
oa = np.zeros(sa.shape, np.uint8)
h0, w0 = min(sa.shape[0], outline.shape[0]), min(sa.shape[1], outline.shape[1])
dy, dx = (outline.shape[0] - sa.shape[0]) // 2, (outline.shape[1] - sa.shape[1]) // 2
oa[:h0, :w0] = outline[dy:dy + h0, dx:dx + w0, 3]
hollow = float(((oa < 100) & inner).sum()) / max(int(inner.sum()), 1)
ok &= bool_check("outline style is hollow", hollow > 0.3, "%.0f%% of stroke centres empty" % (100 * hollow))
from codeswarm.app import run_headless              # noqa: E402
imgs = {}
short = [e for e in ev if e.date <= ev[0].date + 20 * 86400000]
for label, extra in (("with", {"caption": "test caption"}), ("bad font", {"caption": "x", "caption_font": "/nope.ttf"}),
                     ("without", {})):
    c2 = dict(cfg, **extra)
    run_headless(short, c2, max_frames=5, frame_callback=lambda n, img, lab=label: imgs.__setitem__(lab, img.copy()))
cap = imgs["with"][0:50, 0:300].astype(int) - imgs["without"][0:50, 0:300].astype(int)
ok &= bool_check("caption drawn top left", (np.abs(cap).max(axis=2) > 30).sum() > 300, "")
ok &= bool_check("missing font file falls back, no crash", "bad font" in imgs, "")

# ------------------------------------------------------------------ packaging
out("PACKAGING")
wdir = tempfile.mkdtemp(prefix="cs_wheel_")
try:
    p = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "-q", "-w", wdir, ROOT],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    wheels = [f for f in os.listdir(wdir) if f.endswith(".whl")]
    ok &= bool_check("wheel builds", bool(p.returncode == 0 and wheels), wheels[0] if wheels else p.stderr.decode()[-200:])
    if wheels:
        names = zipfile.ZipFile(os.path.join(wdir, wheels[0])).namelist()
        need = ["codeswarm/assets/particle.png", "codeswarm/assets/mask.png",
                "codeswarm/assets/fonts/Orbitron-Medium.ttf", "codeswarm/assets/fonts/OFL.txt"]
        missing = [n for n in need if n not in names]
        ok &= bool_check("wheel carries assets and font licence", not missing, ", ".join(missing))
        has_entry = any(n.endswith("entry_points.txt") for n in names)
        ok &= bool_check("console command 'codeswarm' declared", has_entry, "")
    pipx = shutil.which("pipx")
    if pipx and wheels:
        home = tempfile.mkdtemp(prefix="cs_pipx_")
        env = dict(os.environ, PIPX_HOME=os.path.join(home, "home"), PIPX_BIN_DIR=os.path.join(home, "bin"))
        r1 = subprocess.run([pipx, "install", os.path.join(wdir, wheels[0])], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        exe = os.path.join(home, "bin", "codeswarm")
        r2 = subprocess.run([exe, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE) if os.path.exists(exe) \
            else None
        r3 = subprocess.run([pipx, "uninstall", "codeswarm"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        left = os.path.exists(exe) or os.path.isdir(os.path.join(home, "home", "venvs", "codeswarm"))
        ok &= bool_check("pipx install / run / uninstall", r1.returncode == 0 and r2 is not None and r2.returncode == 0
                    and r3.returncode == 0 and not left,
                    (r2.stdout.decode().strip() if r2 else r1.stderr.decode()[-200:]))
        shutil.rmtree(home, ignore_errors=True)
    else:
        out("  info: pipx not installed - install/uninstall test skipped")
finally:
    shutil.rmtree(wdir, ignore_errors=True)

out("RESULT: %s" % ("PASS" if ok else "FAIL"))
rp = unique_path(a.report)
os.makedirs(os.path.dirname(os.path.abspath(rp)), exist_ok=True)
open(rp, "w", encoding="ascii").write("\n".join(L) + "\n")
print("Report: %s" % rp)
sys.exit(0 if ok else 1)
