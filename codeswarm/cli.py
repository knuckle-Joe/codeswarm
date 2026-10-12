"""Command line entry point:  codeswarm SOURCE [options]"""

import argparse
import csv
import datetime
import os
import sys
import time

from . import __version__
from .config import DEFAULTS, PRESETS, build_config, dump_toml
from .ingest import git_available, load_many, summarize, write_legacy_xml
from .util import default_cache_dir, say, unique_path, warn


def _rgb(text):
    parts = [int(p) for p in text.split(",")]
    if len(parts) != 3 or not all(0 <= p <= 255 for p in parts):
        raise argparse.ArgumentTypeError("expected R,G,B with values 0-255")
    return parts


def _size(text):
    try:
        w, h = text.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError("expected WIDTHxHEIGHT, e.g. 1920x1080")


_TOGGLE_HELP = {
    "show_legend": "colour legend (key l)", "show_history": "histogram, bottom left (key h)",
    "show_date": "date, bottom right (key d)", "show_edges": "lines between people and files (key e)",
    "show_popular": "ranked file list + markers (key p)", "show_user_name": "names of people",
    "draw_names_sharp": "draw names (key s)", "draw_names_halos": "blurred glow behind names (key a)",
    "draw_files_sharp": "files as dots (key S)", "draw_files_fuzzy": "files as glowing sprites (key f)",
    "draw_files_jelly": "files as rings (key j)", "circular_avatars": "round avatars",
    "legacy_alpha_wrap": "reproduce the original's flashing (alpha = life mod 256)",
    "ripples": "expanding ring at each commit (key r)", "text_shadow": "dark rim around names and numbers",
    "dim_idle_names": "dim the names of people who have not committed lately",
    "show_engine": "physics engine name, bottom right (key E)",
    "keep_clear": "people and their files stay out of the panels (legend, file list, repository panel, "
                  "ticker) instead of passing under them",
}


