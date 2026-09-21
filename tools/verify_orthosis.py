#! python 3
# Robustness + print-readiness check for orthosis.gh
#
# 1. Drives every slider to min / mid / max (others at default), plus all-min
#    and all-max, and re-solves. A definition that only works at its defaults
#    is not production grade.
# 2. For each case: counts solver errors, checks output is non-empty, and
#    checks every produced mesh for IsValid / IsClosed (watertight).

import traceback, os, json

DIR = r"C:\Users\admin\Documents\darbs\remote-dach\grasshopper_demo\build"
LOG = os.path.join(DIR, "verify.log")
REPORT = os.path.join(DIR, "verify_report.json")
GH = os.path.join(DIR, "orthosis.gh")


def log(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(str(m) + "\n")


try:
    import System
    import Rhino
    import Rhino.Geometry as rg
    Rhino.RhinoApp.RunScript("_-Grasshopper _Load _Enter", False)
    import Grasshopper
    from Grasshopper.Kernel import GH_DocumentIO, GH_RuntimeMessageLevel
    from Grasshopper.Kernel.Special import GH_NumberSlider

    def dbl(d):
        # System.Decimal converts with neither python float() nor
        # System.Convert.ToDouble (the latter kills the process outright).
        # Round-tripping through its string form is the reliable route.
        return float(str(d))

    io = GH_DocumentIO()
    if not io.Open(GH):
        raise Exception("cannot open " + GH)
    doc = io.Document
    doc.Enabled = True

    sliders = {}
    for o in doc.Objects:
        if isinstance(o, GH_NumberSlider):
            sliders[o.NickName] = o
    log("sliders found: %d" % len(sliders))
    for k, s in sliders.items():
        log("   %-28s min=%s max=%s val=%s" % (k, s.Slider.Minimum, s.Slider.Maximum, s.Slider.Value))

    def comp_by_nick(nick):
        for o in doc.Objects:
            if o.NickName == nick:
                return o
        return None

    merged = comp_by_nick("ORTHOSIS")
    meshed = comp_by_nick("print mesh")
    if merged is None or meshed is None:
        raise Exception("output components not found")

    log('computing defaults...')
    defaults = dict((k, dbl(s.Slider.Value)) for k, s in sliders.items())
    log('defaults = ' + repr(defaults))

    def apply(values):
        for k, v in values.items():
            sliders[k].SetSliderValue(System.Decimal(v))

    def solve_and_check(label, values):
        log('-> case: ' + label)
        apply(defaults)
        apply(values)
        log('   applied, solving...')
        doc.NewSolution(True)
        log('   solved')
        errs, warns = [], []
        for o in doc.Objects:
            for m in o.RuntimeMessages(GH_RuntimeMessageLevel.Error):
                errs.append("%s: %s" % (o.NickName, m))
            for m in o.RuntimeMessages(GH_RuntimeMessageLevel.Warning):
                warns.append("%s: %s" % (o.NickName, m))
        n_brep = merged.Params.Output[0].VolatileData.DataCount
        # inspect meshes
        data = meshed.Params.Output[0].VolatileData
        n_mesh = 0
        n_valid = 0
        n_closed = 0
        for i in range(data.PathCount):
            for goo in data.get_Branch(data.get_Path(i)):
                if goo is None:
                    continue
                try:
                    m = goo.Value
                except Exception:
                    continue
                if not isinstance(m, rg.Mesh):
                    continue
                n_mesh += 1
                if m.IsValid:
                    n_valid += 1
                if m.IsClosed:
                    n_closed += 1
        rec = {
            "case": label,
            "changed": dict((k, dbl(v) if not isinstance(v, float) else v) for k, v in values.items()),
            "errors": len(errs),
            "warnings": len(warns),
            "breps": n_brep,
            "meshes": n_mesh,
            "meshes_valid": n_valid,
            "meshes_closed": n_closed,
            "error_text": errs[:4],
        }
        ok = (len(errs) == 0 and n_brep > 0 and n_mesh == n_valid == n_closed and n_mesh > 0)
        rec["pass"] = ok
        log("%-40s errs=%d breps=%3d mesh=%3d valid=%3d closed=%3d  %s" % (
            label, len(errs), n_brep, n_mesh, n_valid, n_closed, "PASS" if ok else "FAIL"))
        for e in errs[:4]:
            log("        ! " + e)
        return rec

    results = []
    results.append(solve_and_check("defaults", {}))

    for name, s in sliders.items():
        lo = dbl(s.Slider.Minimum)
        hi = dbl(s.Slider.Maximum)
        mid = (lo + hi) / 2.0
        results.append(solve_and_check("%s = min (%g)" % (name, lo), {name: lo}))
        results.append(solve_and_check("%s = mid (%g)" % (name, mid), {name: mid}))
        results.append(solve_and_check("%s = max (%g)" % (name, hi), {name: hi}))

    all_min = dict((k, dbl(s.Slider.Minimum)) for k, s in sliders.items())
    all_max = dict((k, dbl(s.Slider.Maximum)) for k, s in sliders.items())
    results.append(solve_and_check("ALL MIN", all_min))
    results.append(solve_and_check("ALL MAX", all_max))

    # a deliberately awkward one: thickest struts, densest lattice, smallest body
    worst = {
        "Strut thickness mm": dbl(sliders["Strut thickness mm"].Slider.Maximum),
        "Ribs around": dbl(sliders["Ribs around"].Slider.Maximum),
        "Hoops along length": dbl(sliders["Hoops along length"].Slider.Maximum),
        "Forearm circumference mm": dbl(sliders["Forearm circumference mm"].Slider.Minimum),
        "Wrist circumference mm": dbl(sliders["Wrist circumference mm"].Slider.Minimum),
        "Length mm": dbl(sliders["Length mm"].Slider.Minimum),
    }
    results.append(solve_and_check("WORST CASE thick+dense+small", worst))

    passed = sum(1 for r in results if r["pass"])
    log("")
    log("=== %d / %d cases passed ===" % (passed, len(results)))

    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump({"passed": passed, "total": len(results), "cases": results}, f, indent=1)
    log("report written: " + REPORT)

except Exception:
    log("FATAL: " + traceback.format_exc())
