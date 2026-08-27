"""
plane_model.py
--------------
A320 aircraft model. When a320_cockpit_2.glb is present, uses the detailed
mesh (fuselage, wings, engines, cockpit interior, landing gear) and adds
procedural animated control surfaces (ailerons, flaps, spoilers, rudder,
elevators) on top. Falls back to a fully procedural model if the glb is missing.

Real A320-200 dimensions used:
  length      37.6 m
  wingspan    34.1 m
  height      11.8 m
  wing sweep  25 deg
  engines     2 x CFM56 under wings
"""

import os
from panda3d.core import (
    Geom, GeomNode, GeomVertexData, GeomVertexFormat, GeomVertexWriter,
    GeomTriangles, NodePath, Vec3, Vec4, Point3, LVector3,
    ColorBlendAttrib, TransparencyAttrib,
)
import math


# ----------------------------------------------------------------------
# Low-level primitive builders
# ----------------------------------------------------------------------
def _make_box_geom(sx, sy, sz, color=(1, 1, 1, 1)):
    """Axis-aligned box centered on origin. sx/sy/sz are full extents."""
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    # 6 faces × 4 verts each. Face normals set so lighting looks right.
    faces = [
        # (normal, four corners CCW when viewed from outside)
        ((0, 0, 1),  [(-hx,-hy, hz),( hx,-hy, hz),( hx, hy, hz),(-hx, hy, hz)]),  # +Z
        ((0, 0,-1),  [(-hx, hy,-hz),( hx, hy,-hz),( hx,-hy,-hz),(-hx,-hy,-hz)]),  # -Z
        ((0, 1, 0),  [( hx, hy,-hz),(-hx, hy,-hz),(-hx, hy, hz),( hx, hy, hz)]),  # +Y
        ((0,-1, 0),  [(-hx,-hy,-hz),( hx,-hy,-hz),( hx,-hy, hz),(-hx,-hy, hz)]),  # -Y
        (( 1, 0, 0), [( hx,-hy,-hz),( hx, hy,-hz),( hx, hy, hz),( hx,-hy, hz)]),  # +X
        ((-1, 0, 0), [(-hx, hy,-hz),(-hx,-hy,-hz),(-hx,-hy, hz),(-hx, hy, hz)]),  # -X
    ]

    fmt = GeomVertexFormat.getV3n3c4()
    vdata = GeomVertexData('box', fmt, Geom.UHStatic)
    vdata.setNumRows(24)
    vwr = GeomVertexWriter(vdata, 'vertex')
    nwr = GeomVertexWriter(vdata, 'normal')
    cwr = GeomVertexWriter(vdata, 'color')

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0
    for normal, corners in faces:
        for c in corners:
            vwr.addData3(*c)
            nwr.addData3(*normal)
            cwr.addData4(*color)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode('box')
    node.addGeom(geom)
    return NodePath(node)