def build_parser():
    p = argparse.ArgumentParser(
        prog="codeswarm",
        description="Animate the commit history of a git repository (code_swarm rewrite).",
        epilog="SOURCE can be a GitHub URL, owner/repo, a local repository folder, "
               "or a legacy code_swarm .xml event file.")
    p.add_argument("sources", nargs="*", metavar="SOURCE",
                   help="repository URL, owner/repo, local path or .xml; several = one combined swarm")
    p.add_argument("--version", action="version", version="codeswarm " + __version__)

    g = p.add_argument_group("configuration")
    g.add_argument("--preset", choices=sorted(PRESETS),
                   help="named look: default (classic look, automatic colours, panels), classic (the code_swarm "
                        "Stack Exchange setup), original (code_swarm's own defaults)")
    g.add_argument("--config", help="TOML file, or a legacy code_swarm .config file")
    g.add_argument("--java-escapes", action="store_true",
                   help="read legacy .config backslashes exactly like Java did")
    g.add_argument("--print-config", action="store_true", help="print the final config as TOML and exit")

    g = p.add_argument_group("history selection")
    g.add_argument("--since", help="only commits after this date (git syntax, e.g. 2020-01-01)")
    g.add_argument("--until", help="only commits before this date")
    g.add_argument("--branch", help="branch, tag or commit to read (default HEAD)")
    g.add_argument("--include", action="append", metavar="GLOB", help="keep only matching paths (repeatable)")
    g.add_argument("--exclude", action="append", metavar="GLOB", help="drop matching paths (repeatable)")
    g.add_argument("--author-key", choices=["name", "email"], help="identify people by name or email")
    g.add_argument("--renames", choices=["new", "both", "legacy"],
                   help="rename handling: new path only, both paths, or none (add+delete)")

    g.add_argument("--no-prefix", action="store_true",
                   help="with several repositories: do not prefix paths with the repository name")
    g.add_argument("--max-gap", type=float, metavar="DAYS",
                   help="shorten quiet periods longer than DAYS to DAYS (dates on screen stay real)")
    g.add_argument("--duration", type=float, metavar="SECONDS",
                   help="choose frames-per-day so the animation lasts about SECONDS")

    g = p.add_argument_group("people")
    g.add_argument("--merge-identities", dest="merge_identities", action=argparse.BooleanOptionalAction,
                   default=None, help="treat names/emails/GitHub logins of one person as one (default on)")
    g.add_argument("--keep-bots", dest="exclude_bots", action="store_false", default=None,
                   help="show dependabot, pre-commit-ci and other bots (hidden by default)")
    g.add_argument("--alias", action="append", metavar="'OLD=NEW'", help="show OLD as NEW (repeatable)")
    g.add_argument("--exclude-author", action="append", metavar="GLOB", help="hide matching people (repeatable)")

    g = p.add_argument_group("look")
    g.add_argument("--file-groups", metavar="FILE.toml",
                   help="your own file groups, checked before the built-in ones (see README)")
    g.add_argument("--granularity", choices=["fine", "coarse"], default="fine",
                   help="fine = ~60 groups (languages, tests, CI, AI agents...); coarse = 8 families")
    g.add_argument("--colors", choices=["auto", "rules", "repo"],
                   help="auto = by language/kind; rules = ColorAssign rules; repo = one colour per repository")
    g.add_argument("--avatar-size", type=int, metavar="PX", help="avatar size before ui scale")
    g.add_argument("--avatar-fallback", dest="gravatar_fallback",
                   choices=["identicon", "retro", "robohash", "monsterid", "wavatar", "mp", "none"],
                   help="picture for people without one (default identicon)")
    g.add_argument("--avatar-dir", dest="local_avatar_dir", metavar="DIR", help="folder for --avatars local")
    g.add_argument("--github-token", help="GitHub token for avatar lookups (or set GITHUB_TOKEN)")
    g.add_argument("--github-api-budget", type=int, help="max GitHub API calls without a token (default 50)")
    g.add_argument("--size", type=_size, help="frame size, e.g. 1280x720")
    g.add_argument("--fps", type=int, help="frames per second of the window / video")
    g.add_argument("--ui-scale", dest="ui_scale", metavar="X",
                   help="size of text, dots, avatars and lines: 'auto' (height/720) or a number")
    g.add_argument("--font-size", dest="font_size", type=int, help="names and panels, before ui scale (default 11)")
    g.add_argument("--frames-per-day", type=float, metavar="N",
                   help="animation frames per day of history (speed); see also --duration")
    g.add_argument("--background", type=_rgb, metavar="R,G,B", help="background colour")
    g.add_argument("--font-color", type=_rgb, metavar="R,G,B", help="colour of names and panel text")
    g.add_argument("--avatars", choices=["auto", "github", "gravatar", "local", "none"],
                   help="where pictures come from (auto: GitHub for GitHub repos, else Gravatar)")
    g.add_argument("--seed", type=int, help="random seed for reproducible renders")
    g.add_argument("--bounds", choices=["auto", "legacy"],
                   help="auto keeps whole file rings on screen; legacy = original edge clamp")
    for flag in ("show_legend", "show_history", "show_date", "show_edges", "show_popular",
                 "show_user_name", "draw_names_sharp", "draw_names_halos",
                 "draw_files_sharp", "draw_files_fuzzy", "draw_files_jelly",
                 "circular_avatars", "legacy_alpha_wrap", "ripples", "text_shadow", "dim_idle_names",
                 "show_engine", "keep_clear"):
        g.add_argument("--" + flag.replace("_", "-"), dest=flag,
                       action=argparse.BooleanOptionalAction, default=None, help=_TOGGLE_HELP[flag])

    g.add_argument("--linger", type=float, metavar="SECONDS",
                   help="keep animating after the last event so things fade out (default 0)")
    g.add_argument("--utc-dates", dest="utc_dates", action="store_true", default=None,
                   help="show the date overlay in UTC instead of local time")

    g = p.add_argument_group("titles")
    g.add_argument("--title", help="intro card title (default: repository name(s))")
    g.add_argument("--subtitle", action="append", help="intro card line under the title (repeatable)")
    g.add_argument("--intro", type=float, metavar="SECONDS",
                   help="show an intro card for SECONDS (default 3 when --title is given, else 0)")
    g.add_argument("--credits", type=float, metavar="SECONDS",
                   help="closing card with the most active people for SECONDS")
    g.add_argument("--credits-count", type=int, default=24, help="people on the closing card (default 24)")
    g.add_argument("--caption", help="permanent title in the top-left corner (default: the repository name)")
    g.add_argument("--no-caption", action="store_true", help="no caption")
    g.add_argument("--caption-font", help="'orbitron' (bundled, default) or a .ttf/.otf path")
    g.add_argument("--caption-style", choices=["outline", "solid", "plain"],
                   help="caption letters: outline + glow, solid + glow, or plain")
    g.add_argument("--legend-font", help="font of the colour legend: sans (default), orbitron, or a .ttf path")
    g.add_argument("--caption-color", type=_rgb, metavar="R,G,B", help="caption colour")
    g.add_argument("--popular-style", choices=["ranked", "classic"],
                   help="ranked = numbered list + matching markers in the swarm; classic = original counts")
    g.add_argument("--popular-window", dest="popular_window_days", type=float, metavar="DAYS",
                   help="rank files by changes in the last DAYS (0 = all time)")
    g.add_argument("--accent", type=_rgb, metavar="R,G,B", help="colour of rank numbers and markers")
    g.add_argument("--popular-count", type=int, metavar="N", help="files in the ranked list (default 20)")
    g.add_argument("--popular-marks", type=int, metavar="N",
                   help="how many of the listed files are marked in the swarm (default 10, 0 = none)")
    g.add_argument("--stats-panel", dest="show_stats", action=argparse.BooleanOptionalAction, default=None,
                   help="repository panel at the top right (key i)")
    g.add_argument("--stats-window", dest="stats_window_days", type=float, metavar="DAYS",
                   help="window of the 'last N days' numbers when files are ranked all-time (default 30)")
    g.add_argument("--people-count", type=int, metavar="N", help="most active people in the panel (default 5, 0 = none)")
    g.add_argument("--histogram-scale", type=float, metavar="X", help="histogram bar width and height (default 2)")
    g.add_argument("--histogram-max", type=float, metavar="FRACTION",
                   help="cap the histogram at this share of the height (default 0.22, 0 = no cap)")

    g = p.add_argument_group("commit details")
    g.add_argument("--commit-text", choices=["off", "names", "ticker", "both"],
                   help="commit subjects: under the committer's name, in a ticker bottom right, or both (key c)")
    g.add_argument("--commit-text-seconds", type=float, metavar="SECONDS",
                   help="how long a subject stays under a name (default 3)")
    g.add_argument("--commit-text-max", type=int, metavar="N",
                   help="subjects under names at the same time, newest first (default 3)")
    g.add_argument("--ticker-lines", type=int, metavar="N", help="lines in the commit ticker, just above the date (default 8)")
    g.add_argument("--subject-length", type=int, metavar="CHARS",
                   help="cut longer subjects with '...' (default 64)")
    g.add_argument("--status-flash", dest="status_flash", action=argparse.BooleanOptionalAction, default=None,
                   help="ranked-file rings flash on each change: green added, white changed, red deleted, blue moved")
    g.add_argument("--author-ticks", dest="author_ticks", action=argparse.BooleanOptionalAction, default=None,
                   help="ticks around ranked-file rings, one per person who changed the file in the window")
    g.add_argument("--releases", dest="show_releases", action=argparse.BooleanOptionalAction, default=None,
                   help="release tags: short banner and markers on the histogram (key t)")
    g.add_argument("--release-tags", metavar="auto|all|none|PATTERNS",
                   help="which tags are releases: auto (version-like, else build numbers), all, none, "
                        "or shell patterns such as 'v*,release-*'")
    g.add_argument("--release-gap", dest="release_gap_seconds", type=float, metavar="SECONDS",
                   help="at most one release banner per this many seconds (default 4)")
    g.add_argument("--hubs", type=int, metavar="N",
                   help="the N busiest shared files go to each new editor quickly and stick to them, instead of "
                        "the original springy flight that overshoots and orbits (default 10, 0 = original motion)")
    g.add_argument("--file-size", choices=["gentle", "original"],
                   help="gentle = busy files only a little bigger (about 2.5x a new file at most); original = "
                        "grows with the square root of all changes (20x and more on long histories)")
    g.add_argument("--hub-follow", type=float, metavar="0..1",
                   help="where a hub goes: 1 = the ring of the person who changed it last, as the original "
                        "(default); lower = between that person and everyone who changed it lately")
    g.add_argument("--hub-rate", type=float, metavar="0..1",
                   help="share of the remaining distance a hub covers each frame: higher = arrives sooner "
                        "(default 0.3; it never overshoots and locks on when it arrives)")
    g.add_argument("--hub-speed", type=float, metavar="PX",
                   help="top speed of a hub in px per frame before ui scale (default 20; original files peak "
                        "around 35 and then bounce)")
    g.add_argument("--hub-gather", dest="hub_gather", action=argparse.BooleanOptionalAction, default=None,
                   help="also pull people toward their hubs (the 0.10 look; people move more)")
    g.add_argument("--hub-min-people", type=int, metavar="N",
                   help="a hub was changed by at least N people in the window (default 2)")
    g.add_argument("--dim-idle-avatars", dest="dim_idle_avatars", action=argparse.BooleanOptionalAction,
                   default=None, help="avatars of people not committing lately fade like their names")
    g.add_argument("--name-layout", choices=["spread", "off"],
                   help="spread = move overlapping names apart (default); off = original placement (key n)")

    g = p.add_argument_group("output")
    g.add_argument("--output", "-o", metavar="FILE",
                   help="render a video without a window: .mp4 (default codec H.264), .mkv, .mov, .webm")
    g.add_argument("--crf", type=int, default=18, help="video quality, lower = better/bigger (default 18)")
    g.add_argument("--encoder-preset", default="medium",
                   help="x264 speed/size trade-off: ultrafast ... medium ... veryslow")
    g.add_argument("--frames", metavar="DIR",
                   help="render without a window and save each frame as PNG in DIR")
    g.add_argument("--start-frame", type=int, default=1, help="first frame to save")
    g.add_argument("--every", type=int, default=1, help="save every Nth frame")
    g.add_argument("--max-frames", type=int, help="stop after this frame number")

    g = p.add_argument_group("data / diagnostics")
    g.add_argument("--stats", action="store_true", help="print history statistics and exit")
    g.add_argument("--dump-events", metavar="FILE.csv", help="write the events to CSV and exit")
    g.add_argument("--file-types", action="store_true",
                   help="print how the files are grouped (share, files, example) and what is unclassified, then exit")
    g.add_argument("--people", metavar="FILE.csv",
                   help="write who is who after merging (names, emails, logins) to CSV and exit")
    g.add_argument("--export-xml", metavar="FILE.xml",
                   help="write a legacy code_swarm event XML (for the old Java tool) and exit")
    g.add_argument("--cache-dir", default=default_cache_dir(), metavar="DIR",
                   help="where clones, parsed histories and avatars are kept")
    g.add_argument("--cache-info", action="store_true", help="show where the cache is and how big, then exit")
    g.add_argument("--clear-cache", nargs="?", const="all", choices=["all", "repos", "events", "avatars"],
                   help="delete cached clones / parsed histories / avatars (default all), then exit")
    g.add_argument("--no-cache", action="store_true", help="re-read history even if cached")
    g.add_argument("--offline", action="store_true", help="do not fetch updates for a cached clone")
    return p


