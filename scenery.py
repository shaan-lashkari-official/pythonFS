"""
scenery.py  (v2 — richer scenery)
--------------------------------
Same public API as before — `main.py` doesn't need to change:
    build_ground, build_runway, build_runway_lights, build_city,
    add_lighting, update_papi

What's new in build_city():
  - thousands of procedural trees in forests + scattered
  - road grid running through the city clusters
  - a river (Thames-ish) running roughly north-south east of the airport
  - terminal buildings north of the runway
  - hangars and fuel tanks near the airport
  - taxiway parallel to the runway
  - grass patches with color variation
  - more varied building clusters (downtown, mid-rise, residential)

Uses flattenStrong() at the end of large groupings so thousands of
small objects don't kill the frame rate.
"""

import math
import random
from night_lighting import build_night_lighting_group
from panda3d.core import (
    Geom, GeomNode, GeomVertexData, GeomVertexFormat, GeomVertexWriter,
    GeomTriangles, NodePath, Vec3, Vec4, Point3, CardMaker,
    TransparencyAttrib, ColorBlendAttrib,
    AmbientLight, DirectionalLight,
)


# ----------------------------------------------------------------------
# Primitive builders (kept local to avoid circular import)
# ----------------------------------------------------------------------
def _flat_quad(sx, sy, color=(1, 1, 1, 1)):
    fmt = GeomVertexFormat.getV3n3c4()
    vdata = GeomVertexData('quad', fmt, Geom.UHStatic)
    vdata.setNumRows(4)
    vw = GeomVertexWriter(vdata, 'vertex')
    nw = GeomVertexWriter(vdata, 'normal')
    cw = GeomVertexWriter(vdata, 'color')
    hx, hy = sx / 2, sy / 2
    for x, y in [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]:
        vw.addData3(x, y, 0); nw.addData3(0, 0, 1); cw.addData4(*color)
    tris = GeomTriangles(Geom.UHStatic)
    tris.addVertices(0, 1, 2); tris.addVertices(0, 2, 3)
    geom = Geom(vdata); geom.addPrimitive(tris)
    node = GeomNode('quad'); node.addGeom(geom)
    return NodePath(node)


def _box(sx, sy, sz, color):
    from plane_model import _make_box_geom
    return _make_box_geom(sx, sy, sz, color)


def _cyl(radius, length, color, segments=10, axis='z'):
    from plane_model import _make_cylinder_geom
    return _make_cylinder_geom(radius, length, segments=segments,
                               color=color, axis=axis)


def _airport_clear(x, y, margin=0.0):
    """Return False for the two runway corridors and their safety margins."""
    return not (
        -4300 - margin < x < 500 + margin and
        -300 - margin < y < 2100 + margin
    )


def _terrain_mesh(size, divisions=48, seed=11):
    """Low-relief terrain with a level airport basin around the runway."""
    rng = random.Random(seed)
    fmt = GeomVertexFormat.getV3n3c4()
    vdata = GeomVertexData('terrain', fmt, Geom.UHStatic)
    rows = divisions + 1
    vdata.setNumRows(rows * rows)
    vw = GeomVertexWriter(vdata, 'vertex')
    nw = GeomVertexWriter(vdata, 'normal')
    cw = GeomVertexWriter(vdata, 'color')
    step = size / divisions
    for row in range(rows):
        y = -size / 2 + row * step
        for col in range(rows):
            x = -size / 2 + col * step
            basin = max(0.0, 1.0 - math.hypot(x / 4200, y / 1500))
            waves = (math.sin(x / 850) + math.cos(y / 1100)) * 1.6
            broad = math.sin((x + y) / 2600) * 2.0
            # Terrain is the base layer; keep every airport/road/water overlay
            # above it to avoid z-fighting and accidental occlusion.
            z = -0.35 + (waves + broad) * (1.0 - basin) * 0.08
            z += rng.uniform(-0.02, 0.02)
            # Keep the complete runway, taxiway, and approach corridor level.
            if -4300 < x < 500 and -300 < y < 2100:
                z = 0.0
            z = max(-0.65, min(-0.12, z))
            green = 0.25 + 0.06 * math.sin(x / 500) + 0.03 * math.cos(y / 700)
            cw.addData4(0.12, max(0.20, green), 0.10, 1)
            vw.addData3(x, y, z)
            nw.addData3(0, 0, 1)
    tris = GeomTriangles(Geom.UHStatic)
    for row in range(divisions):
        for col in range(divisions):
            a = row * rows + col
            b = a + 1
            c = a + rows
            d = c + 1
            tris.addVertices(a, b, c)
            tris.addVertices(b, d, c)
    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode('terrain')
    node.addGeom(geom)
    return NodePath(node)


# ----------------------------------------------------------------------
# Ground
# ----------------------------------------------------------------------
def build_ground(size=30000.0):
    """Vibrant low-relief countryside surrounding a level airport basin."""
    ground = _terrain_mesh(size)
    ground.setZ(-0.08)
    ground.clearLight()          # explicitly ensure lighting works
    ground.setTwoSided(True)     # let light hit either side
    return ground


def _grass_patches(parent, seed=1):
    """Scatter subtle grass color variation patches so the ground isn't flat."""
    rng = random.Random(seed)
    for _ in range(220):
        x = rng.uniform(-12000, 12000)
        y = rng.uniform(-12000, 12000)
        # Skip anywhere near the runway (visual noise on the strip)
        if not _airport_clear(x, y, margin=80):
            continue
        sx = rng.uniform(80, 400)
        sy = rng.uniform(80, 400)
        # Varying green: slightly darker/lighter/yellower/blueier
        r = 0.15 + rng.uniform(-0.04, 0.05)
        g = 0.32 + rng.uniform(-0.05, 0.07)
        b = 0.13 + rng.uniform(-0.03, 0.04)
        patch = _flat_quad(sx, sy, color=(r, g, b, 1))
        patch.setPos(x, y, -0.03)     # just above the base ground
        patch.reparentTo(parent)


