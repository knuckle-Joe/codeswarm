"""Layered configuration.

Order (later wins), same idea as the original CodeSwarmConfig prop stack:
    1. built-in defaults   (values of code_swarm's defaults/code_swarm.config)
    2. preset              (--preset classic, ...)
    3. config file         (--config file.toml, or a legacy .config file)
    4. command-line flags

Every legacy key has a snake_case equivalent, e.g. FramesPerDay -> frames_per_day.
"""

import copy
import re

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    tomllib = None

from .util import warn

# ---------------------------------------------------------------------------
# 1. Defaults: taken from rictic code_swarm defaults/code_swarm.config
# ---------------------------------------------------------------------------
DEFAULTS = {
    "width": 1920,
    "height": 1080,
    "ui_scale": "auto",            # auto = height/720: text, dots, avatars, lines grow with the frame
    "frames_per_day": 6.0,
    "fps": 24,                     # code_swarm.java FRAME_RATE
    "background": [0, 0, 0],
    "font": "SansSerif",
    "font_size": 10,
    "font_color": [255, 255, 255],
    "bold_font": "SansSerif",
    "bold_font_size": 14,
    "show_user_name": True,
    "draw_names_sharp": True,
    "draw_names_halos": False,
    "draw_files_sharp": True,
    "draw_files_fuzzy": True,
    "draw_files_jelly": False,
    "circular_avatars": True,
    "show_legend": True,
    "show_history": True,
    "show_date": True,
    "show_edges": False,
    "show_debug": False,
    "show_popular": False,
    "show_engine": False,          # physics engine name, bottom right (key E)
    "popular_position": "right",   # right = original; left = under the legend
    "edge_length": 25,
    "edge_life": 150,
    "file_life": 150,
    "person_life": 255,
    "edge_decrement": -2,
    "file_decrement": -2,
    "person_decrement": -1,
    "file_mass": 1.0,
    "person_mass": 100.0,
    "highlight_pct": 5,
    "physics_engine": "orderly",
    "avatars": "auto",             # auto | github | gravatar | local | none
    "avatar_limit": 1000,          # pictures for the N most active people (0 = everyone)
    "github_api_budget": 50,       # max GitHub API lookups per run without a token
    "gravatar_fallback": "identicon",
    "avatar_size": 40,
    "local_avatar_dir": "",
    "local_avatar_default": "default.png",
    "take_snapshots": False,
    "snapshot_location": "frames/code_swarm-#####.png",
    "seed": None,
    "linger_frames": 0,            # frames to keep animating after the last event (0 = original)
    "utc_dates": False,            # date overlay in UTC instead of local time
    "legacy_alpha_wrap": False,    # reproduce the original's flashing alpha (life mod 256)
    # accents (new; off in the faithful presets)
    "popular_style": "classic",    # classic = touch counts over files | ranked = numbered list + markers
    "popular_window_days": None,   # rank by changes in the last N days (None = all time, original)
    "ripples": False,              # expanding ring at each commit
    "accent": [255, 196, 64],      # colour of rank numbers and markers
    "caption": None,
    "auto_caption": False,         # caption = repository name when --caption is not given
    "popular_count": 10,           # files in the ranked list (fits above the histogram)
    "popular_marks": 10,           # how many of them get a ring + number in the swarm
    "show_stats": False,           # repository panel, top right
    "stats_window_days": 30,       # window of the "last N days" numbers (if files are ranked all-time)
    "people_count": 0,             # most active people listed in the stats panel
    "histogram_scale": 1,          # bar width and height multiplier (original 1)
    "histogram_max": None,         # cap the histogram at this fraction of the height (None = no cap)
    "text_shadow": False,          # dark rim around names and numbers
    "dim_idle_names": False,       # names of people not committing lately are dimmer
    "caption_font": "orbitron",    # bundled Orbitron (SIL OFL), or a .ttf path
    "caption_style": "outline",    # outline | solid | plain
    "caption_color": [110, 230, 255],
    "legend_font": "sans",         # sans (same as names) | orbitron | path to a .ttf
    "bounds": "auto",              # auto = keep file rings on screen | legacy = original clamp
    # commit details (new; off in the faithful presets)
    "commit_text": "off",          # off | names (subject under the name) | ticker (bottom right) | both
    "commit_text_seconds": 3.0,    # how long a subject stays under a name
    "commit_text_max": 3,          # subjects shown under names at the same time (newest win)
    "ticker_lines": 4,             # lines in the commit ticker
    "subject_length": 64,          # longer subjects are cut with "..."
    "status_flash": False,         # ranked-file rings flash: green added, white changed, red deleted, blue moved
    "author_ticks": False,         # ticks around ranked-file rings: one per person who changed the file
    "show_releases": False,        # release tags: banner + markers on the histogram
    "release_tags": "auto",        # auto | all | none | shell patterns ("v*,release-*")
    "release_gap_seconds": 4.0,    # at most one release banner per this many seconds of video
    "name_layout": "off",          # off = original | spread = move overlapping names apart
    "hubs": 0,                     # settle mode: the N busiest shared files glide between their people (0 = original)
    "hub_min_people": 2,           # a hub file was changed by at least this many people in the window
    "hub_follow": 1.0,             # 1 = a hub goes to the ring of each new editor (as the original), 0 = stays between its people
    "hub_speed": 20.0,             # top speed of a hub, px per frame before ui scale
    "hub_rate": 0.3,               # share of the remaining distance a hub covers each frame (no overshoot)
    "hub_gather": False,           # also pull people toward their hubs (0.10 behaviour)
    "dim_idle_avatars": False,     # avatars of idle people fade like their names
    "keep_clear": False,           # people (and their files) stay out of the panels
    "file_size": "original",       # original = grows with sqrt(changes) | gentle = only a little bigger when busy
    # ingest options (new)
    "author_key": "name",          # name | email  (legacy git recipe used email)
    "since": None,
    "until": None,
    "branch": None,                # None = HEAD
    "include": [],
    "exclude": [],
    "renames": "new",              # new = touch new path only | both | legacy
    "color_rules": [],
    "colors": None,                # auto | rules ; None = rules if any are configured, else auto
    # people (new)
    "merge_identities": True,      # link names/emails/GitHub logins of the same person
    "exclude_bots": True,          # hide dependabot, pre-commit-ci, ... (original showed them)
    "aliases": [],                 # ["Old Name=New Name", ...]
    "exclude_authors": [],         # glob patterns on the display name
}