def _make_cylinder_geom(radius, length, segments=16, color=(1, 1, 1, 1),
                        axis='x', radius_end=None):
    """Cylinder or tapered cylinder centered on origin."""
    fmt = GeomVertexFormat.getV3n3c4()
    vdata = GeomVertexData('cyl', fmt, Geom.UHStatic)
    vwr = GeomVertexWriter(vdata, 'vertex')
    nwr = GeomVertexWriter(vdata, 'normal')
    cwr = GeomVertexWriter(vdata, 'color')
    tris = GeomTriangles(Geom.UHStatic)

    hl = length / 2

    def pos(a_pos, x, y):
        """Convert (axis_pos, plane_x, plane_y) to (X,Y,Z) based on axis."""
        if axis == 'x':
            return (a_pos, x, y)
        if axis == 'y':
            return (x, a_pos, y)
        return (x, y, a_pos)

    def norm(x, y):
        if axis == 'x':
            return (0, x, y)
        if axis == 'y':
            return (x, 0, y)
        return (x, y, 0)

    idx = 0
    # Side walls
    for i in range(segments):
        a0 = 2 * math.pi * i / segments
        a1 = 2 * math.pi * (i + 1) / segments
        x0, y0 = math.cos(a0) * radius, math.sin(a0) * radius
        x1, y1 = math.cos(a1) * radius, math.sin(a1) * radius
        n0 = (math.cos(a0), math.sin(a0))
        n1 = (math.cos(a1), math.sin(a1))

        end_radius = radius if radius_end is None else radius_end
        v = [
            (pos(-hl, x0, y0), norm(*n0)),
            (pos( hl, x0 * end_radius / radius, y0 * end_radius / radius), norm(*n0)),
            (pos( hl, x1 * end_radius / radius, y1 * end_radius / radius), norm(*n1)),
            (pos(-hl, x1, y1), norm(*n1)),
        ]
        for p, n in v:
            vwr.addData3(*p); nwr.addData3(*n); cwr.addData4(*color)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

    # End caps
    for cap_pos, cap_norm in ((-hl, -1), (hl, 1)):
        center_idx = idx
        vwr.addData3(*pos(cap_pos, 0, 0))
        nwr.addData3(*(norm(0, 0)[:2] + (cap_norm,) if axis == 'z'
                       else (cap_norm, 0, 0) if axis == 'x'
                       else (0, cap_norm, 0)))
        cwr.addData4(*color)
        idx += 1
        ring_start = idx
        for i in range(segments):
            a = 2 * math.pi * i / segments
            cap_radius = radius if cap_norm < 0 else (
                radius if radius_end is None else radius_end
            )
            x, y = math.cos(a) * cap_radius, math.sin(a) * cap_radius
            vwr.addData3(*pos(cap_pos, x, y))
            # normal points along the axis
            if axis == 'x':   nwr.addData3(cap_norm, 0, 0)
            elif axis == 'y': nwr.addData3(0, cap_norm, 0)
            else:             nwr.addData3(0, 0, cap_norm)
            cwr.addData4(*color)
            idx += 1
        for i in range(segments):
            a, b = ring_start + i, ring_start + (i + 1) % segments
            if cap_norm > 0:
                tris.addVertices(center_idx, a, b)
            else:
                tris.addVertices(center_idx, b, a)

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode('cyl')
    node.addGeom(geom)
    return NodePath(node)


def _make_glow(color=(1, 1, 1, 1), size=0.5):
    """Billboard glow disc for aircraft lights — three-layer radial fade.

    Uses additive blending so glows look bright against dark backgrounds
    and blend naturally in daylight.  Always faces the camera.
    """
    r, g, b, _ = color
    segments = 12
    layers = [
        (size * 0.25, (r, g, b, 1.0)),        # bright core
        (size * 0.65, (r, g, b, 0.55)),        # mid halo
        (size * 1.40, (r, g, b, 0.18)),        # soft bloom
    ]

    fmt = GeomVertexFormat.getV3n3c4()
    vdata = GeomVertexData('glow', fmt, Geom.UHStatic)
    vwr = GeomVertexWriter(vdata, 'vertex')
    nwr = GeomVertexWriter(vdata, 'normal')
    cwr = GeomVertexWriter(vdata, 'color')
    tris = GeomTriangles(Geom.UHStatic)

    idx = 0
    for radius, col in layers:
        # Center vertex — full layer colour
        vwr.addData3(0, 0, 0)
        nwr.addData3(0, 1, 0)
        cwr.addData4(*col)
        center = idx
        idx += 1
        # Ring vertices — transparent at the rim for radial fade
        for i in range(segments):
            a = 2 * math.pi * i / segments
            vwr.addData3(math.cos(a) * radius, 0, math.sin(a) * radius)
            nwr.addData3(0, 1, 0)
            cwr.addData4(col[0], col[1], col[2], 0.0)
            idx += 1
        for i in range(segments):
            tris.addVertices(center, center + 1 + i,
                             center + 1 + (i + 1) % segments)

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    gn = GeomNode('glow')
    gn.addGeom(geom)
    np = NodePath(gn)
    np.setLightOff()
    np.setDepthWrite(False)
    np.setTransparency(TransparencyAttrib.MAlpha)
    np.setAttrib(ColorBlendAttrib.make(
        ColorBlendAttrib.MAdd,
        ColorBlendAttrib.OIncomingAlpha,
        ColorBlendAttrib.OOne))
    np.setBin('transparent', 22)
    np.setBillboardPointEye()
    return np