def build_fields(seed=13):
    """Large rectangular fields and hedgerows for a readable aerial map."""
    rng = random.Random(seed)
    fields = NodePath('fields')
    field_colors = [
        (0.24, 0.43, 0.16, 1), (0.31, 0.50, 0.18, 1),
        (0.42, 0.50, 0.20, 1), (0.20, 0.38, 0.16, 1),
    ]
    for x in range(-12000, 12001, 1600):
        for y in range(-10000, 10001, 1500):
            if not _airport_clear(x, y, margin=80):
                continue
            field = _flat_quad(rng.uniform(850, 1020),
                               rng.uniform(650, 900),
                               color=rng.choice(field_colors))
            field.setPos(x + rng.uniform(-90, 90),
                         y + rng.uniform(-80, 80), 0.002)
            field.reparentTo(fields)
    fields.flattenStrong()
    return fields


# ----------------------------------------------------------------------
# Runway + taxiway
# ----------------------------------------------------------------------
def build_runway(length=3902.0, width=45.0):
    """Runway 27L, threshold at origin, extending along -X."""
    rwy = NodePath('runway')

    # Asphalt
    asphalt = _flat_quad(length, width, color=(0.12, 0.12, 0.13, 1))
    asphalt.setX(-length / 2)
    asphalt.reparentTo(rwy)

    # Threshold "piano keys"
    for i in range(8):
        stripe = _flat_quad(6.0, 3.0, color=(1, 1, 1, 1))
        stripe.setPos(-6.0, -width / 2 + 4 + i * 5, 0.01)
        stripe.reparentTo(rwy)

    # Centerline dashes
    dash_len, gap = 30.0, 20.0
    x = -20.0
    while x > -length + 60:
        dash = _flat_quad(dash_len, 0.9, color=(1, 1, 1, 1))
        dash.setPos(x - dash_len / 2, 0, 0.01)
        dash.reparentTo(rwy)
        x -= (dash_len + gap)

    # Aiming point rectangles (both sides of centerline, ~400m in)
    for side in (-1, 1):
        aim = _flat_quad(40.0, 6.0, color=(1, 1, 1, 1))
        aim.setPos(-400, side * 8, 0.01)
        aim.reparentTo(rwy)

    # Touchdown zone markings (three groups of parallel bars)
    for group_x in (-150, -300, -450):
        for side in (-1, 1):
            for i in range(3):
                bar = _flat_quad(20.0, 1.5, color=(1, 1, 1, 1))
                bar.setPos(group_x, side * (5 + i * 2.5), 0.01)
                bar.reparentTo(rwy)

    # Runway designator placeholder
    designator = _flat_quad(15.0, 8.0, color=(0.9, 0.9, 0.9, 1))
    designator.setPos(-80, 0, 0.01)
    designator.reparentTo(rwy)

    # --- Parallel taxiway 150m north of the runway
    taxiway = _flat_quad(length + 400, 32, color=(0.105, 0.105, 0.115, 1))
    taxiway.setPos(-length / 2, 100, 0.005)
    taxiway.reparentTo(rwy)

    # Taxiway centerline (yellow)
    x = -50.0
    while x > -length - 200:
        dash = _flat_quad(15.0, 0.6, color=(0.95, 0.85, 0.15, 1))
        dash.setPos(x, 100, 0.015)
        dash.reparentTo(rwy)
        x -= 25.0

    # Connector taxiways: 5 short strips linking runway to taxiway
    for x_pos in (-200, -900, -1600, -2400, -3200):
        connector = _flat_quad(32, 100, color=(0.105, 0.105, 0.115, 1))
        connector.setPos(x_pos, 50, 0.005)
        connector.reparentTo(rwy)

    # Taxiway edge lines and a broad terminal apron make the airport read as active.
    for side in (-1, 1):
        edge = _flat_quad(length + 400, 0.35, color=(0.9, 0.9, 0.82, 1))
        edge.setPos(-length / 2, 100 + side * 15.2, 0.02)
        edge.reparentTo(rwy)
    apron = _flat_quad(1500, 430, color=(0.18, 0.19, 0.20, 1))
    apron.setPos(-1500, 430, 0.01)
    apron.reparentTo(rwy)
    for x in range(-2050, -900, 90):
        stand = _flat_quad(55, 3, color=(0.82, 0.82, 0.76, 1))
        stand.setPos(x, 350, 0.025)
        stand.reparentTo(rwy)

    return rwy


def build_heathrow_parallel_runway(length=3650.0, width=45.0,
                                   center_y=1800.0):
    """The northern 27R/09L runway and its characteristic parallel taxiway."""
    airport = NodePath('heathrow_northern_runway')
    runway = _flat_quad(length, width, color=(0.11, 0.115, 0.125, 1))
    runway.setPos(-length / 2, center_y, 0.012)
    runway.reparentTo(airport)

    # Threshold and centerline markings, aligned with the active runway.
    for i in range(8):
        stripe = _flat_quad(6, 3, color=(1, 1, 1, 1))
        stripe.setPos(-6, center_y - width / 2 + 4 + i * 5, 0.024)
        stripe.reparentTo(airport)
    for x in range(-35, int(-length + 60), -50):
        dash = _flat_quad(30, 0.9, color=(1, 1, 1, 1))
        dash.setPos(x - 15, center_y, 0.024)
        dash.reparentTo(airport)
    for side in (-1, 1):
        edge = _flat_quad(length, 0.45, color=(0.9, 0.9, 0.84, 1))
        edge.setPos(-length / 2, center_y + side * (width / 2 - 2), 0.024)
        edge.reparentTo(airport)

    taxiway = _flat_quad(length + 350, 30, color=(0.105, 0.11, 0.12, 1))
    taxiway.setPos(-length / 2, center_y - 120, 0.018)
    taxiway.reparentTo(airport)
    for x in range(-50, int(-length - 150), -28):
        dash = _flat_quad(15, 0.6, color=(0.95, 0.82, 0.15, 1))
        dash.setPos(x, center_y - 120, 0.033)
        dash.reparentTo(airport)

    # High-speed connectors between runway and taxiway.
    for x in (-300, -1000, -1750, -2500, -3250):
        connector = _flat_quad(28, 120, color=(0.105, 0.11, 0.12, 1))
        connector.setPos(x, center_y - 60, 0.016)
        connector.reparentTo(airport)
    return airport