# Legacy CamelCase key -> new key
LEGACY_KEYS = {
    "Width": "width", "Height": "height", "FramesPerDay": "frames_per_day",
    "Background": "background", "Font": "font", "FontSize": "font_size",
    "FontColor": "font_color", "BoldFont": "bold_font", "BoldFontSize": "bold_font_size",
    "ShowUserName": "show_user_name", "DrawNamesSharp": "draw_names_sharp",
    "DrawNamesHalos": "draw_names_halos", "DrawFilesSharp": "draw_files_sharp",
    "DrawFilesFuzzy": "draw_files_fuzzy", "DrawFilesJelly": "draw_files_jelly",
    "CircularAvatars": "circular_avatars", "ShowLegend": "show_legend",
    "ShowHistory": "show_history", "ShowDate": "show_date", "ShowEdges": "show_edges",
    "ShowDebug": "show_debug", "EdgeLength": "edge_length", "EdgeLife": "edge_life",
    "FileLife": "file_life", "PersonLife": "person_life",
    "EdgeDecrement": "edge_decrement", "FileDecrement": "file_decrement",
    "PersonDecrement": "person_decrement", "FileMass": "file_mass",
    "PersonMass": "person_mass", "HighlightPct": "highlight_pct",
    "GravatarFallback": "gravatar_fallback", "AvatarSize": "avatar_size",
    "LocalAvatarDirectory": "local_avatar_dir", "LocalAvatarDefaultPic": "local_avatar_default",
    "TakeSnapshots": "take_snapshots", "SnapshotLocation": "snapshot_location",
}
# Legacy keys that are accepted but have no effect in the rewrite
LEGACY_IGNORED = {
    "InputFile", "ParticleSpriteFile", "UseOpenGL", "MaxThreads",
    "PhysicsEngineConfigDir", "IsInputSorted", "MillisecondsPerFrame",
    # present in the user's classic config but never read by code_swarm.java:
    "NodeSpeed", "FileSpeed", "PersonSpeed", "DrawNamesFuzzy",
}

# ---------------------------------------------------------------------------
# 2. Presets
# ---------------------------------------------------------------------------
_CLASSIC_COLORS = [
    ("C", r".*(\.c|\.cpp|\.h|\.mk)", (255, 0, 0)),
    ("Python", r".*(\.py|\.pyx)", (65, 105, 225)),
    ("CSharp", r".*(\.cs|\.csproj)", (255, 255, 0)),
    ("Other Source Code", r".*(\.rb|\.erb|\.hs|\.sql|\.m|\.d|\.js|\.pl|\.sh|\.lhs|\.hi|\.hpp|\.cat|\.inf|\.sys|\.dll|\.as|\.cmake\.java)", (255, 99, 71)),
    ("Documents/Images", r".*(\.txt|\.html|\.tex|\.tmpl|\.css|\.xml|\.yml|\.json|\.rdoc|\.md|\.png|\.jpg|\.gif|\.jpeg|README|COPYING|LICENSE|AUTHORS|\.asciidoc|HACKING)", (138, 43, 226)),
    ("Tests", r".*test.*", (153, 255, 255)),
    ("Localizations", r"(.*(\.mo|\.po))|(.*\.lproj.*)", (110, 200, 90)),
]

