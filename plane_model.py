"""
plane_model.py
--------------
Procedural A320-ish model built from primitive geometry. Not pretty, but
proportional and clearly an airliner. Replace with a proper Blender model
later — just swap build_a320() with loader.loadModel('a320.gltf') and keep
the same NodePath structure.

Real A320-200 dimensions used:
  length      37.6 m
  wingspan    34.1 m
  height      11.8 m
  wing sweep  25 deg
  engines     2 x CFM56 under wings
"""

from panda3d.core import (
    Geom, GeomNode, GeomVertexData, GeomVertexFormat, GeomVertexWriter,
    GeomTriangles, NodePath, Vec3, Vec4, Point3, LVector3,
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


# ----------------------------------------------------------------------
# Build the A320
# ----------------------------------------------------------------------
FUSELAGE_COLOR = (0.94, 0.94, 0.95, 1)   # off-white
WING_COLOR     = (0.90, 0.90, 0.92, 1)
TAIL_COLOR     = (0.15, 0.30, 0.60, 1)   # blue tail (generic livery)
ENGINE_COLOR   = (0.85, 0.85, 0.88, 1)
GEAR_COLOR     = (0.25, 0.25, 0.27, 1)
CONTROL_COLOR  = (0.80, 0.80, 0.82, 1)


def build_a320():
    """
    Returns a NodePath rooted at the aircraft body center.
    In Panda3D convention: +Y = forward (nose), +X = right wing, +Z = up.
    Named sub-nodes for animation:
      .find('**/gear_nose'), .find('**/gear_left'), .find('**/gear_right')
      .find('**/aileron_left'), .find('**/aileron_right')
    .find('**/elevator_left'), .find('**/elevator_right'),
    .find('**/rudder'), .find('**/flap_left'), .find('**/flap_right')
    """
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

    # --- Main wings: use two swept boxes (one per side).
    # Panda3D lacks skewed primitives, so we approximate sweep by rotating
    # a thin box slightly around Z and offsetting.
    def build_wing(side_sign):
        """side_sign = +1 for right wing, -1 for left."""
        wing_root = NodePath('wing_root')
        # Wing: 15m long (half-span minus fuselage), 4m chord, 0.4m thick
        wing = _make_box_geom(15.0, 4.0, 0.4, color=WING_COLOR)
        # Position so root is at fuselage side, extending outward
        wing.setX(side_sign * (2.0 + 7.5))     # 2m fuselage + 7.5m to wing mid
        wing.setY(-1.0)                         # slightly aft of CG
        wing.setZ(-1.0)                         # under-fuselage low wing
        # Sweep: rotate around Z so leading edge sweeps back
        wing.setH(side_sign * -25)
        wing.reparentTo(wing_root)

        # Aileron: small box near wingtip, on trailing edge
        aileron = _make_box_geom(3.0, 0.8, 0.15, color=CONTROL_COLOR)
        aileron.setName(f'aileron_{"right" if side_sign > 0 else "left"}')
        aileron.setX(side_sign * (2.0 + 12.5))
        aileron.setY(-1.0 - 5.0 * math.sin(math.radians(25)))
        aileron.setZ(-0.9)
        aileron.setH(side_sign * -25)
        aileron.reparentTo(wing_root)

        # Flap: inboard trailing edge
        flap = _make_box_geom(6.0, 1.2, 0.15, color=CONTROL_COLOR)
        flap.setName(f'flap_{"right" if side_sign > 0 else "left"}')
        flap.setX(side_sign * (2.0 + 5.5))
        flap.setY(-3.2)
        flap.setZ(-1.0)
        flap.setH(side_sign * -25)
        flap.reparentTo(wing_root)

        # Spoiler panels on TOP of the wing (deploy upward for speedbrake).
        # Real A320 has 5 panels per wing — we do 2 per side for the model.
        side_name = "right" if side_sign > 0 else "left"
        for i, x_off in enumerate((7.0, 11.0)):
            sp = _make_box_geom(3.0, 1.5, 0.1, color=CONTROL_COLOR)
            sp.setName(f'spoiler_{side_name}_{i+1}')
            sp.setX(side_sign * (2.0 + x_off))
            sp.setY(-2.0)
            sp.setZ(-0.75)      # top surface of the wing
            sp.setH(side_sign * -25)
            sp.reparentTo(wing_root)

        # Engine nacelle: cylinder under wing, forward of leading edge
        engine = _make_cylinder_geom(1.3, 4.5, segments=16,
                                     color=ENGINE_COLOR, axis='y')
        engine.setX(side_sign * 6.0)
        engine.setY(1.0)
        engine.setZ(-2.5)
        engine.reparentTo(wing_root)

        # Dark intake and exhaust faces make the CFM56 nacelles readable.
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

        # Blended winglet, a distinctive A320 family silhouette.
        winglet = _make_box_geom(0.18, 1.8, 2.2, color=WING_COLOR)
        winglet.setX(side_sign * 17.35)
        winglet.setY(-1.0 - 7.5 * math.sin(math.radians(25)))
        winglet.setZ(0.1)
        winglet.setH(side_sign * -25)
        winglet.reparentTo(wing_root)

        # Pylon connecting engine to wing
        pylon = _make_box_geom(0.4, 2.0, 1.5, color=WING_COLOR)
        pylon.setX(side_sign * 6.0)
        pylon.setY(0.5)
        pylon.setZ(-1.7)
        pylon.reparentTo(wing_root)

        return wing_root

    build_wing(+1).reparentTo(plane)
    build_wing(-1).reparentTo(plane)

    # --- Vertical stabilizer (tail fin)
    vstab = _make_box_geom(0.5, 4.0, 5.5, color=TAIL_COLOR)
    vstab.setY(-15.0)
    vstab.setZ(3.5)
    vstab.reparentTo(plane)

    # Rudder
    rudder = _make_box_geom(0.4, 1.2, 4.5, color=CONTROL_COLOR)
    rudder.setName('rudder')
    rudder.setY(-17.0)
    rudder.setZ(3.5)
    rudder.reparentTo(plane)

    # --- Horizontal stabilizers
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

    # Separate left and right elevators, each aligned with its stabilizer.
    for side_sign in (-1, 1):
        elevator = _make_box_geom(5.5, 0.8, 0.2, color=CONTROL_COLOR)
        elevator.setName(f'elevator_{"right" if side_sign > 0 else "left"}')
        elevator.setX(side_sign * 3.5)
        elevator.setY(-17.5)
        elevator.setZ(1.5)
        elevator.setH(side_sign * 15)
        elevator.reparentTo(plane)

    # --- Landing gear
    def build_gear(name, x, y, z, leg_len=2.5, main=False):
        gear = NodePath(name)
        leg = _make_cylinder_geom(0.15, leg_len, segments=8,
                                  color=GEAR_COLOR, axis='z')
        leg.setZ(-leg_len / 2)
        leg.reparentTo(gear)

        # A320 nose gear has two wheels; each main bogie has four wheels.
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

    build_gear('gear_nose',  0.0,  14.0, -2.0).reparentTo(plane)
    build_gear('gear_left', -3.5,  -1.0, -2.0, main=True).reparentTo(plane)
    build_gear('gear_right', 3.5,  -1.0, -2.0, main=True).reparentTo(plane)

    # Cockpit windshield panes, placed on both sides of the tapered nose.
    window_color = (0.04, 0.10, 0.18, 1)
    for side_sign in (-1, 1):
        for y, z, length in ((14.7, 1.05, 1.0), (15.8, 1.2, 0.7)):
            window = _make_box_geom(0.08, length, 0.55, color=window_color)
            window.setX(side_sign * 1.78)
            window.setY(y)
            window.setZ(z)
            window.setH(side_sign * -12)
            window.reparentTo(plane)

    return plane