# ----------------------------------------------------------------------
# Runway lights (unchanged from v1)
# ----------------------------------------------------------------------
def _light_point(color=(1, 1, 1, 1), size=1.5):
    """
    Runway light: bright billboard card with radial glow.
    Uses CardMaker-style geometry so the light always faces the camera
    (visible from any angle, including straight above at cruise altitude).
    Three concentric additive layers create a photo-realistic bulb glow.

    Absolute radii capped so bigger `size` inputs (like PAPI at 1.6)
    don't produce room-sized glows.
    """
    import math
    from panda3d.core import (
        Geom, GeomNode, GeomVertexData, GeomVertexFormat, GeomVertexWriter,
        GeomTriangles, NodePath, TransparencyAttrib, ColorBlendAttrib,
    )

    r, g, b, _ = color

    # Absolute (capped) radii — decoupled from the input `size` so all
    # runway light types get sensibly-scaled glows.
    core_r  = min(size * 0.30, 0.5)   # sharp bright pinpoint
    halo_r  = min(size * 0.75, 1.1)   # bright halo
    bloom_r = min(size * 1.60, 2.2)   # dim outer glow

    layers = [
        (core_r,  (r, g, b, 1.0)),
        (halo_r,  (r, g, b, 0.65)),
        (bloom_r, (r, g, b, 0.25)),
    ]
    edge_color = (r, g, b, 0.0)
    segments = 12

    fmt = GeomVertexFormat.getV3n3c4()
    vdata = GeomVertexData('rwy_light', fmt, Geom.UHStatic)
    vw = GeomVertexWriter(vdata, 'vertex')
    nw = GeomVertexWriter(vdata, 'normal')
    cw = GeomVertexWriter(vdata, 'color')
    tris = GeomTriangles(Geom.UHStatic)

    idx = 0
    for radius, center_color in layers:
        vw.addData3(0, 0, 0)
        nw.addData3(0, 1, 0)
        cw.addData4(*center_color)
        for i in range(segments):
            a = 2 * math.pi * i / segments
            vw.addData3(math.cos(a) * radius, 0, math.sin(a) * radius)
            nw.addData3(0, 1, 0)
            cw.addData4(*edge_color)
        for i in range(segments):
            ni = (i + 1) % segments
            tris.addVertices(idx, idx + 1 + i, idx + 1 + ni)
        idx += 1 + segments

    geom = Geom(vdata); geom.addPrimitive(tris)
    node = GeomNode('rwy_light'); node.addGeom(geom)
    np = NodePath(node)
    np.setTransparency(TransparencyAttrib.MAlpha)
    np.setAttrib(ColorBlendAttrib.make(ColorBlendAttrib.MAdd,
                                       ColorBlendAttrib.OIncomingAlpha,
                                       ColorBlendAttrib.OOne))
    np.setLightOff()
    np.setDepthWrite(False)
    np.setBin('transparent', 22)
    np.setBillboardPointEye()
    return np
def build_runway_lights(length=3902.0, width=45.0, center_y=0.0,
                        name='runway_lights', prefix=''):
    """Build threshold, edge, PAPI, and approach lights for one runway."""
    lights = NodePath(name)

    # Threshold — green
    for i in range(6):
        y = center_y - width / 2 + (i + 0.5) * (width / 6)
        l = _light_point((0.0, 1.0, 0.2, 1), size=1.2)
        l.setPos(0.5, y, 0.5); l.reparentTo(lights)

    # Edge lights
    n_edge = int(length / 60)
    for i in range(n_edge + 1):
        x = -i * (length / n_edge)
        color = (1, 1, 0.4, 1) if x < -length + 600 else (1, 1, 1, 1)
        for side in (-1, 1):
            l = _light_point(color, size=1.0)
            l.setPos(x, center_y + side * (width / 2 + 1), 0.5); l.reparentTo(lights)

    # Centerline
    n_cl = int(length / 15)
    for i in range(1, n_cl):
        x = -i * 15.0
        remaining = length + x
        if remaining < 300:
            color = (1, 0, 0, 1)
        elif remaining < 900:
            color = (1, 0, 0, 1) if i % 2 else (1, 1, 1, 1)
        else:
            color = (1, 1, 1, 1)
        l = _light_point(color, size=0.7)
        l.setPos(x, center_y, 0.4); l.reparentTo(lights)

    # End lights — red
    for i in range(6):
        y = center_y - width / 2 + (i + 0.5) * (width / 6)
        l = _light_point((1, 0, 0, 1), size=1.2)
        l.setPos(-length, y, 0.5); l.reparentTo(lights)

    # PAPI
    papi_parent = NodePath(f'{prefix}papi')
    for i in range(4):
        l = _light_point((1, 1, 1, 1), size=1.6)
        l.setName(f'{prefix}papi_{i}')
        l.setPos(-300, center_y - width / 2 - 15 - i * 9, 1.5)
        l.reparentTo(papi_parent)
    papi_parent.reparentTo(lights)

    build_alsf2_approach(threshold_x=0, threshold_y=0).reparentTo(lights)

    return lights



