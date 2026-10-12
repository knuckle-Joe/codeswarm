"""Automatic colour rules: group files by language / kind, colour the
biggest groups by share of activity.  Used when no ColorAssign rules
are configured (or with --colors auto)."""

import os
from collections import Counter

from .filetypes import group_of   # noqa: F401  (re-exported; sim.py imports it from here)

# distinct, bright on black; first colour goes to the busiest group
PALETTE = [
    (65, 140, 255),   # blue
    (255, 90, 80),    # red
    (80, 215, 120),   # green
    (185, 95, 255),   # purple
    (60, 215, 215),   # cyan
    (255, 150, 50),   # orange
    (255, 110, 195),  # pink
    (175, 220, 70),   # lime
    (150, 160, 255),  # lavender
    (230, 230, 160),  # cream
    (255, 205, 60),   # yellow - last: close to the gold accent of ranked files
]
OTHER = (128, 128, 128)
# fixed colours for groups that should be recognisable in every video
FIXED = {"AI agents": (255, 255, 255)}      # white: stands out against every palette colour


def auto_rules(events, max_groups=10, show_share=True, min_share=0.005, pinned=("AI agents",),
               custom_colors=None):
    """Colour rules (same shape as config color_rules) built from the history.

    Groups are ranked by file touches; the busiest get the palette colours in
    order, groups below min_share fall into Misc (grey).  Pinned groups are
    always listed when present at all (AI agent files are often few but
    interesting) and keep a fixed colour."""
    custom_colors = custom_colors or {}
    touches = Counter(group_of(e.path) for e in events)
    total = sum(touches.values()) or 1
    ranked = [g for g, n in touches.most_common() if g != "(no extension)"]
    top = [g for g in ranked if touches[g] / float(total) >= min_share][:max_groups]
    for g in pinned:
        if g in touches and g not in top:
            top = top[:max_groups - 1] + [g]
    rules = []
    k = 0
    for g in top:
        label = "%s  %s" % (g, _pct(touches[g], total)) if show_share else g
        if g in custom_colors:
            c = list(custom_colors[g])
        elif g in FIXED:
            c = list(FIXED[g])
        else:
            c = list(PALETTE[k % len(PALETTE)])
            k += 1
        # "group" rules match by group_of(path) instead of a regex
        rules.append({"label": label, "group": g, "regex": "", "color": c, "color2": c})
    return rules


def _pct(n, total):
    p = 100.0 * n / total
    return "%d%%" % round(p) if p >= 1 else "<1%"


def file_type_report(events):
    """Rows (group, touches, share, files, example) + unclassified extensions."""
    by = {}
    for e in events:
        g = group_of(e.path)
        row = by.setdefault(g, [0, set()])
        row[0] += 1
        row[1].add(e.path)
    total = sum(r[0] for r in by.values()) or 1
    rows = sorted(((g, r[0], 100.0 * r[0] / total, len(r[1]), sorted(r[1])[0]) for g, r in by.items()),
                  key=lambda t: -t[1])
    return rows


def repo_rules(events, show_share=True):
    """One colour per repository (events carry e.repo), busiest first."""
    touches = Counter(e.repo or "?" for e in events)
    total = sum(touches.values()) or 1
    rules = []
    for i, (repo, n) in enumerate(touches.most_common(len(PALETTE))):
        label = "%s  %d%%" % (repo, round(100.0 * n / total)) if show_share else repo
        c = list(PALETTE[i % len(PALETTE)])
        rules.append({"label": label, "repo": repo, "regex": "", "color": c, "color2": c})
    return rules