# ----------------------------------------------------------------------
# Build the A320
# ----------------------------------------------------------------------
FUSELAGE_COLOR = (0.94, 0.94, 0.95, 1)   # off-white
WING_COLOR     = (0.90, 0.90, 0.92, 1)
TAIL_COLOR     = (0.15, 0.30, 0.60, 1)   # blue tail (generic livery)
ENGINE_COLOR   = (0.85, 0.85, 0.88, 1)
GEAR_COLOR     = (0.25, 0.25, 0.27, 1)
CONTROL_COLOR  = (0.80, 0.80, 0.82, 1)
SURFACE_COLOR  = (0.72, 0.72, 0.74, 1)   # slightly darker for HD surfaces
GEAR_BAY_COLOR = (0.18, 0.18, 0.20, 1)   # dark gear bay fairings


def _build_gear(name, x, y, z, leg_len=2.5, main=False):
    """Build a landing-gear strut with wheels, positioned at (x, y, z)."""
    gear = NodePath(name)
    leg = _make_cylinder_geom(0.15, leg_len, segments=8,
                              color=GEAR_COLOR, axis='z')
    leg.setZ(-leg_len / 2)
    leg.reparentTo(gear)

    wheel_positions = (
        ((-0.28, 0.0), (0.28, 0.0)) if not main else
        ((-0.42, -0.58), (0.42, -0.58),
         (-0.42, 0.58), (0.42, 0.58))
    )
    for wheel_x, wheel_y in wheel_positions:
        wheel = _make_cylinder_geom(0.5, 0.28, segments=12,
                                    color=(0.1, 0.1, 0.1, 1), axis='x')
        wheel.setPos(wheel_x, wheel_y, -leg_len)
        wheel.reparentTo(gear)

    if main:
        bogie = _make_box_geom(0.18, 1.7, 0.18, color=GEAR_COLOR)
        bogie.setZ(-leg_len + 0.05)
        bogie.reparentTo(gear)
    gear.setPos(x, y, z)
    return gear


def _load_glb_body():
    """Load a320_cockpit_2.glb, scale and centre it. Returns NodePath or None."""
    glb_path = os.path.join(os.path.dirname(__file__), 'a320_cockpit_2.glb')
    if not os.path.isfile(glb_path):
        return None
    try:
        from panda3d.core import Loader, Filename, LoaderOptions
        ldr = Loader.getGlobalPtr()
        node = ldr.loadSync(Filename.fromOsSpecific(glb_path), LoaderOptions())
        if node is None:
            return None
        model = NodePath(node)
        # Model is already Z-up — no HPR rotation needed.

        wrapper = NodePath('glb_body')
        model.reparentTo(wrapper)
        bounds = wrapper.getTightBounds()
        if bounds:
            lo, hi = bounds
            # Centre X and Y; leave Z at raw position so the cockpit
            # sits at Z ≈ 0.7 after scaling (matching camera eye height).
            model.setPos(-(lo.x + hi.x) / 2,
                         -(lo.y + hi.y) / 2,
                         0)
            # Scale to match old model's fuselage length (~37.67 units)
            raw_len = max(hi.y - lo.y, 0.01)
            wrapper.setScale(37.67 / raw_len)
        return wrapper
    except Exception:
        return None