def _overrides(a):
    o = {k: getattr(a, k) for k in (
        "since", "until", "branch", "author_key", "renames", "fps", "frames_per_day",
        "background", "font_color", "avatars", "seed", "utc_dates", "bounds", "ui_scale", "font_size",
        "show_legend", "show_history", "show_date", "show_edges", "show_popular",
        "show_user_name", "draw_names_sharp", "draw_names_halos",
        "draw_files_sharp", "draw_files_fuzzy", "draw_files_jelly", "circular_avatars",
        "legacy_alpha_wrap", "merge_identities", "exclude_bots", "colors", "avatar_size",
        "gravatar_fallback", "local_avatar_dir", "github_api_budget", "ripples", "text_shadow", "dim_idle_names", "show_engine", "caption_font",
        "caption_style", "caption_color", "legend_font", "popular_count", "popular_marks", "show_stats", "stats_window_days",
        "people_count", "histogram_scale", "histogram_max", "popular_style", "popular_window_days", "accent",
        "commit_text", "commit_text_seconds", "commit_text_max", "ticker_lines", "subject_length",
        "status_flash", "author_ticks", "show_releases", "release_tags", "release_gap_seconds", "name_layout",
        "hubs", "hub_min_people", "dim_idle_avatars", "hub_follow", "hub_speed", "hub_gather", "file_size", "hub_rate", "keep_clear")}

    if a.alias:
        o["aliases"] = a.alias
    if a.exclude_author:
        o["exclude_authors"] = a.exclude_author
    if a.include:
        o["include"] = a.include
    if a.exclude:
        o["exclude"] = a.exclude
    if a.size:
        o["width"], o["height"] = a.size
    return o