# =====================================================================
# ALSF-II APPROACH LIGHTING SYSTEM
# =====================================================================
APPROACH_LIGHT_SPACING = 30.0
APPROACH_N_ROWS = 30
BAR_LIGHT_SPACING = 1.5
BAR_LIGHTS_PER_ROW = 5
RABBIT_LIGHT_SPACING = 30.0
RABBIT_N_LIGHTS = 20
CROSSBAR_DISTANCE_M = 300.0
CROSSBAR_WIDTH_M = 30.0
CROSSBAR_LIGHTS = 20


def build_alsf2_approach(threshold_x=0, threshold_y=0):
    """
    Full ALSF-II approach lighting: centerline bars, sequenced flashers
    (rabbit — animated by update_rabbit_lights), 300m crossbar, threshold
    wing bars, green threshold lights.
    """
    root = NodePath('alsf2_approach_lighting')

    # Centerline bars (5-light bars every 30m)
    centerline = NodePath('alsf_centerline')
    for row in range(1, APPROACH_N_ROWS + 1):
        x = threshold_x + row * APPROACH_LIGHT_SPACING
        for lat in range(BAR_LIGHTS_PER_ROW):
            offset = (lat - (BAR_LIGHTS_PER_ROW - 1) / 2) * BAR_LIGHT_SPACING
            l = _light_point((1, 1, 1, 1), size=0.9)
            l.setPos(x, threshold_y + offset, 0.5)
            l.reparentTo(centerline)
    centerline.reparentTo(root)

    # Sequenced flashers (rabbit) — named individually for animation
    rabbit = NodePath('alsf_rabbit')
    for i in range(RABBIT_N_LIGHTS):
        x = threshold_x + (i + 1) * RABBIT_LIGHT_SPACING
        l = _light_point((1, 1, 1, 1), size=1.4)
        l.setName(f'rabbit_{i}')
        l.setPos(x, threshold_y, 0.7)
        l.setColorScale(0.4, 0.4, 0.4, 1)
        l.reparentTo(rabbit)
    rabbit.reparentTo(root)

    # 300m crossbar
    crossbar = NodePath('alsf_crossbar')
    for i in range(CROSSBAR_LIGHTS):
        offset = (i - (CROSSBAR_LIGHTS - 1) / 2) * (CROSSBAR_WIDTH_M / CROSSBAR_LIGHTS)
        l = _light_point((1, 1, 1, 1), size=1.0)
        l.setPos(threshold_x + CROSSBAR_DISTANCE_M, threshold_y + offset, 0.5)
        l.reparentTo(crossbar)
    crossbar.reparentTo(root)

    # Threshold wing bars (red bars flanking runway start)
    wing_bars = NodePath('alsf_wing_bars')
    runway_half_width = 22.5
    for side in (-1, 1):
        for j in range(8):
            l = _light_point((1.0, 0.15, 0.05, 1), size=1.1)
            l.setPos(threshold_x,
                     threshold_y + side * (runway_half_width + 3 + j * 1.5),
                     0.5)
            l.reparentTo(wing_bars)
    wing_bars.reparentTo(root)

    # Green threshold lights across runway start
    threshold = NodePath('alsf_threshold')
    for i in range(15):
        offset = (i - 7) * (45.0 / 15)
        l = _light_point((0.15, 1.0, 0.25, 1), size=1.1)
        l.setPos(threshold_x - 1, threshold_y + offset, 0.5)
        l.reparentTo(threshold)
    threshold.reparentTo(root)

    return root


def update_rabbit_lights(cached_nodes, current_time):
    """
    Sequenced flashing 'rabbit'. Call every frame from main.py::_update.
    One light bright, sweeping from far end toward threshold at 2 Hz.
    cached_nodes: pre-built list of rabbit NodePaths (avoids find() each frame).
    """
    cycle_duration = 0.5
    phase = (current_time % cycle_duration) / cycle_duration
    active_idx = int((1.0 - phase) * RABBIT_N_LIGHTS)
    for i, node in enumerate(cached_nodes):
        if node.isEmpty():
            continue
        if i == active_idx:
            node.setColorScale(4.0, 4.0, 4.0, 1)
        elif abs(i - active_idx) == 1:
            node.setColorScale(1.2, 1.2, 1.2, 1)
        else:
            node.setColorScale(0.35, 0.35, 0.35, 1)

def update_papi(cached_nodes, aircraft_east, aircraft_up, center_y=0.0):
    """4-bulb PAPI: red/white based on angle to touchdown zone.
    cached_nodes: pre-built list of 4 PAPI NodePaths (avoids find() each frame).
    """
    # PAPI is meaningful only when the aircraft is on the approach side.
    dx = aircraft_east - (-300.0)
    if dx <= 0:
        return
    angle_deg = math.degrees(math.atan2(max(aircraft_up, 0.1), dx))
    transitions = [2.5, 2.83, 3.17, 3.5]
    for node, t in zip(cached_nodes, transitions):
        if node.isEmpty():
            continue
        node.setColor(1, 1, 1, 1) if angle_deg > t else node.setColor(1, 0.15, 0.05, 1)


# ----------------------------------------------------------------------
# Trees
# ----------------------------------------------------------------------
def _make_tree(rng):
    """Lollipop tree: brown trunk cylinder + green canopy cylinder."""
    tree = NodePath('tree')
    trunk_h = rng.uniform(3.5, 7.0)
    trunk_r = rng.uniform(0.2, 0.35)
    trunk_col = (
        0.35 + rng.uniform(-0.05, 0.05),
        0.22 + rng.uniform(-0.03, 0.03),
        0.12 + rng.uniform(-0.02, 0.02), 1
    )
    trunk = _cyl(trunk_r, trunk_h, trunk_col, segments=6, axis='z')
    trunk.setZ(trunk_h / 2)
    trunk.reparentTo(tree)

    canopy_r = rng.uniform(1.6, 3.2)
    canopy_h = rng.uniform(3.0, 5.5)
    green_variants = [
        (0.18, 0.42, 0.15, 1),
        (0.22, 0.48, 0.18, 1),
        (0.15, 0.38, 0.13, 1),
        (0.28, 0.45, 0.20, 1),
        (0.20, 0.40, 0.22, 1),
    ]
    canopy_col = rng.choice(green_variants)
    canopy = _cyl(canopy_r, canopy_h, canopy_col, segments=8, axis='z')
    canopy.setZ(trunk_h + canopy_h / 2 - 0.5)
    canopy.reparentTo(tree)

    return tree


