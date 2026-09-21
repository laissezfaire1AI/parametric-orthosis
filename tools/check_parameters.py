#!/usr/bin/env python3
"""Keep the JSON product definition and the Grasshopper geometry backend in step.

The product UI is described in product/parameters.json. The geometry is produced
by definition/orthosis.ghx. Nothing stops those two drifting apart: someone nudges
a slider range in Grasshopper, the JSON still advertises the old one, and the
clinician gets a form that silently disagrees with the geometry.

This check reads the .ghx directly - it is XML, so no Rhino and no Windows are
needed - and fails the build on any drift.

Checks performed:
  1. parameters.json validates against parameters.schema.json
  2. internal consistency (min <= default <= max, unique ids, groups resolve)
  3. every ghSlider binding exists in the .ghx
  4. min / max / default match the slider exactly
  5. integer parameters are backed by integer-accuracy sliders
  6. no slider in the .ghx is missing from the JSON (nothing undocumented)
  7. the declared output component exists
  8. scriptComponents:false is true in fact - no C#/Python/VB script components,
     which ShapeDiver allows only on paid plans and reviews by hand

Usage:  python tools/check_parameters.py [repo_root]
Exit code 0 on success, 1 on any failure.
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SLIDER_NAME = "Number Slider"
SCRIPT_MARKERS = ("script", "python", "c#", "vb")


def fail(msgs: list[str], msg: str) -> None:
    msgs.append(msg)


def chunk_items(chunk: ET.Element) -> dict:
    out = {}
    items = chunk.find("items")
    if items is not None:
        for item in items.findall("item"):
            out[item.get("name")] = item.text
    return out


def read_ghx(path: Path):
    """Return (sliders, nicknames, component_names) from a Grasshopper .ghx file."""
    root = ET.parse(path).getroot()
    sliders = {}
    nicknames = set()
    component_names = []

    for obj in root.iter("chunk"):
        if obj.get("name") != "Object":
            continue
        obj_items = chunk_items(obj)
        comp_name = obj_items.get("Name") or ""
        component_names.append(comp_name)

        container = None
        for c in obj.iter("chunk"):
            if c.get("name") == "Container":
                container = c
                break
        if container is None:
            continue

        nick = chunk_items(container).get("NickName")
        if nick:
            nicknames.add(nick)

        if comp_name != SLIDER_NAME or not nick:
            continue

        for c in container.iter("chunk"):
            vals = chunk_items(c)
            if "Min" in vals and "Max" in vals:
                sliders[nick] = {
                    "min": float(vals["Min"]),
                    "max": float(vals["Max"]),
                    "value": float(vals.get("Value", "nan")),
                    # Interval carries GH_SliderAccuracy: 0 float, 1 integer
                    "integer": vals.get("Interval") == "1",
                }
                break

    return sliders, nicknames, component_names


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    product_path = root / "product" / "parameters.json"
    schema_path = root / "product" / "parameters.schema.json"

    problems: list[str] = []

    if not product_path.exists():
        print("missing " + str(product_path))
        return 1

    product = json.loads(product_path.read_text(encoding="utf-8"))

    # ---- 1. schema -------------------------------------------------------
    try:
        import jsonschema
    except ImportError:
        print("note: jsonschema not installed, skipping schema validation")
    else:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        for err in sorted(validator.iter_errors(product), key=lambda e: list(e.path)):
            loc = "/".join(str(x) for x in err.path) or "(root)"
            fail(problems, "schema: %s: %s" % (loc, err.message))

    params = product.get("parameters", [])
    groups = {g["id"] for g in product.get("groups", [])}

    # ---- 2. internal consistency ----------------------------------------
    seen_ids, seen_sliders = set(), set()
    for prm in params:
        pid = prm.get("id", "?")
        if pid in seen_ids:
            fail(problems, "duplicate parameter id: %s" % pid)
        seen_ids.add(pid)

        slider_name = prm.get("ghSlider")
        if slider_name in seen_sliders:
            fail(problems, "two parameters bind the same slider: %s" % slider_name)
        seen_sliders.add(slider_name)

        if prm.get("group") not in groups:
            fail(problems, "%s: group '%s' is not defined" % (pid, prm.get("group")))

        lo, hi, dflt = prm.get("min"), prm.get("max"), prm.get("default")
        if None not in (lo, hi) and lo >= hi:
            fail(problems, "%s: min %s is not below max %s" % (pid, lo, hi))
        if None not in (lo, hi, dflt) and not (lo <= dflt <= hi):
            fail(problems, "%s: default %s is outside %s..%s" % (pid, dflt, lo, hi))

    # ---- 3-8. cross-check against the Grasshopper definition -------------
    ghx_rel = product.get("geometryBackend", {}).get("definition", "")
    ghx_path = root / ghx_rel
    if not ghx_path.exists():
        fail(problems, "geometryBackend.definition not found: %s" % ghx_rel)
    else:
        sliders, nicknames, comp_names = read_ghx(ghx_path)

        for prm in params:
            pid = prm.get("id", "?")
            name = prm.get("ghSlider")
            if name not in sliders:
                fail(problems, "%s: no slider named '%s' in %s" % (pid, name, ghx_rel))
                continue
            s = sliders[name]
            if abs(s["min"] - prm["min"]) > 1e-9:
                fail(problems, "%s: min differs - json %s, definition %s" % (pid, prm["min"], s["min"]))
            if abs(s["max"] - prm["max"]) > 1e-9:
                fail(problems, "%s: max differs - json %s, definition %s" % (pid, prm["max"], s["max"]))
            if abs(s["value"] - prm["default"]) > 1e-9:
                fail(problems, "%s: default differs - json %s, definition %s" % (pid, prm["default"], s["value"]))
            wants_int = prm.get("type") == "integer"
            if wants_int != s["integer"]:
                fail(problems, "%s: json type '%s' but slider integer=%s" % (pid, prm.get("type"), s["integer"]))

        undocumented = sorted(set(sliders) - seen_sliders)
        for name in undocumented:
            fail(problems, "slider '%s' exists in the definition but no parameter documents it" % name)

        out_comp = product.get("geometryBackend", {}).get("outputComponent")
        if out_comp and out_comp not in nicknames:
            fail(problems, "outputComponent '%s' not found in the definition" % out_comp)

        declared_scripts = product.get("geometryBackend", {}).get("scriptComponents", False)
        actual_scripts = sorted({
            n for n in comp_names
            if any(m in n.lower() for m in SCRIPT_MARKERS)
        })
        if actual_scripts and not declared_scripts:
            fail(problems, "scriptComponents is false but the definition contains: %s" % ", ".join(actual_scripts))

        print("definition: %d sliders, %d objects" % (len(sliders), len(comp_names)))

    print("parameters: %d in %d groups" % (len(params), len(groups)))

    if problems:
        print("\nFAILED - %d problem(s):" % len(problems))
        for m in problems:
            print("  - " + m)
        return 1

    print("\nOK - JSON product definition and Grasshopper definition agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