PRESETS = {
    # The user's sample.config (Stack Exchange answer), key for key.
    "classic": {
        "width": 1920, "height": 1080, "frames_per_day": 25.0,   # your file said 800x600
        "draw_names_halos": False, "show_user_name": True,
        "font": "SansSerif", "font_size": 9, "bold_font_size": 10,
        "font_color": [245, 245, 245], "background": [0, 0, 0],
        "draw_names_sharp": True, "draw_files_fuzzy": True,
        "draw_files_jelly": True, "draw_files_sharp": False,
        "show_legend": True, "show_history": True, "show_date": True,
        "show_edges": True,
        "edge_decrement": -8, "file_decrement": -3, "person_decrement": -2,
        "file_mass": 2.0, "person_mass": 9.0,
        "edge_life": 140, "edge_length": 12, "file_life": 1000, "person_life": 750,
        "highlight_pct": 8, "physics_engine": "orderly",
        # the Stack Exchange answer's optional patch: popular on, under legend
        "show_popular": True, "popular_position": "left",
        "color_rules": [
            {"label": l, "regex": r, "color": list(c), "color2": list(c)}
            for (l, r, c) in _CLASSIC_COLORS
        ],
    },
    # Original project defaults (defaults/code_swarm.config) - same as DEFAULTS
    "original": {},
}
# Used when neither --preset nor --config is given: the classic look, but
# colours computed from the repository instead of the fixed C/Python/C# rules.
PRESETS["default"] = dict(PRESETS["classic"], color_rules=[], colors="auto",
                          popular_style="ranked", popular_window_days=30, ripples=True,
                          font_size=11, bold_font_size=13, avatar_size=40,
                          text_shadow=True, dim_idle_names=True, legend_font="orbitron",
                          auto_caption=True, popular_count=20, show_stats=True, people_count=5,
                          histogram_scale=2, histogram_max=0.22,
                          commit_text="both", status_flash=True, author_ticks=True, show_releases=True,
                          hubs=10, dim_idle_avatars=True, ticker_lines=8, file_size="gentle", keep_clear=True)
PRESETS["classic"]["name_layout"] = "spread"
PRESETS["default"]["name_layout"] = "spread"


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def _parse_rgb(text):
    parts = [p.strip() for p in str(text).split(",")]
    return [int(parts[0]), int(parts[1]), int(parts[2])]


def _coerce(key, value):
    """Coerce a string value from a legacy file to the type of DEFAULTS[key]."""
    ref = DEFAULTS.get(key)
    if isinstance(ref, bool):
        return str(value).strip().lower() == "true"   # Java Boolean.valueOf semantics
    if isinstance(ref, int):
        return int(str(value).strip())
    if isinstance(ref, float):
        return float(str(value).strip())
    if isinstance(ref, list) and key in ("background", "font_color"):
        return _parse_rgb(value)
    return str(value).strip()


def parse_legacy_color(value):
    """Parse a ColorAssignN value:  "label","regex", r1,g1,b1, r2,g2,b2
    Mirrors ColorTest.loadProperty (first and last double quote delimit the
    label/regex part, the rest is comma separated numbers)."""
    first_q = value.index('"')
    last_q = value.rindex('"')
    tokens = value[first_q + 1:last_q].split('"')
    label = tokens[0]
    regex = tokens[2] if len(tokens) == 3 else tokens[0]
    nums = [int(t.strip()) for t in value[last_q + 1:].split(",") if t.strip()]
    return {"label": label, "regex": regex, "color": nums[0:3], "color2": nums[3:6]}