def build_trees(seed=7):
    """
    Scatter trees:
      - dense forest patches (a few clusters, hundreds of trees each)
      - scattered singles around residential areas
      - line of trees along the river bank
    flattenStrong at the end so this doesn't tank framerate.
    """
    rng = random.Random(seed)
    trees = NodePath('trees')

    # Forest clusters
    forests = [
        # (cx, cy, radius, count)
        (-6000,  5000, 1200, 350),
        ( 7500, -4500, 1000, 250),
        (-3000, -6500, 1500, 400),
        ( 9000,  6000,  900, 200),
        (-8000, -2000,  800, 180),
    ]
    for cx, cy, r, n in forests:
        for _ in range(n):
            rr = rng.random() ** 0.5 * r
            th = rng.random() * 2 * math.pi
            x = cx + rr * math.cos(th)
            y = cy + rr * math.sin(th)
            # keep trees off the runway strip
            if not _airport_clear(x, y, margin=120):
                continue
            t = _make_tree(rng)
            t.setPos(x, y, 0)
            t.setH(rng.uniform(0, 360))
            t.reparentTo(trees)

    # Scattered singles — random across the map
    for _ in range(600):
        x = rng.uniform(-10000, 10000)
        y = rng.uniform(-10000, 10000)
        if not _airport_clear(x, y, margin=180):
            continue     # keep clear of runway/taxiway area
        if abs(x) > 12000 or abs(y) > 12000:
            continue
        t = _make_tree(rng)
        t.setPos(x, y, 0)
        t.setH(rng.uniform(0, 360))
        t.reparentTo(trees)

    # Tree line along the river (river runs at X ≈ 6000, north-south)
    for y in range(-8000, 8000, 25):
        for dx in (-30, 30):
            if rng.random() < 0.6:
                t = _make_tree(rng)
                t.setPos(6000 + dx + rng.uniform(-8, 8),
                         y + rng.uniform(-6, 6), 0)
                t.reparentTo(trees)

    trees.flattenStrong()   # crucial for performance
    return trees


# ----------------------------------------------------------------------
# Roads
# ----------------------------------------------------------------------
def build_roads():
    """Highways and connected local streets around the airport."""
    roads = NodePath('roads')
    road_col = (0.10, 0.11, 0.12, 1)
    line_col = (0.9, 0.85, 0.3, 1)

    # Broad divided highways with a planted median.
    for y in (2500, -2000):
        for lane_y in (y - 12, y + 12):
            road = _flat_quad(24000, 10, color=road_col)
            road.setPos(0, lane_y, 0.04); road.reparentTo(roads)
            for x in range(-11000, 11000, 40):
                d = _flat_quad(15, 0.35, color=line_col)
                d.setPos(x, lane_y, 0.055); d.reparentTo(roads)
        median = _flat_quad(24000, 5, color=(0.18, 0.34, 0.12, 1))
        median.setPos(0, y, 0.045); median.reparentTo(roads)

    # Two main roads feeding the airport and the city.
    for x in (3500, -4500):
        road = _flat_quad(11, 24000, color=road_col)
        road.setPos(x, 0, 0.005); road.reparentTo(roads)
        for y in range(-11000, 11000, 40):
            d = _flat_quad(0.4, 15, color=line_col)
            d.setPos(x, y, 0.015); d.reparentTo(roads)

    # Downtown streets stay on the edges of blocks, leaving buildings on land.
    for offset in (-1000, -500, 0, 500, 1000):
        for y in (3000 + offset, 5000 + offset):
            s = _flat_quad(2400, 8, color=road_col)
            s.setPos(5000, y, 0.005)
            s.reparentTo(roads)
        for x in (4000 + offset, 6000 + offset):
            s = _flat_quad(8, 2400, color=road_col)
            s.setPos(x, 4000, 0.005)
            s.reparentTo(roads)

    roads.flattenStrong()
    return roads


def build_parks(seed=19):
    """Green public spaces and paths breaking up the nearby neighborhoods."""
    rng = random.Random(seed)
    parks = NodePath('parks')
    park_specs = [
        (-3000, 2700, 950, 520),
        (-650, 2700, 680, 430),
        (1500, -1350, 1050, 520),
        (3300, 1300, 720, 480),
    ]
    for cx, cy, sx, sy in park_specs:
        grass = _flat_quad(sx, sy, color=(0.16, 0.42, 0.18, 1))
        grass.setPos(cx, cy, 0.08)
        grass.reparentTo(parks)
        for offset in (-0.25, 0.25):
            path = _flat_quad(sx * 0.9, 8, color=(0.65, 0.56, 0.38, 1))
            path.setPos(cx, cy + sy * offset, 0.10)
            path.reparentTo(parks)
        for _ in range(16):
            tree = _make_tree(rng)
            tree.setScale(0.65)
            tree.setPos(cx + rng.uniform(-sx * 0.42, sx * 0.42),
                        cy + rng.uniform(-sy * 0.38, sy * 0.38), 0.12)
            tree.reparentTo(parks)
    parks.flattenStrong()
    return parks