def _add_animated_surfaces(plane):
    """Add procedural animated control surfaces matched to a320_cockpit_2.glb.

    Each surface gets a **pivot NodePath** at the hinge line.  The box
    geometry is attached as a child, offset so the hinge edge sits at
    the pivot origin.  Coordinates derived from vertex-level analysis
    of the centred/scaled a320_cockpit_2.glb mesh.
    """

    THICKNESS = 0.05   # thin overlay

    # --- Ailerons (outer wing trailing edge, X ≈ 11–16) ---------------
    # Trailing edge sweep ≈ 21° in this region.
    # Wing Z follows dihedral: Z ≈ 0.03 @X=11, Z ≈ 0.47 @X=16
    for side_sign in (-1, 1):
        side = 'right' if side_sign > 0 else 'left'
        chord = 0.7
        pivot = NodePath(f'aileron_{side}')
        pivot.setX(side_sign * 13.5)
        pivot.setY(-2.0)                     # hinge (forward edge)
        pivot.setZ(0.15)                     # wing surface Z @X=13.5
        pivot.setH(side_sign * -21)          # trailing-edge sweep
        pivot.reparentTo(plane)
        geom = _make_box_geom(4.5, chord, THICKNESS, color=SURFACE_COLOR)
        geom.setY(-chord / 2)
        geom.reparentTo(pivot)

    # --- Flaps (inner wing trailing edge, X ≈ 4–10) ------------------
    # Trailing edge sweep ≈ 6° in this region.
    # Wing Z: ≈ -0.55 @X=6, ≈ -0.10 @X=10
    for side_sign in (-1, 1):
        side = 'right' if side_sign > 0 else 'left'
        chord = 1.0
        pivot = NodePath(f'flap_{side}')
        pivot.setX(side_sign * 7.0)
        pivot.setY(-0.3 + chord / 2)        # hinge (forward edge)
        pivot.setZ(-0.35)                    # wing surface Z @X=7
        pivot.setH(side_sign * -6)           # trailing-edge sweep
        pivot.reparentTo(plane)
        geom = _make_box_geom(5.5, chord, THICKNESS, color=SURFACE_COLOR)
        geom.setY(-chord / 2)
        geom.reparentTo(pivot)

    # --- Spoilers (on wing top surface) -------------------------------
    for side_sign in (-1, 1):
        side = 'right' if side_sign > 0 else 'left'
        chord = 1.0

        # Inner spoiler @X ≈ 7 (wing top Z ≈ -0.23)
        pivot1 = NodePath(f'spoiler_{side}_1')
        pivot1.setX(side_sign * 7.0)
        pivot1.setY(0.8)
        pivot1.setZ(-0.20)
        pivot1.setH(side_sign * -6)
        pivot1.reparentTo(plane)
        geom1 = _make_box_geom(3.0, chord, THICKNESS, color=SURFACE_COLOR)
        geom1.setY(-chord / 2)
        geom1.setZ(THICKNESS / 2)
        geom1.reparentTo(pivot1)

        # Outer spoiler @X ≈ 11 (wing top Z ≈ 0.13)
        pivot2 = NodePath(f'spoiler_{side}_2')
        pivot2.setX(side_sign * 11.0)
        pivot2.setY(-0.5)
        pivot2.setZ(0.10)
        pivot2.setH(side_sign * -15)
        pivot2.reparentTo(plane)
        geom2 = _make_box_geom(3.0, chord, THICKNESS, color=SURFACE_COLOR)
        geom2.setY(-chord / 2)
        geom2.setZ(THICKNESS / 2)
        geom2.reparentTo(pivot2)

    # --- Rudder (aft edge of vertical fin) ----------------------------
    # Fin trailing edge Y ≈ -17.8 @Z=2, Y ≈ -18.3 @Z=8
    # Fin mid-height Z ≈ 4.5
    chord_r = 1.2
    pivot_r = NodePath('rudder')
    pivot_r.setY(-17.0)                      # hinge (forward edge)
    pivot_r.setZ(4.5)                        # fin mid-height
    pivot_r.reparentTo(plane)
    geom_r = _make_box_geom(0.25, chord_r, 5.5, color=SURFACE_COLOR)
    geom_r.setY(-chord_r / 2)
    geom_r.reparentTo(pivot_r)

    # --- Elevators (trailing edge of horizontal stab) -----------------
    # Stab trailing edge: Y ≈ -18.1 @X=±6, Z ≈ 1.3
    for side_sign in (-1, 1):
        side = 'right' if side_sign > 0 else 'left'
        chord_e = 0.8
        pivot_e = NodePath(f'elevator_{side}')
        pivot_e.setX(side_sign * 3.5)
        pivot_e.setY(-17.2 + chord_e / 2)   # hinge
        pivot_e.setZ(1.3)                    # stab surface level
        pivot_e.setH(side_sign * -5)
        pivot_e.reparentTo(plane)
        geom_e = _make_box_geom(5.0, chord_e, THICKNESS, color=SURFACE_COLOR)
        geom_e.setY(-chord_e / 2)
        geom_e.reparentTo(pivot_e)


