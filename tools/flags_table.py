"""Build the flag reference table of the README straight from the program's
own argument parser, so the documentation can never drift from the code.

Usage:
  python tools/flags_table.py                    # print the Markdown table
  python tools/flags_table.py --update-readme    # replace the table in README.md
  python tools/flags_table.py --check            # exit 1 if README.md is out of date

The table sits in README.md between the markers
  <!-- FLAGS:BEGIN -->  and  <!-- FLAGS:END -->
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from codeswarm.cli import build_parser          # noqa: E402
from codeswarm.config import build_config      # noqa: E402

BEGIN, END = "<!-- FLAGS:BEGIN -->", "<!-- FLAGS:END -->"


def _default(action, cfg):
    if isinstance(action, (argparse._HelpAction, argparse._VersionAction)):
        return ""
    d = action.default
    if d not in (None, False, argparse.SUPPRESS) and not isinstance(action, argparse._StoreTrueAction):
        return str(d)
    key = action.dest
    if key in cfg and cfg[key] not in (None, [], ""):
        v = cfg[key]
        if isinstance(v, bool):
            return "on" if v else "off"
        if isinstance(v, list):
            return ",".join(str(x) for x in v)
        return str(v)
    if isinstance(action, argparse._StoreTrueAction):
        return "off"
    return ""


def _flag(action):
    opts = [o for o in action.option_strings]
    if isinstance(action, argparse.BooleanOptionalAction):
        opts = [o for o in opts if not o.startswith("--no-")]
        return " ".join("`%s` / `--no-%s`" % (o, o[2:]) for o in opts)
    return " ".join("`%s`" % o for o in opts)


def _arg(action):
    if action.nargs == 0 or isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction,
                                                argparse.BooleanOptionalAction)):
        return ""
    if action.choices:
        return " \\| ".join(str(c) for c in action.choices)
    return action.metavar or action.dest.upper()


def table():
    p = build_parser()
    cfg = build_config("default")
    cfg["width"], cfg["height"] = 1920, 1080
    lines = []
    for group in p._action_groups:
        acts = [a for a in group._group_actions]
        if not acts:
            continue
        title = group.title
        if title in ("options", "optional arguments"):
            title = "general"
        if title == "positional arguments":
            title = "sources"
        lines.append("")
        lines.append("### %s" % title.capitalize())
        lines.append("")
        lines.append("| flag | value | default | what it does |")
        lines.append("|---|---|---|---|")
        for a in acts:
            flag = _flag(a) if a.option_strings else "`%s`" % (a.metavar or a.dest).upper()
            if a.dest == "size":
                dflt = "1920x1080"
            elif a.dest == "preset":
                dflt = "default"
            elif a.dest == "cache_dir":
                dflt = "~/.cache/codeswarm"
            else:
                dflt = _default(a, cfg)
            helptext = (a.help or "").replace("|", "\\|").replace("%%", "%")
            lines.append("| %s | %s | %s | %s |" % (flag, _arg(a).replace(" \\| ", "|").replace("|", " \\| "), dflt.replace("|", "\\|"), helptext))
    return "\n".join(lines).strip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update-readme", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    t = table()
    readme = os.path.join(ROOT, "README.md")
    if not (a.update_readme or a.check):
        sys.stdout.write(t)
        return 0
    with open(readme, "r", encoding="utf-8") as fh:
        text = fh.read()
    if BEGIN not in text or END not in text:
        print("README.md has no %s ... %s markers" % (BEGIN, END))
        return 1
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    new = head + BEGIN + "\n" + t + END + tail
    if a.check:
        same = new == text
        print("README flag table is %s" % ("up to date" if same else "OUT OF DATE (run --update-readme)"))
        return 0 if same else 1
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write(new)
    print("README.md flag table updated (%d flags)" % t.count("\n| `"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