def load_legacy_config(path, java_escapes=False):
    """Read a code_swarm .config (Java properties) file.

    java_escapes=False keeps backslashes literally, so a regex such as
    .*(\\.c|\\.h) means what its author wrote.  java_escapes=True reproduces
    java.util.Properties exactly: '\\.' collapses to '.', which made the
    original rules looser than written (e.g. "x.doc" matched the C rule).
    """
    out = {}
    colors = {}
    with open(path, "r", encoding="latin-1") as fh:   # Properties.load is ISO-8859-1
        lines = fh.read().splitlines()
    buf = ""
    logical = []
    for raw in lines:
        line = raw.strip() if not buf else raw.lstrip()
        if not buf and (not line or line[0] in "#!"):
            continue
        if line.endswith("\\") and not line.endswith("\\\\"):
            buf += line[:-1]
            continue
        logical.append(buf + line)
        buf = ""
    if buf:
        logical.append(buf)

    for line in logical:
        m = re.match(r"([^=:\s]+)\s*[=:]?\s*(.*)$", line)
        if not m:
            continue
        key, value = m.group(1), m.group(2)
        if java_escapes:
            value = re.sub(r"\\(.)", lambda mm: {"t": "\t", "n": "\n"}.get(mm.group(1), mm.group(1)), value)
        cm = re.match(r"ColorAssign(\d+)$", key)
        if cm:
            colors[int(cm.group(1))] = parse_legacy_color(value)
        elif key in LEGACY_KEYS:
            out[LEGACY_KEYS[key]] = _coerce(LEGACY_KEYS[key], value)
        elif key == "AvatarFetcher":
            out["avatars"] = {"GravatarFetcher": "gravatar", "NoAvatar": "none",
                              "LocalAvatar": "local"}.get(value.strip(), "none")
        elif key == "PhysicsEngineSelection":
            out["physics_engine"] = "orderly" if value.strip() == "PhysicsEngineOrderly" else value.strip()
        elif key in LEGACY_IGNORED:
            if key == "InputFile":
                out["_legacy_input_file"] = value.strip()
        else:
            warn("unknown key in %s ignored: %s" % (path, key))
    if colors:
        # original reads ColorAssign1, 2, 3 ... and stops at the first gap
        rules = []
        i = 1
        while i in colors:
            rules.append(colors[i])
            i += 1
        out["color_rules"] = rules
    return out


def load_toml_config(path):
    if tomllib is None:
        raise RuntimeError("TOML config needs Python 3.11 or newer")
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    out = {}
    for k, v in data.items():
        if k == "color":            # [[color]] tables
            out["color_rules"] = [
                {"label": c["label"], "regex": c["regex"],
                 "color": list(c["color"]), "color2": list(c.get("color2", c["color"]))}
                for c in v
            ]
        elif k in DEFAULTS:
            out[k] = v
        else:
            warn("unknown key in %s ignored: %s" % (path, k))
    return out


def load_config_file(path, java_escapes=False):
    if path.lower().endswith(".toml"):
        return load_toml_config(path)
    return load_legacy_config(path, java_escapes=java_escapes)


def build_config(preset=None, config_path=None, overrides=None, java_escapes=False):
    cfg = copy.deepcopy(DEFAULTS)
    if preset:
        if preset not in PRESETS:
            raise ValueError("unknown preset %r (choose from %s)" % (preset, ", ".join(sorted(PRESETS))))
        cfg.update(copy.deepcopy(PRESETS[preset]))
    if config_path:
        cfg.update(load_config_file(config_path, java_escapes=java_escapes))
    for k, v in (overrides or {}).items():
        if v is not None:
            cfg[k] = v
    validate(cfg)
    return cfg


def validate(cfg):
    for k in ("width", "height", "edge_life", "file_life", "person_life", "avatar_size"):
        if cfg[k] < 0:
            raise ValueError("%s must be >= 0, found %s" % (k, cfg[k]))
    for k in ("edge_decrement", "file_decrement", "person_decrement"):
        if cfg[k] > 0:
            raise ValueError("%s must be <= 0, found %s" % (k, cfg[k]))   # fixed message
    if cfg["frames_per_day"] <= 0:
        raise ValueError("frames_per_day must be > 0")
    if cfg.get("commit_text", "off") not in ("off", "names", "ticker", "both"):
        raise ValueError("commit_text must be off, names, ticker or both, found %r" % cfg["commit_text"])
    if cfg.get("name_layout", "off") not in ("off", "spread"):
        raise ValueError("name_layout must be off or spread, found %r" % cfg["name_layout"])
    for rule in cfg["color_rules"]:
        if not rule.get("group"):
            re.compile(rule["regex"])


def dump_toml(cfg):
    """Render a config as TOML text (ASCII), for --print-config."""
    lines = []
    for k in sorted(cfg):
        if k.startswith("_") or k == "color_rules":
            continue
        v = cfg[k]
        if v is None:
            lines.append("# %s = (unset)" % k)
        else:
            lines.append("%s = %s" % (k, _toml_value(v)))
    for r in cfg["color_rules"]:
        lines.append("")
        lines.append("[[color]]")
        lines.append("label = %s" % _toml_value(r["label"]))
        lines.append("regex = '%s'" % r["regex"])     # literal string: no escapes
        lines.append("color = %s" % _toml_value(r["color"]))
        lines.append("color2 = %s" % _toml_value(r["color2"]))
    return "\n".join(lines) + "\n"


def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % s