def _add_aircraft_lights(plane, hd=True):
    """Add A320 exterior lights matching real positions.

    Light types and their behaviour (animated by main.py):
        nav lights   — always on (red port, green starboard, white tail)
        strobes      — flashing white (wingtips + tail)
        beacons      — flashing red (top + bottom fuselage)
        landing      — bright white at wing root (on when gear down)
        taxi         — white on nose gear strut (on when on ground)
        logo         — white on horizontal stab (always on)

    Group NodePaths are named so main.py can find them and control
    brightness via ``setColorScale()``.
    """
    lights = NodePath('aircraft_lights')
    lights.reparentTo(plane)

    # Position tables — HD glb vs procedural fallback geometry
    if hd:
        nav_l   = (-17.0, -3.6,  0.76)
        nav_r   = ( 17.0, -3.6,  0.76)
        nav_t   = (  0.0, -18.8,  1.0)
        stb_l   = (-16.5, -3.4,  0.50)
        stb_r   = ( 16.5, -3.4,  0.50)
        stb_t   = (  0.0, -18.5,  1.0)
        bcn_top = (  0.0,  -1.0,  1.7)
        bcn_bot = (  0.0,  -1.0, -2.4)
        ldg_l   = ( -5.5,   5.5, -1.5)
        ldg_r   = (  5.5,   5.5, -1.5)
        logo_l  = ( -2.5, -16.0,  1.0)
        logo_r  = (  2.5, -16.0,  1.0)
    else:
        nav_l   = (-17.0, -3.5, -0.8)
        nav_r   = ( 17.0, -3.5, -0.8)
        nav_t   = (  0.0, -18.0,  3.5)
        stb_l   = (-16.5, -4.0, -0.8)
        stb_r   = ( 16.5, -4.0, -0.8)
        stb_t   = (  0.0, -18.5,  0.5)
        bcn_top = (  0.0,  -1.0,  2.2)
        bcn_bot = (  0.0,  -1.0, -2.0)
        ldg_l   = ( -3.0,   2.0, -1.5)
        ldg_r   = (  3.0,   2.0, -1.5)
        logo_l  = ( -3.0, -16.0,  1.8)
        logo_r  = (  3.0, -16.0,  1.8)

    # --- Navigation lights (always on) --------------------------------
    nav_group = NodePath('nav_lights')
    nav_group.reparentTo(lights)

    nl = _make_glow(color=(1.0, 0.05, 0.05, 1), size=0.4)  # port RED
    nl.setPos(*nav_l)
    nl.reparentTo(nav_group)

    nr = _make_glow(color=(0.05, 1.0, 0.05, 1), size=0.4)  # starboard GREEN
    nr.setPos(*nav_r)
    nr.reparentTo(nav_group)

    nt = _make_glow(color=(1.0, 1.0, 1.0, 1), size=0.3)    # tail WHITE
    nt.setPos(*nav_t)
    nt.reparentTo(nav_group)

    # --- Strobe lights (flashing white — Airbus double-flash) ---------
    strobes = NodePath('strobes')
    strobes.reparentTo(lights)
    for pos in (stb_l, stb_r, stb_t):
        s = _make_glow(color=(1.0, 1.0, 1.0, 1), size=0.9)
        s.setPos(*pos)
        s.reparentTo(strobes)

    # --- Anti-collision beacons (flashing red) -------------------------
    beacons = NodePath('beacons')
    beacons.reparentTo(lights)
    for pos in (bcn_top, bcn_bot):
        b = _make_glow(color=(1.0, 0.08, 0.02, 1), size=0.6)
        b.setPos(*pos)
        b.reparentTo(beacons)

    # --- Landing lights (bright white, wing root) ----------------------
    landing = NodePath('landing_lights')
    landing.reparentTo(lights)
    for pos in (ldg_l, ldg_r):
        ll = _make_glow(color=(1.0, 1.0, 0.95, 1), size=1.5)
        ll.setPos(*pos)
        ll.reparentTo(landing)

    # --- Runway turnoff lights (angled laterally from wing root) -------
    turnoff = NodePath('turnoff_lights')
    turnoff.reparentTo(lights)
    for sign in (-1, 1):
        tl = _make_glow(color=(1.0, 1.0, 0.95, 1), size=0.7)
        x = sign * (4.0 if hd else 4.0)
        y = 4.0 if hd else 1.5
        z = -1.0 if hd else -1.6
        tl.setPos(x, y, z)
        tl.reparentTo(turnoff)

    # --- Taxi / takeoff light -----------------------------------------
    taxi = NodePath('taxi_light')
    taxi.reparentTo(lights)
    tl = _make_glow(color=(1.0, 1.0, 0.95, 1), size=1.0)
    tl.setPos(0, 13.5, -3.5)                # nose gear area
    tl.reparentTo(taxi)

    # --- Logo lights (on horizontal stab, illuminate fin) --------------
    logo = NodePath('logo_lights')
    logo.reparentTo(lights)
    for pos in (logo_l, logo_r):
        lo = _make_glow(color=(1.0, 1.0, 0.90, 1), size=0.35)
        lo.setPos(*pos)
        lo.reparentTo(logo)


