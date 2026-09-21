#!/usr/bin/env python3
"""Tests for check_parameters.py.

A drift check that never fails proves nothing, so each test deliberately breaks
one thing and asserts the checker catches it with the right message.

Usage:  python tools/test_check_parameters.py [repo_root]
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
CHECKER = REPO / "tools" / "check_parameters.py"


def run_case(name: str, mutate, expect_ok: bool, expect_text: str = "") -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(REPO, work, ignore=shutil.ignore_patterns(".git", "__pycache__", "docs"))
        pfile = work / "product" / "parameters.json"
        data = json.loads(pfile.read_text(encoding="utf-8"))
        mutate(data)
        pfile.write_text(json.dumps(data, indent=2), encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, str(work / "tools" / "check_parameters.py"), str(work)],
            capture_output=True, text=True,
        )
        ok = (proc.returncode == 0)
        passed = (ok == expect_ok) and (expect_text in proc.stdout)
        print(("PASS  " if passed else "FAIL  ") + name)
        if not passed:
            print("      exit=%d expected_ok=%s" % (proc.returncode, expect_ok))
            print("      looked for: %r" % expect_text)
            for line in proc.stdout.strip().splitlines():
                print("      | " + line)
        return passed


def set_param(data, pid, key, value):
    for prm in data["parameters"]:
        if prm["id"] == pid:
            prm[key] = value


CASES = [
    ("unmodified definition passes",
     lambda d: None, True, "OK -"),

    ("slider max drifts from the definition",
     lambda d: set_param(d, "forearm_circumference", "max", 350), False, "max differs"),

    ("slider min drifts from the definition",
     lambda d: set_param(d, "length", "min", 100), False, "min differs"),

    ("default drifts from the definition",
     lambda d: set_param(d, "strut_thickness", "default", 4.5), False, "default differs"),

    ("integer slider declared as a float",
     lambda d: set_param(d, "hoops", "type", "number"), False, "slider integer=True"),

    ("a slider is left undocumented",
     lambda d: d.__setitem__("parameters", [p for p in d["parameters"] if p["id"] != "ribs"]),
     False, "no parameter documents it"),

    ("parameter binds a slider that does not exist",
     lambda d: set_param(d, "ribs", "ghSlider", "Ribs arund"), False, "no slider named"),

    ("default sits outside its own min/max",
     lambda d: set_param(d, "length", "default", 999), False, "outside"),

    ("parameter points at an undefined group",
     lambda d: set_param(d, "ribs", "group", "nosuchgroup"), False, "is not defined"),

    ("output component name is wrong",
     lambda d: d["geometryBackend"].__setitem__("outputComponent", "NOT_THERE"),
     False, "not found in the definition"),
]


def main() -> int:
    if not CHECKER.exists():
        print("checker not found: " + str(CHECKER))
        return 1
    results = [run_case(n, m, ok, txt) for n, m, ok, txt in CASES]
    print("\n%d / %d tests passed" % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
