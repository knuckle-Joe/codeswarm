"""Shared start-up check for the tools: fail early with a clear message."""
import importlib
import os
import sys


def require(*modules):
    missing = []
    for m in modules:
        try:
            importlib.import_module(m)
        except ImportError:
            missing.append(m)
    if missing:
        venv_py = os.path.join(".venv", "Scripts", "python.exe") if os.name == "nt" else ".venv/bin/python"
        sys.stderr.write(
            "Missing Python packages: %s\n"
            "This Python (%s) is not the one codeswarm was installed into.\n"
            "Run the tool with the virtual environment's Python, e.g.:\n"
            "    %s %s\n"
            "or activate it first (source .venv/bin/activate / .venv\\Scripts\\activate).\n"
            % (", ".join(missing), sys.executable, venv_py, " ".join(sys.argv)))
        sys.exit(2)