def _dir_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _cache_cmd(a):
    import shutil
    parts = ["repos", "events", "avatars"]
    if a.clear_cache:
        for part in (parts if a.clear_cache == "all" else [a.clear_cache]):
            path = os.path.join(a.cache_dir, part)
            if os.path.isdir(path):
                size = _dir_size(path)
                shutil.rmtree(path, ignore_errors=True)
                say("Deleted %s (%.1f MB)" % (path, size / 1e6))
        if a.clear_cache == "all" and os.path.isdir(a.cache_dir) and not os.listdir(a.cache_dir):
            os.rmdir(a.cache_dir)
            say("Removed %s" % a.cache_dir)
        return 0
    say("Cache folder: %s" % a.cache_dir)
    for part in parts:
        path = os.path.join(a.cache_dir, part)
        n = len(os.listdir(path)) if os.path.isdir(path) else 0
        say("  %-8s %6d entries  %8.1f MB" % (part, n, _dir_size(path) / 1e6 if n else 0.0))
    return 0


def _month(ms):
    d = datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc)
    return "%s %d" % (["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.month - 1], d.year)


def _apply_linger(cfg, a):
    if a.linger is not None:
        cfg["linger_frames"] = int(round(a.linger * cfg["fps"]))


def _fmt_ms(ms):
    if ms is None:
        return "-"
    return datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        preset = a.preset or (None if a.config else "default")
        cfg = build_config(preset, a.config, _overrides(a), java_escapes=a.java_escapes)
        if a.popular_window_days == 0:          # --popular-window 0 = all time
            cfg["popular_window_days"] = None
    except (ValueError, OSError) as exc:
        warn(exc)
        return 2

    if a.print_config:
        sys.stdout.write(dump_toml(cfg))
        return 0
    if a.cache_info or a.clear_cache:
        return _cache_cmd(a)

    sources = list(a.sources) or ([cfg["_legacy_input_file"]] if cfg.get("_legacy_input_file") else [])
    if not sources:
        warn("no SOURCE given (a repository URL, owner/repo, local path or .xml)")
        return 2
    if any(not s_.lower().endswith(".xml") for s_ in sources) and not git_available():
        warn("git was not found on PATH; install Git for Windows and retry")
        return 2
    source = sources[0]
    if a.caption:
        cfg["caption"] = a.caption
    if a.histogram_max == 0:
        cfg["histogram_max"] = None

    t0 = time.time()
    try:
        events, infos = load_many(sources, cfg, a.cache_dir, use_cache=not a.no_cache,
                                  refresh=not a.offline, prefix=False if a.no_prefix else None)
        info = infos[0]
        meta = info.get("meta_all")
    except (RuntimeError, ValueError) as exc:
        warn(exc)
        return 1
    dt = time.time() - t0
    if not events:
        warn("no events found (check --since/--until/--include/--exclude)")
        return 1

    from .identity import build_people
    raw_ids = len(set((e.name, e.email) for e in events))
    events, people, prep = build_people(events, cfg)
    if not events:
        warn("every event was excluded (check --exclude-author / --keep-bots)")
        return 1
    s = summarize(events)
    for inf in infos:
        say("Source   : %s%s%s" % (inf["source"], "  (from cache)" if inf.get("cached") else "",
                                   ("  [%s: %d events]" % (inf["label"], inf["events"])) if len(infos) > 1 else ""))
        if inf.get("head"):
            say("Head     : %s" % inf["head"])
    say("Events   : %d   commits: %d   people: %d   files: %d"
        % (s["events"], s["commits"], s["authors"], s["files"]))
    say("People   : %d name/email pairs -> %d people%s"
        % (raw_ids, len(people),
           ("; hidden: " + ", ".join("%s (%d)" % kv for kv in sorted(prep["dropped"].items())))
           if prep["dropped"] else ""))
    say("Span     : %s  ->  %s" % (_fmt_ms(s["first_ms"]), _fmt_ms(s["last_ms"])))
    say("Status   : %s" % "  ".join("%s=%d" % kv for kv in sorted(s["status"].items())))
    say("Loaded in %.2f s" % dt)

    if a.dump_events:
        out = unique_path(a.dump_events)
        with open(out, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["date_ms", "date_utc", "person", "git_name", "git_email", "path", "status", "commit"])
            for e in events:
                w.writerow([e.date, _fmt_ms(e.date), e.author, e.name, e.email, e.path, e.status, e.commit])
        say("Wrote %s" % out)
        return 0
    if a.export_xml:
        out = unique_path(a.export_xml)
        write_legacy_xml(out, events)
        say("Wrote %s" % out)
        return 0
    if a.people:
        out = unique_path(a.people)
        with open(out, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["person", "events", "names", "emails", "github_logins"])
            for p in sorted(people.values(), key=lambda q: -q.events):
                w.writerow([p.display, p.events, " | ".join(sorted(p.names)), " | ".join(sorted(p.emails)),
                            " | ".join(sorted(p.logins))])
        say("Wrote %s" % out)
        return 0
    if a.stats:
        return 0

    from .filetypes import Classifier, load_custom_groups, set_active
    custom, custom_colors = ([], {})
    if a.file_groups:
        try:
            custom, custom_colors = load_custom_groups(a.file_groups)
        except (OSError, ValueError, KeyError) as exc:
            warn("cannot read %s: %s" % (a.file_groups, exc))
            return 2
    set_active(Classifier(custom, a.granularity))
    if a.file_types:
        from .colors import file_type_report
        rows = file_type_report(events)
        say("")
        say("%-16s %8s %7s %7s  %s" % ("group", "touches", "share", "files", "example"))
        for g, n, pct, nf, ex in rows:
            say("%-16s %8d %6.1f%% %7d  %s" % (g[:16], n, pct, nf, ex[:70]))
        unk = [r for r in rows if r[0].startswith(".") or r[0] == "(no extension)"]
        say("")
        say("Unclassified: %.1f%% of file touches in %d groups%s"
            % (sum(r[2] for r in unk), len(unk),
               (" - add them with --file-groups if they matter" if unk else "")))
        return 0
    mode = cfg.get("colors") or ("rules" if cfg["color_rules"] else "auto")
    if mode == "auto":
        from .colors import auto_rules
        cfg["color_rules"] = auto_rules(events, custom_colors=custom_colors)
    elif mode == "repo":
        from .colors import repo_rules
        cfg["color_rules"] = repo_rules(events)
    say("Colours  : %s (%s)" % (mode, ", ".join(r["label"].split("  ")[0] for r in cfg["color_rules"]) or "Misc only"))

    _apply_linger(cfg, a)
    try:
        from . import app
    except ImportError as exc:
        warn("rendering needs: pip install numpy moderngl pygame-ce  (%s)" % exc)
        return 2

    # quiet periods, target duration
    from .timeline import compress_gaps, frames_per_day_for, span_days
    time_map = None
    if a.max_gap:
        before = span_days(events)
        events, time_map = compress_gaps(events, a.max_gap)
        say("Gaps     : %d quiet periods over %g days shortened; %.0f -> %.0f days of animation"
            % (len(time_map.skips), a.max_gap, before, span_days(events)))
    title = a.title or " + ".join(inf["label"] for inf in infos)
    if a.no_caption:
        cfg["caption"] = None
    elif not cfg.get("caption") and cfg.get("auto_caption"):
        from .avatars import github_slug
        names = [(github_slug(inf["source"]) or inf["label"]).replace("/", " / ") for inf in infos]
        cfg["caption"] = " + ".join(names)
    intro_s = a.intro if a.intro is not None else (3.0 if a.title else 0.0)
    credits_s = a.credits or 0.0
    if a.duration:
        _apply_linger(cfg, a)
        extra = int(round((intro_s + credits_s) * cfg["fps"])) + int(cfg.get("linger_frames", 0))
        target = max(int(a.duration * cfg["fps"]) - extra, 2)
        cfg["frames_per_day"] = frames_per_day_for(events, target)
        say("Duration : %g s -> %.3f frames per day" % (a.duration, cfg["frames_per_day"]))

    from .avatars import AvatarStore
    from .render import ui_scale
    av_cfg = dict(cfg, avatar_size=int(round(cfg["avatar_size"] * ui_scale(cfg))))
    avatars = AvatarStore(av_cfg, a.cache_dir, source=source, offline=a.offline, token=a.github_token,
                          repo_sources={inf["label"]: inf["source"] for inf in infos}).prefetch(people)

    from .app import ShowSpec
    first_real = time_map.real(events[0].date) if time_map else events[0].date
    last_real = time_map.real(events[-1].date) if time_map else events[-1].date
    subtitle = a.subtitle or ["%s  -  %s" % (_month(first_real), _month(last_real)),
                              "%d people  |  %d commits  |  %d files" % (len(people), s["commits"], s["files"])]
    top = sorted(people.values(), key=lambda q: -q.events)[: max(a.credits_count, 0)]
    spec = ShowSpec(cfg, title=title, subtitle=subtitle,
                    legend=[(r_["label"].split("  ")[0], tuple(r_["color"])) for r_ in cfg["color_rules"]][:9],
                    credits=[(q.display, q.events) for q in top],
                    intro_seconds=intro_s, credits_seconds=credits_s)

    frames_dir = a.frames
    if not frames_dir and cfg.get("take_snapshots"):
        frames_dir = os.path.dirname(cfg["snapshot_location"]) or "frames"
    if a.output or frames_dir:
        out_dir = app.unique_dir(frames_dir) if frames_dir else None
        writer = None
        if a.output:
            from .video import VideoWriter
            out_file = unique_path(a.output)
            try:
                writer = VideoWriter(out_file, cfg["width"], cfg["height"], cfg["fps"],
                                     crf=a.crf, preset=a.encoder_preset)
            except (ValueError, RuntimeError) as exc:
                warn(exc)
                return 2
            say("Rendering video to %s (%dx%d, %d fps, about %d frames) ..."
                % (out_file, cfg["width"], cfg["height"], cfg["fps"],
                   app.estimate_frames(events, cfg, a.max_frames, spec)))
        if out_dir:
            say("Rendering frames to %s ..." % out_dir)
        cb = (lambda n, img: writer.write(img)) if writer else None
        failed = None
        try:
            res = app.run_headless(events, cfg, out_dir, start=a.start_frame, every=max(a.every, 1),
                                   max_frames=a.max_frames, frame_callback=cb, progress=True,
                                   avatars=avatars, spec=spec, time_map=time_map, meta=meta)
        except RuntimeError as exc:                 # ffmpeg died: report it, no traceback
            failed = exc
        finally:
            if writer:
                try:
                    writer.close()
                except RuntimeError as exc:
                    failed = failed or exc
        if failed:
            sys.stdout.write("\n")
            warn(failed)
            return 1
        if writer:
            say("Wrote %s: %d frames, %.1f s of video" % (out_file, writer.frames, writer.frames / float(cfg["fps"])))
        say("Frames: %d simulated, %d written in %.1f s (sim %.1f s, draw %.1f s, output %.1f s)"
            % (res["frames"], res["written"], res["seconds"], res["sim_s"], res["draw_s"], res["io_s"]))
        return 0

    res = app.run_live(events, cfg, title="codeswarm - %s" % os.path.basename(source.rstrip("/\\")),
                       max_frames=a.max_frames, avatars=avatars, spec=spec, time_map=time_map, meta=meta)
    say("Window closed after %d frames (%.1f fps at the end)" % (res["frames"], res["fps"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