def build_nearby_neighborhoods(seed=31):
    """Compact apartments and houses that establish a lived-in airport edge."""
    rng = random.Random(seed)
    neighborhoods = NodePath('nearby_neighborhoods')
    specs = [
        (-3000, 2350, 7, 4, True),
        (-700, 2450, 6, 4, True),
        (1450, -2300, 7, 4, False),
        (3200, 1800, 6, 4, False),
    ]
    for cx, cy, cols, rows, apartments in specs:
        for col in range(cols):
            for row in range(rows):
                x = cx + (col - (cols - 1) / 2) * 105 + rng.uniform(-18, 18)
                y = cy + (row - (rows - 1) / 2) * 105 + rng.uniform(-18, 18)
                if apartments:
                    sx, sy = rng.uniform(42, 66), rng.uniform(38, 58)
                    height = rng.uniform(24, 52)
                else:
                    sx, sy = rng.uniform(30, 48), rng.uniform(30, 45)
                    height = rng.uniform(8, 18)
                building = _building(sx, sy, height, rng, is_downtown=apartments)
                building.setPos(x, y, height / 2)
                building.setH(rng.choice((0, 90, 180, 270)))
                building.reparentTo(neighborhoods)
        road = _flat_quad(cols * 110 + 100, 10, color=(0.12, 0.13, 0.14, 1))
        road.setPos(cx, cy - rows * 55, 0.12)
        road.reparentTo(neighborhoods)
    neighborhoods.flattenStrong()
    return neighborhoods


def build_airport_vicinity(seed=61):
    """Dense Heathrow-edge districts: homes, flats, workshops, and local roads."""
    rng = random.Random(seed)
    vicinity = NodePath('airport_vicinity')
    house_colors = [
        (0.55, 0.50, 0.46, 1), (0.68, 0.63, 0.56, 1),
        (0.48, 0.52, 0.55, 1), (0.72, 0.68, 0.61, 1),
    ]

    # Heathrow-like districts outside the runway and terminal envelopes.
    districts = [
        # (center x, center y, columns, rows, spacing, apartment blocks)
        (1200, 2750, 9, 7, 105, False),   # Cranford / Heston edge
        (2600, 2850, 8, 6, 115, True),    # dense north-east flats
        (1500, -2900, 10, 7, 100, False), # Feltham edge
        (-5000, 1050, 9, 6, 115, False),  # Stanwell edge
        (4300, -850, 8, 6, 125, True),    # industrial/residential east
    ]
    for cx, cy, cols, rows, spacing, apartments in districts:
        district_w = (cols - 1) * spacing
        district_h = (rows - 1) * spacing
        for col in range(cols):
            for row in range(rows):
                x = cx + (col - (cols - 1) / 2) * spacing
                y = cy + (row - (rows - 1) / 2) * spacing
                if -4300 < x < 400 and -300 < y < 2100:
                    continue
                if apartments and (col + row) % 3 == 0:
                    sx, sy, height = 72, 52, rng.uniform(28, 58)
                else:
                    sx, sy, height = rng.uniform(34, 58), rng.uniform(30, 48), rng.uniform(7, 16)
                building = _box(sx, sy, height, rng.choice(house_colors))
                roof = _box(sx * 0.92, sy * 0.92, 0.35,
                            (0.25, 0.25, 0.27, 1))
                roof.setZ(height / 2 + 0.2)
                roof.reparentTo(building)
                building.setPos(x, y, height / 2)
                building.setH(rng.choice((0, 90, 180, 270)))
                building.reparentTo(vicinity)

        # Streets run along block edges, never through the building rows.
        for row in range(rows + 1):
            road = _flat_quad(district_w + spacing, 9,
                              color=(0.12, 0.13, 0.14, 1))
            road.setPos(cx, cy - district_h / 2 - spacing / 2 + row * spacing,
                        0.13)
            road.reparentTo(vicinity)
        for col in range(cols + 1):
            road = _flat_quad(9, district_h + spacing,
                              color=(0.12, 0.13, 0.14, 1))
            road.setPos(cx - district_w / 2 - spacing / 2 + col * spacing,
                        cy, 0.13)
            road.reparentTo(vicinity)

        # Small green pocket at the edge of each district.
        park = _flat_quad(district_w * 0.22, district_h * 0.18,
                          color=(0.17, 0.40, 0.18, 1))
        park.setPos(cx + district_w * 0.36, cy + district_h * 0.34, 0.14)
        park.reparentTo(vicinity)

    vicinity.flattenStrong()
    return vicinity


def build_villages(seed=47):
    """Small distant settlements with homes, church towers, and field roads."""
    rng = random.Random(seed)
    villages = NodePath('villages')
    specs = [(-7200, 5200, 24), (7600, -5600, 20), (-9000, -4300, 18)]
    for cx, cy, count in specs:
        for _ in range(count):
            x = cx + rng.uniform(-500, 500)
            y = cy + rng.uniform(-380, 380)
            sx, sy = rng.uniform(14, 28), rng.uniform(12, 24)
            height = rng.uniform(5, 11)
            house = _building(sx, sy, height, rng, is_downtown=False)
            house.setPos(x, y, height / 2)
            house.setH(rng.choice((0, 90, 180, 270)))
            house.reparentTo(villages)
        road = _flat_quad(1100, 7, color=(0.20, 0.20, 0.18, 1))
        road.setPos(cx, cy, 0.10)
        road.reparentTo(villages)
        tower = _cyl(2.2, 22, color=(0.55, 0.48, 0.38, 1),
                     segments=8, axis='z')
        tower.setPos(cx + 80, cy + 35, 11)
        tower.reparentTo(villages)
    villages.flattenStrong()
    return villages