def build_a320():
    """
    Returns a NodePath rooted at the aircraft body centre.
    Uses a320_cockpit_2.glb when available (includes cockpit interior and
    static landing gear).  Procedural animated surfaces overlay the model.
    Falls back to fully procedural geometry if the glb is missing.

    Named sub-nodes for animation:
      .find('**/aileron_left'), .find('**/aileron_right')
      .find('**/elevator_left'), .find('**/elevator_right')
      .find('**/rudder'), .find('**/flap_left'), .find('**/flap_right')
      .find('**/spoiler_left_1'), .find('**/spoiler_right_1'), etc.
    """

    # ------------------------------------------------------------------
    # Path A: HD glb body + procedural animated parts
    # ------------------------------------------------------------------
    glb = _load_glb_body()
    if glb is not None:
        plane = NodePath('a320')
        glb.reparentTo(plane)

        _add_animated_surfaces(plane)
        _add_aircraft_lights(plane, hd=True)

        # The GLB model includes detailed static landing gear geometry,
        # so no procedural gear or gear bay fairings are added.

        return plane

    # ------------------------------------------------------------------
    # Path B: fully procedural fallback
    # ------------------------------------------------------------------
    plane = NodePath('a320')

    # --- Fuselage: rounded center section with tapered nose and tail
    fuselage = _make_cylinder_geom(2.0, 27.6, segments=20,
                                   color=FUSELAGE_COLOR, axis='y')
    fuselage.reparentTo(plane)

    nose = _make_cylinder_geom(1.9, 5.0, segments=20,
                               color=FUSELAGE_COLOR, axis='y',
                               radius_end=0.25)
    nose.setY(16.3)
    nose.reparentTo(plane)

    tailcone = _make_cylinder_geom(0.75, 5.0, segments=20,
                                   color=FUSELAGE_COLOR, axis='y',
                                   radius_end=1.9)
    tailcone.setY(-16.3)
    tailcone.reparentTo(plane)

    # --- Main wings
    def build_wing(side_sign):
        wing_root = NodePath('wing_root')
        wing = _make_box_geom(15.0, 4.0, 0.4, color=WING_COLOR)
        wing.setX(side_sign * (2.0 + 7.5))
        wing.setY(-1.0)
        wing.setZ(-1.0)
        wing.setH(side_sign * -25)
        wing.reparentTo(wing_root)

        side = 'right' if side_sign > 0 else 'left'

        aileron = _make_box_geom(3.0, 0.8, 0.15, color=CONTROL_COLOR)
        aileron.setName(f'aileron_{side}')
        aileron.setX(side_sign * (2.0 + 12.5))
        aileron.setY(-1.0 - 5.0 * math.sin(math.radians(25)))
        aileron.setZ(-0.9)
        aileron.setH(side_sign * -25)
        aileron.reparentTo(wing_root)

        flap = _make_box_geom(6.0, 1.2, 0.15, color=CONTROL_COLOR)
        flap.setName(f'flap_{side}')
        flap.setX(side_sign * (2.0 + 5.5))
        flap.setY(-3.2)
        flap.setZ(-1.0)
        flap.setH(side_sign * -25)
        flap.reparentTo(wing_root)

        for i, x_off in enumerate((7.0, 11.0)):
            sp = _make_box_geom(3.0, 1.5, 0.1, color=CONTROL_COLOR)
            sp.setName(f'spoiler_{side}_{i+1}')
            sp.setX(side_sign * (2.0 + x_off))
            sp.setY(-2.0)
            sp.setZ(-0.75)
            sp.setH(side_sign * -25)
            sp.reparentTo(wing_root)

        engine = _make_cylinder_geom(1.3, 4.5, segments=16,
                                     color=ENGINE_COLOR, axis='y')
        engine.setX(side_sign * 6.0)
        engine.setY(1.0)
        engine.setZ(-2.5)
        engine.reparentTo(wing_root)

        intake = _make_cylinder_geom(1.12, 0.12, segments=20,
                                     color=(0.06, 0.07, 0.09, 1), axis='y')
        intake.setX(side_sign * 6.0)
        intake.setY(3.28)
        intake.setZ(-2.5)
        intake.reparentTo(wing_root)
        exhaust = _make_cylinder_geom(0.78, 0.12, segments=16,
                                      color=(0.12, 0.12, 0.14, 1), axis='y')
        exhaust.setX(side_sign * 6.0)
        exhaust.setY(-1.28)
        exhaust.setZ(-2.5)
        exhaust.reparentTo(wing_root)

        winglet = _make_box_geom(0.18, 1.8, 2.2, color=WING_COLOR)
        winglet.setX(side_sign * 17.35)
        winglet.setY(-1.0 - 7.5 * math.sin(math.radians(25)))
        winglet.setZ(0.1)
        winglet.setH(side_sign * -25)
        winglet.reparentTo(wing_root)

        pylon = _make_box_geom(0.4, 2.0, 1.5, color=WING_COLOR)
        pylon.setX(side_sign * 6.0)
        pylon.setY(0.5)
        pylon.setZ(-1.7)
        pylon.reparentTo(wing_root)

        return wing_root

    build_wing(+1).reparentTo(plane)
    build_wing(-1).reparentTo(plane)

    vstab = _make_box_geom(0.5, 4.0, 5.5, color=TAIL_COLOR)
    vstab.setY(-15.0)
    vstab.setZ(3.5)
    vstab.reparentTo(plane)

    rudder = _make_box_geom(0.4, 1.2, 4.5, color=CONTROL_COLOR)
    rudder.setName('rudder')
    rudder.setY(-17.0)
    rudder.setZ(3.5)
    rudder.reparentTo(plane)

    hstab_left = _make_box_geom(6.0, 2.5, 0.3, color=WING_COLOR)
    hstab_left.setX(-3.5)
    hstab_left.setY(-16.0)
    hstab_left.setZ(1.5)
    hstab_left.setH(-15)
    hstab_left.reparentTo(plane)

    hstab_right = _make_box_geom(6.0, 2.5, 0.3, color=WING_COLOR)
    hstab_right.setX(3.5)
    hstab_right.setY(-16.0)
    hstab_right.setZ(1.5)
    hstab_right.setH(15)
    hstab_right.reparentTo(plane)

    for side_sign in (-1, 1):
        elevator = _make_box_geom(5.5, 0.8, 0.2, color=CONTROL_COLOR)
        elevator.setName(f'elevator_{"right" if side_sign > 0 else "left"}')
        elevator.setX(side_sign * 3.5)
        elevator.setY(-17.5)
        elevator.setZ(1.5)
        elevator.setH(side_sign * 15)
        elevator.reparentTo(plane)

    _build_gear('gear_nose',  0.0,  14.0, -2.0).reparentTo(plane)
    _build_gear('gear_left', -3.5,  -1.0, -2.0, main=True).reparentTo(plane)
    _build_gear('gear_right', 3.5,  -1.0, -2.0, main=True).reparentTo(plane)

    window_color = (0.04, 0.10, 0.18, 1)
    for side_sign in (-1, 1):
        for y, z, length in ((14.7, 1.05, 1.0), (15.8, 1.2, 0.7)):
            window = _make_box_geom(0.08, length, 0.55, color=window_color)
            window.setX(side_sign * 1.78)
            window.setY(y)
            window.setZ(z)
            window.setH(side_sign * -12)
            window.reparentTo(plane)

    _add_aircraft_lights(plane, hd=False)

    return plane