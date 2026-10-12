"""Small helpers shared by all modules. ASCII-only console output."""

import os
import sys


def say(msg=""):
    """Print to the console as pure ASCII (PowerShell 5 safe).

    Non-ASCII characters (accented author names, file names) are
    escaped as \\xNN / \\uNNNN instead of crashing or showing mojibake.
    """
    text = str(msg).encode("ascii", "backslashreplace").decode("ascii")
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def warn(msg):
    text = ("WARNING: " + str(msg)).encode("ascii", "backslashreplace").decode("ascii")
    sys.stderr.write(text + "\n")
    sys.stderr.flush()


def unique_path(path):
    """Return path, or path_1, path_2 ... so an existing file is never overwritten."""
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    n = 1
    while True:
        cand = "%s_%d%s" % (root, n, ext)
        if not os.path.exists(cand):
            return cand
        n += 1


def default_cache_dir():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "codeswarm")
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "codeswarm")