# ----------------------------------------------------------------------
# River
# ----------------------------------------------------------------------
def build_river():
    """A river running north-south, east of the airport."""
    river = NodePath('river')
    water_col = (0.20, 0.35, 0.50, 1)

    # Main channel — flat quad
    channel = _flat_quad(80, 16000, color=water_col)
    channel.setPos(6000, 0, 0.16)
    channel.reparentTo(river)

    # A slight bend: extra quads offset a bit
    bend1 = _flat_quad(80, 4000, color=water_col)
    bend1.setPos(6100, 4500, 0.16)
    bend1.setH(-3)
    bend1.reparentTo(river)

    bend2 = _flat_quad(80, 4000, color=water_col)
    bend2.setPos(5900, -4500, 0.16)
    bend2.setH(3)
    bend2.reparentTo(river)

    # Banks (slightly darker sand color)
    bank_col = (0.55, 0.48, 0.32, 1)
    for side in (-1, 1):
        bank = _flat_quad(6, 16000, color=bank_col)
        bank.setPos(6000 + side * 43, 0, 0.17)
        bank.reparentTo(river)

    # A couple of bridges crossing the river
    for y in (2500, -2000, -6000):
        bridge = _box(120, 12, 0.6, color=(0.4, 0.4, 0.42, 1))
        bridge.setPos(6000, y, 1.0)
        bridge.reparentTo(river)
        # Bridge pillars
        for dx in (-30, 30):
            p = _box(3, 3, 3, color=(0.5, 0.5, 0.5, 1))
            p.setPos(6000 + dx, y, 1.5)
            p.reparentTo(river)

    return river


# ----------------------------------------------------------------------
# Terminal buildings + hangars + fuel tanks (the airport itself)
# ----------------------------------------------------------------------
def build_terminals():
    """Heathrow-inspired terminal and apron complex between the runways."""
    terminals = NodePath('terminals')
    terminal_col = (0.72, 0.72, 0.78, 1)
    roof_col = (0.5, 0.5, 0.55, 1)

    # T1: long main terminal north of taxiway
    t1 = _box(600, 90, 22, color=terminal_col)
    t1.setPos(-1500, 350, 11); t1.reparentTo(terminals)
    t1_roof = _box(600, 90, 1, color=roof_col)
    t1_roof.setPos(-1500, 350, 22.5); t1_roof.reparentTo(terminals)

    # T2: satellite pier
    t2 = _box(300, 40, 18, color=terminal_col)
    t2.setPos(-2500, 500, 9); t2.reparentTo(terminals)

    # Control tower
    tower_base = _cyl(6, 45, color=(0.75, 0.75, 0.78, 1),
                      segments=12, axis='z')
    tower_base.setPos(-800, 250, 22.5); tower_base.reparentTo(terminals)
    tower_cab = _box(14, 14, 5, color=(0.15, 0.25, 0.45, 1))
    tower_cab.setPos(-800, 250, 47.5); tower_cab.reparentTo(terminals)
    tower_roof = _box(16, 16, 1, color=roof_col)
    tower_roof.setPos(-800, 250, 50.5); tower_roof.reparentTo(terminals)

    # Jetway stubs from T1 (little rectangles jutting toward the taxiway)
    for i in range(-4, 5):
        stub = _box(6, 30, 5, color=(0.6, 0.6, 0.65, 1))
        stub.setPos(-1500 + i * 60, 290, 5)
        stub.reparentTo(terminals)

    # Parking apron (dark asphalt north of terminal)
    apron = _flat_quad(1400, 300, color=(0.16, 0.16, 0.17, 1))
    apron.setPos(-1500, 550, 0.008)
    apron.reparentTo(terminals)

    # Central terminal spine and separated concourses between the runways.
    glass_col = (0.20, 0.38, 0.48, 1)
    central = _box(520, 110, 18, color=terminal_col)
    central.setPos(-1250, 950, 9)
    central.reparentTo(terminals)
    central_roof = _box(540, 120, 2, color=glass_col)
    central_roof.setPos(-1250, 950, 19)
    central_roof.reparentTo(terminals)
    for x in (-1950, -550):
        concourse = _box(430, 55, 10, color=terminal_col)
        concourse.setPos(x, 1220, 5)
        concourse.reparentTo(terminals)
        for gate_x in range(int(x - 160), int(x + 161), 80):
            gate = _box(9, 55, 4, color=(0.58, 0.63, 0.68, 1))
            gate.setPos(gate_x, 1165, 2)
            gate.reparentTo(terminals)

    # Western satellite terminals mirror the distributed Heathrow layout.
    for x, y in ((-2850, 900), (-3200, 1320)):
        satellite = _box(260, 70, 12, color=(0.66, 0.69, 0.74, 1))
        satellite.setPos(x, y, 6)
        satellite.reparentTo(terminals)

    # Landside access loop and structured parking south of the terminal spine.
    access = _flat_quad(1500, 18, color=(0.09, 0.10, 0.11, 1))
    access.setPos(-1250, 700, 0.02)
    access.reparentTo(terminals)
    for x in range(-1850, -650, 70):
        parking = _flat_quad(45, 210, color=(0.22, 0.24, 0.25, 1))
        parking.setPos(x, 500, 0.02)
        parking.reparentTo(terminals)

    return terminals


def build_hangars():
    """A row of hangars south of the runway."""
    hangars = NodePath('hangars')
    hangar_col = (0.55, 0.55, 0.60, 1)
    roof_col = (0.35, 0.35, 0.38, 1)

    for i in range(4):
        x = -3000 + i * 200
        # Main hangar body
        h = _box(150, 100, 20, color=hangar_col)
        h.setPos(x, -400, 10); h.reparentTo(hangars)
        # Roof (slightly wider, darker)
        r = _box(155, 105, 1.5, color=roof_col)
        r.setPos(x, -400, 20.75); r.reparentTo(hangars)
        # Big hangar door (dark rectangle on north face)
        door = _box(80, 1, 15, color=(0.2, 0.2, 0.22, 1))
        door.setPos(x, -350, 7.5); door.reparentTo(hangars)

    # Fuel tank farm — cylinders
    for i in range(6):
        angle = i / 6 * 2 * math.pi
        x = -800 + math.cos(angle) * 80
        y = -600 + math.sin(angle) * 80
        tank = _cyl(15, 12, color=(0.85, 0.85, 0.88, 1),
                    segments=16, axis='z')
        tank.setPos(x, y, 6)
        tank.reparentTo(hangars)
        # Tank top cap ring
        cap = _cyl(15.5, 0.5, color=(0.6, 0.6, 0.62, 1),
                   segments=16, axis='z')
        cap.setPos(x, y, 12.3)
        cap.reparentTo(hangars)

    # A few small support buildings between hangars
    for i in range(6):
        x = -3200 + i * 130
        b = _box(25, 25, 8, color=(0.65, 0.6, 0.55, 1))
        b.setPos(x, -280, 4); b.reparentTo(hangars)

    return hangars


