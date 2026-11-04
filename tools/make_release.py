"""
Writes version.json from AXIS_Panel.py, so the version and the changelog
live in a single place (PANEL_VERSION and PANEL_CHANGELOG in the script).

Usage, from the repository root:
    python tools/make_release.py

The installed panels read "version" to detect an update, and from 0.6.6
"changelog" to show its changes before installing. Older panels ignore it.
"""
import ast
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "AXIS_Panel.py"
OUT = ROOT / "version.json"
KEEP = 6  # versions of notes kept in version.json


def read_constants(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], "id", None)
            if name in ("PANEL_VERSION", "PANEL_CHANGELOG"):
                found[name] = ast.literal_eval(node.value)
    return found


def main():
    c = read_constants(SCRIPT)
    version = list(c["PANEL_VERSION"])
    vstr = ".".join(map(str, version))
    log = c.get("PANEL_CHANGELOG", {})
    if vstr not in log or not log[vstr]:
        sys.exit(f"PANEL_CHANGELOG has no notes for {vstr}. Add them before releasing.")
    order = sorted(log, key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True)
    data = {"version": version, "changelog": {v: log[v] for v in order[:KEEP]}}
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"version.json -> {vstr} ({len(data['changelog'])} versions of notes)")


if __name__ == "__main__":
    main()
