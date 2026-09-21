#! python 3
# Generates the parametric forearm orthosis Grasshopper definition.
#
# Native components only - no C#/Python script components, because ShapeDiver
# allows scripting only on paid plans and every script needs manual review.
#
# The lattice is built explicitly from geometry (Divide Curve + Line for the
# ribs, interpolated arcs for the hoops) instead of from surface isocurves.
# Isocurves would need the Surface input flagged "Reparameterize", because a
# lofted surface does NOT have a 0..1 UV domain. That flag is a right-click
# option - invisible in the graph and easy to lose in a hand-over. Building
# the struts directly keeps the definition readable and removes the trap.
# Both ribs and hoops lie exactly on the ruled loft surface by construction.
#
# Output: orthosis.gh (binary, for ShapeDiver) + orthosis.ghx (XML, git-diffable)

import traceback, os

OUT_DIR = r"C:\Users\admin\Documents\darbs\remote-dach\grasshopper_demo\build"
LOG = os.path.join(OUT_DIR, "build.log")


def log(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(str(m) + "\n")


try:
    import System
    from System.Drawing import PointF
    import Rhino
    Rhino.RhinoApp.RunScript("_-Grasshopper _Load _Enter", False)
    import Grasshopper
    from Grasshopper.Kernel import GH_Document, GH_DocumentIO, GH_RuntimeMessageLevel
    from Grasshopper.Kernel.Special import GH_NumberSlider
    from Grasshopper.Kernel.Parameters import Param_Number, Param_Integer, Param_Boolean
    from Grasshopper.Kernel.Types import GH_Number, GH_Integer, GH_Boolean
    from Grasshopper.GUI.Base import GH_SliderAccuracy

    srv = Grasshopper.Instances.ComponentServer
    doc = GH_Document()
    doc.Enabled = True

    def add(name, x, y, nick=None):
        proxy = srv.FindObjectByName(name, True, True)
        if proxy is None:
            raise Exception("component not found: " + name)
        o = srv.EmitObject(proxy.Guid)
        if o is None:
            raise Exception("emit failed: " + name)
        o.CreateAttributes()
        o.Attributes.Pivot = PointF(float(x), float(y))
        if nick:
            o.NickName = nick
        doc.AddObject(o, False)
        return o

    def slider(nick, lo, hi, val, x, y, integer=False):
        s = GH_NumberSlider()
        s.CreateAttributes()
        s.Slider.Minimum = System.Decimal(lo)
        s.Slider.Maximum = System.Decimal(hi)
        if integer:
            s.Slider.Type = GH_SliderAccuracy.Integer
            s.Slider.DecimalPlaces = 0
        else:
            s.Slider.DecimalPlaces = 1
        s.SetSliderValue(System.Decimal(val))
        s.NickName = nick
        s.Attributes.Pivot = PointF(float(x), float(y))
        doc.AddObject(s, False)
        return s

    def const(kind, val, x, y, nick):
        if kind == "n":
            p, goo = Param_Number(), GH_Number(float(val))
        elif kind == "i":
            p, goo = Param_Integer(), GH_Integer(int(val))
        else:
            p, goo = Param_Boolean(), GH_Boolean(bool(val))
        p.CreateAttributes()
        p.NickName = nick
        p.PersistentData.Append(goo)
        p.Attributes.Pivot = PointF(float(x), float(y))
        doc.AddObject(p, False)
        return p

    def wire(target, in_idx, source, out_idx=None):
        src = source if out_idx is None else source.Params.Output[out_idx]
        target.Params.Input[in_idx].AddSource(src)

    log("=== BUILD START ===")

    # ---- column 0: user parameters (these become the ShapeDiver UI controls) ----
    X0 = 0
    s_fore = slider("Forearm circumference mm", 200, 340, 260, X0, 20)
    s_wrist = slider("Wrist circumference mm", 130, 230, 170, X0, 60)
    s_len = slider("Length mm", 120, 280, 200, X0, 100)
    s_strut = slider("Strut thickness mm", 1.5, 5.0, 3.0, X0, 140)
    s_nlen = slider("Hoops along length", 4, 16, 8, X0, 180, integer=True)
    s_narnd = slider("Ribs around", 6, 24, 12, X0, 220, integer=True)
    s_open = slider("Opening angle deg", 200, 330, 290, X0, 260)

    # ---- constants: plain params, not sliders, so they stay out of the UI ----
    c_two = const("n", 2.0, X0, 320, "two")
    c_zero = const("n", 0.0, X0, 350, "zero")
    c_one = const("n", 1.0, X0, 380, "one")
    c_rim = const("n", 1.6, X0, 410, "rim factor")
    c_caps = const("i", 2, X0, 440, "caps round")
    c_false = const("b", False, X0, 470, "false")

    # ---- column 1: maths ----
    X1 = 300
    pi2 = add("Pi", X1, 20, "two pi")
    wire(pi2, 0, c_two)

    r_fore = add("Division", X1, 70, "r forearm")
    wire(r_fore, 0, s_fore)
    wire(r_fore, 1, pi2, 0)

    r_wrist = add("Division", X1, 120, "r wrist")
    wire(r_wrist, 0, s_wrist)
    wire(r_wrist, 1, pi2, 0)

    ang_rad = add("Radians", X1, 170, "open rad")
    wire(ang_rad, 0, s_open)

    r_strut = add("Division", X1, 220, "strut r")
    wire(r_strut, 0, s_strut)
    wire(r_strut, 1, c_two)

    r_rim = add("Multiplication", X1, 270, "rim r")
    wire(r_rim, 0, r_strut, 0)
    wire(r_rim, 1, c_rim)

    dom_ang = add("Construct Domain", X1, 320, "angle domain")
    wire(dom_ang, 0, c_zero)
    wire(dom_ang, 1, ang_rad, 0)

    dom_01 = add("Construct Domain", X1, 370, "zero to one")
    wire(dom_01, 0, c_zero)
    wire(dom_01, 1, c_one)

    # ---- column 2: the two end sections ----
    X2 = 600
    pt0 = add("Construct Point", X2, 20, "base point")
    wire(pt0, 0, c_zero)
    wire(pt0, 1, c_zero)
    wire(pt0, 2, c_zero)

    pt1 = add("Construct Point", X2, 90, "top point")
    wire(pt1, 0, c_zero)
    wire(pt1, 1, c_zero)
    wire(pt1, 2, s_len)

    pl0 = add("XY Plane", X2, 160, "base plane")
    wire(pl0, 0, pt0, 0)

    pl1 = add("XY Plane", X2, 210, "top plane")
    wire(pl1, 0, pt1, 0)

    arc0 = add("Arc", X2, 260, "forearm section")
    wire(arc0, 0, pl0, 0)
    wire(arc0, 1, r_fore, 0)
    wire(arc0, 2, dom_ang, 0)

    arc1 = add("Arc", X2, 330, "wrist section")
    wire(arc1, 0, pl1, 0)
    wire(arc1, 1, r_wrist, 0)
    wire(arc1, 2, dom_ang, 0)

    # ---- column 3: body surface (used for the rim edges) ----
    X3 = 900
    loft = add("Loft", X3, 20, "body surface")
    wire(loft, 0, arc0, 0)
    wire(loft, 0, arc1, 0)

    # ---- ribs: divide both end arcs, join point i to point i ----
    div0 = add("Divide Curve", X3, 90, "split forearm")
    wire(div0, 0, arc0, 0)
    wire(div0, 1, s_narnd)
    wire(div0, 2, c_false)

    div1 = add("Divide Curve", X3, 160, "split wrist")
    wire(div1, 0, arc1, 0)
    wire(div1, 1, s_narnd)
    wire(div1, 2, c_false)

    ribs = add("Line", X3, 230, "ribs")
    wire(ribs, 0, div0, 0)
    wire(ribs, 1, div1, 0)

    # ---- hoops: rings at interpolated height and radius ----
    t_rng = add("Range", X3, 300, "t 0 to 1")
    wire(t_rng, 0, dom_01, 0)
    wire(t_rng, 1, s_nlen)

    d_r = add("Subtraction", X3, 350, "radius delta")
    wire(d_r, 0, r_wrist, 0)
    wire(d_r, 1, r_fore, 0)

    dr_t = add("Multiplication", X3, 400, "delta x t")
    wire(dr_t, 0, d_r, 0)
    wire(dr_t, 1, t_rng, 0)

    radii = add("Addition", X3, 450, "hoop radii")
    wire(radii, 0, r_fore, 0)
    wire(radii, 1, dr_t, 0)

    z_vals = add("Multiplication", X3, 500, "hoop heights")
    wire(z_vals, 0, s_len)
    wire(z_vals, 1, t_rng, 0)

    # ---- column 4: hoop planes and arcs ----
    X4 = 1200
    h_pts = add("Construct Point", X4, 20, "hoop centres")
    wire(h_pts, 0, c_zero)
    wire(h_pts, 1, c_zero)
    wire(h_pts, 2, z_vals, 0)

    h_pl = add("XY Plane", X4, 90, "hoop planes")
    wire(h_pl, 0, h_pts, 0)

    hoops = add("Arc", X4, 140, "hoops")
    wire(hoops, 0, h_pl, 0)
    wire(hoops, 1, radii, 0)
    wire(hoops, 2, dom_ang, 0)

    edges = add("Brep Edges", X4, 220, "rim curves")
    wire(edges, 0, loft, 0)

    # ---- column 5: pipes ----
    X5 = 1500
    pipe_lat = add("Pipe", X5, 20, "lattice struts")
    wire(pipe_lat, 0, ribs, 0)
    wire(pipe_lat, 0, hoops, 0)
    wire(pipe_lat, 1, r_strut, 0)
    wire(pipe_lat, 2, c_caps)
    wire(pipe_lat, 3, c_false)

    pipe_rim = add("Pipe", X5, 120, "rim")
    wire(pipe_rim, 0, edges, 0)
    wire(pipe_rim, 1, r_rim, 0)
    wire(pipe_rim, 2, c_caps)
    wire(pipe_rim, 3, c_false)

    # ---- column 6: output ----
    X6 = 1800
    merged = add("Merge", X6, 20, "ORTHOSIS")
    wire(merged, 0, pipe_lat, 0)
    wire(merged, 1, pipe_rim, 0)

    meshed = add("Mesh Brep", X6, 100, "print mesh")
    wire(meshed, 0, merged, 0)

    # ---- preview: ShapeDiver renders EVERY preview-enabled component, not just
    # the one you think of as the output. Left alone, the lofted body surface
    # draws as a solid shell and hides the lattice completely. Hide every
    # intermediate and leave only the final merged result visible.
    hidden = 0
    for o in doc.Objects:
        if hasattr(o, "Hidden"):
            o.Hidden = True
            hidden += 1
    merged.Hidden = False
    log("preview hidden on %d objects, visible output = %s" % (hidden, merged.NickName))

    log("objects added: %d" % doc.ObjectCount)

    # ---- solve and report ----
    doc.NewSolution(True)
    log("solution done. runtime messages:")
    errs = 0
    for o in doc.Objects:
        for lvl in (GH_RuntimeMessageLevel.Error, GH_RuntimeMessageLevel.Warning):
            for m in o.RuntimeMessages(lvl):
                log("   [%s] %s (%s): %s" % (lvl, o.NickName, o.GetType().Name, m))
                if lvl == GH_RuntimeMessageLevel.Error:
                    errs += 1
    log("ERROR COUNT = %d" % errs)

    for nm, comp in (("loft", loft), ("ribs", ribs), ("hoops", hoops),
                     ("lattice", pipe_lat), ("rim", pipe_rim),
                     ("merged", merged), ("mesh", meshed)):
        try:
            log("  %-8s output count = %d" % (nm, comp.Params.Output[0].VolatileData.DataCount))
        except Exception as e:
            log("  %-8s read fail: %s" % (nm, e))

    # ---- save ----
    io = GH_DocumentIO(doc)
    ok1 = io.SaveQuiet(os.path.join(OUT_DIR, "orthosis.gh"))
    ok2 = io.SaveQuiet(os.path.join(OUT_DIR, "orthosis.ghx"))
    log("saved gh=%s ghx=%s" % (ok1, ok2))
    log("=== BUILD END ===")

except Exception:
    log("FATAL: " + traceback.format_exc())