# ----------------------------------------------------------------------
# City clusters (buildings)
# ----------------------------------------------------------------------
def _building(sx, sy, h, rng, is_downtown=False):
    """Building with a slightly different roof color for depth."""
    if is_downtown:
        shade = rng.uniform(0.45, 0.75)
    else:
        shade = rng.uniform(0.35, 0.60)
    tint = rng.uniform(-0.06, 0.06)
    body_col = (shade + tint, shade, shade - tint * 0.5, 1)
    body = _box(sx, sy, h, body_col)

    # Roof slightly darker
    roof_col = (body_col[0] * 0.65, body_col[1] * 0.65, body_col[2] * 0.65, 1)
    roof = _box(sx * 0.98, sy * 0.98, 0.4, roof_col)
    roof.setZ(h / 2 + 0.2)
    roof.reparentTo(body)

    # For downtown skyscrapers, add a rooftop antenna sometimes
    if is_downtown and h > 80 and rng.random() < 0.3:
        antenna = _cyl(0.4, 15, color=(0.3, 0.3, 0.35, 1),
                       segments=6, axis='z')
        antenna.setZ(h / 2 + 7.5)
        antenna.reparentTo(body)

    return body


def build_buildings(seed=42):
    """Multiple city clusters with varying character."""
    rng = random.Random(seed)
    city = NodePath('city')

    # (cx, cy, radius, count, max_h, is_downtown)
    clusters = [
        # Big downtown east-northeast
        ( 5000,  4000, 1400, 140, 180, True),
        # Mid-rise cluster to south-east
        ( 4500, -3500, 1000,  85, 90, False),
        # Residential to west
        (-5500,  3000, 1200,  90, 40, False),
        # Small town to south-west
        (-4000, -5000,  800,  70, 55, False),
        # Suburb north
        (-1000,  6000,  900,  75, 45, False),
        # Industrial to far north-east (mostly low warehouses)
        ( 8500, -1000,  700,  50, 30, False),
    ]

    def clear_of_major_roads(x, y):
        clear = not (
            abs(x - 3500) < 90 or abs(x + 4500) < 90 or
            abs(y - 2500) < 90 or abs(y + 2000) < 90
        )
        if abs(x - 5000) < 1500 and abs(y - 4000) < 1500:
            for offset in (-1000, -500, 0, 500, 1000):
                if (abs(y - (3000 + offset)) < 45 or
                        abs(y - (5000 + offset)) < 45 or
                        abs(x - (4000 + offset)) < 45 or
                        abs(x - (6000 + offset)) < 45):
                    return False
        return clear

    for cx, cy, radius, n, max_h, is_dt in clusters:
        for _ in range(n):
            r = rng.random() ** 0.5 * radius
            th = rng.random() * 2 * math.pi
            x = cx + r * math.cos(th)
            y = cy + r * math.sin(th)
            if not clear_of_major_roads(x, y):
                continue
            sx = rng.uniform(18, 55) if is_dt else rng.uniform(12, 35)
            sy = rng.uniform(18, 55) if is_dt else rng.uniform(12, 35)
            dist_frac = r / radius
            h = rng.uniform(15, max_h) * (1 - 0.55 * dist_frac)
            b = _building(sx, sy, h, rng, is_downtown=is_dt)
            b.setPos(x, y, h / 2)
            b.setH(rng.uniform(0, 360))
            b.reparentTo(city)

    city.flattenStrong()
    return city


# ----------------------------------------------------------------------
# The big one — build everything scenic in one call
# ----------------------------------------------------------------------
def build_city(seed=42):
    """
    Umbrella function — main.py still just calls build_city() and gets
    the whole world outside the airport itself: buildings, trees,
    roads, river, terminals, hangars, grass patches.
    """
    world = NodePath('world_scenery')

    build_fields(seed=seed + 6).reparentTo(world)
    build_roads().reparentTo(world)
    build_river().reparentTo(world)
    build_terminals().reparentTo(world)
    build_hangars().reparentTo(world)
    build_buildings(seed=seed).reparentTo(world)
    build_nearby_neighborhoods(seed=seed + 2).reparentTo(world)
    build_airport_vicinity(seed=seed + 7).reparentTo(world)
    build_parks(seed=seed + 4).reparentTo(world)
    build_villages(seed=seed + 5).reparentTo(world)
    build_trees(seed=seed + 3).reparentTo(world)
    build_night_lighting_group(seed=seed + 17).reparentTo(world)
    return world
def build_city_lights():
    """Deprecated — night lighting moved to night_lighting.py."""
    return NodePath('deprecated_city_lights')

# ----------------------------------------------------------------------
# Lighting
# ----------------------------------------------------------------------
def add_lighting(render):
    """Ambient + directional sun. Late-afternoon warm light."""
    amb = AmbientLight('ambient')
    amb.setColor((0.38, 0.38, 0.44, 1))
    amb_np = render.attachNewNode(amb)
    render.setLight(amb_np)

    sun = DirectionalLight('sun')
    sun.setColor((0.95, 0.88, 0.75, 1))
    sun_np = render.attachNewNode(sun)
    # Sun direction is set dynamically by main.py::_apply_time_of_day()
    render.setLight(sun_np)

    return amb_np, sun_np