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


# ----------------------------------------------------------------------
# Ground
# ----------------------------------------------------------------------
def build_ground(size=30000.0):
    """Base ground: dark green everywhere."""
    ground = _flat_quad(size, size, color=(0.18, 0.32, 0.14, 1))
    ground.setZ(-0.05)
    return ground


def _grass_patches(parent, seed=1):
    """Scatter subtle grass color variation patches so the ground isn't flat."""
    rng = random.Random(seed)
    for _ in range(220):
        x = rng.uniform(-12000, 12000)
        y = rng.uniform(-12000, 12000)
        # Skip anywhere near the runway (visual noise on the strip)
        if -4200 < x < 200 and -400 < y < 400:
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
    taxiway = _flat_quad(length + 400, 25, color=(0.14, 0.14, 0.15, 1))
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
        connector = _flat_quad(25, 100, color=(0.14, 0.14, 0.15, 1))
        connector.setPos(x_pos, 50, 0.005)
        connector.reparentTo(rwy)

    return rwy


# ----------------------------------------------------------------------
# Runway lights (unchanged from v1)
# ----------------------------------------------------------------------
def _light_point(color=(1, 1, 1, 1), size=1.5):
    cm = CardMaker('light')
    cm.setFrame(-size / 2, size / 2, -size / 2, size / 2)
    np = NodePath(cm.generate())
    np.setColor(*color)
    np.setTransparency(TransparencyAttrib.MAlpha)
    np.setAttrib(ColorBlendAttrib.make(ColorBlendAttrib.MAdd,
                                       ColorBlendAttrib.OIncomingAlpha,
                                       ColorBlendAttrib.OOne))
    np.setLightOff()
    np.setBillboardPointEye()
    return np


def build_runway_lights(length=3902.0, width=45.0):
    lights = NodePath('runway_lights')

    # Threshold — green
    for i in range(6):
        y = -width / 2 + (i + 0.5) * (width / 6)
        l = _light_point((0.0, 1.0, 0.2, 1), size=1.2)
        l.setPos(0.5, y, 0.5); l.reparentTo(lights)

    # Edge lights
    n_edge = int(length / 60)
    for i in range(n_edge + 1):
        x = -i * (length / n_edge)
        color = (1, 1, 0.4, 1) if x < -length + 600 else (1, 1, 1, 1)
        for side in (-1, 1):
            l = _light_point(color, size=1.0)
            l.setPos(x, side * (width / 2 + 1), 0.5); l.reparentTo(lights)

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
        l.setPos(x, 0, 0.4); l.reparentTo(lights)

    # End lights — red
    for i in range(6):
        y = -width / 2 + (i + 0.5) * (width / 6)
        l = _light_point((1, 0, 0, 1), size=1.2)
        l.setPos(-length, y, 0.5); l.reparentTo(lights)

    # PAPI
    papi_parent = NodePath('papi')
    for i in range(4):
        l = _light_point((1, 1, 1, 1), size=1.6)
        l.setName(f'papi_{i}')
        l.setPos(-300, -width / 2 - 15 - i * 9, 1.5)
        l.reparentTo(papi_parent)
    papi_parent.reparentTo(lights)

    # Approach lighting centerline extension
    for i in range(1, 20):
        l = _light_point((1, 1, 1, 1), size=1.4)
        l.setPos(i * 30.0, 0, 0.5); l.reparentTo(lights)
    # Crossbar
    for j in range(-4, 5):
        l = _light_point((1, 1, 1, 1), size=1.2)
        l.setPos(300, j * 4, 0.5); l.reparentTo(lights)

    return lights


def update_papi(scene_root, aircraft_east, aircraft_up):
    """4-bulb PAPI: red/white based on angle to touchdown zone."""
    dx = aircraft_east - (-300.0)
    if dx <= 0:
        return
    angle_deg = math.degrees(math.atan2(max(aircraft_up, 0.1), dx))
    transitions = [2.5, 2.83, 3.17, 3.5]
    for i, t in enumerate(transitions):
        node = scene_root.find(f'**/papi_{i}')
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
            if -4200 < x < 300 and -300 < y < 300:
                continue
            t = _make_tree(rng)
            t.setPos(x, y, 0)
            t.setH(rng.uniform(0, 360))
            t.reparentTo(trees)

    # Scattered singles — random across the map
    for _ in range(600):
        x = rng.uniform(-10000, 10000)
        y = rng.uniform(-10000, 10000)
        if -4400 < x < 400 and -800 < y < 800:
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
    """Simple grid + a couple of highways."""
    roads = NodePath('roads')
    road_col = (0.22, 0.22, 0.23, 1)
    line_col = (0.9, 0.85, 0.3, 1)

    # Two east-west "highways"
    for y in (2500, -2000):
        road = _flat_quad(24000, 14, color=road_col)
        road.setPos(0, y, 0.005); road.reparentTo(roads)
        # centerline dashes
        for x in range(-11000, 11000, 40):
            d = _flat_quad(15, 0.4, color=line_col)
            d.setPos(x, y, 0.015); d.reparentTo(roads)

    # Two north-south roads
    for x in (3500, -4500):
        road = _flat_quad(14, 24000, color=road_col)
        road.setPos(x, 0, 0.005); road.reparentTo(roads)
        for y in range(-11000, 11000, 40):
            d = _flat_quad(0.4, 15, color=line_col)
            d.setPos(x, y, 0.015); d.reparentTo(roads)

    # Grid within downtown cluster (5000, 4000)
    for i in range(-3, 4):
        # E-W streets
        s = _flat_quad(2400, 8, color=road_col)
        s.setPos(5000, 4000 + i * 200, 0.005)
        s.reparentTo(roads)
        # N-S streets
        s = _flat_quad(8, 2400, color=road_col)
        s.setPos(5000 + i * 200, 4000, 0.005)
        s.reparentTo(roads)

    roads.flattenStrong()
    return roads


# ----------------------------------------------------------------------
# River
# ----------------------------------------------------------------------
def build_river():
    """A river running north-south, east of the airport."""
    river = NodePath('river')
    water_col = (0.20, 0.35, 0.50, 1)

    # Main channel — flat quad
    channel = _flat_quad(80, 16000, color=water_col)
    channel.setPos(6000, 0, 0.02)
    channel.reparentTo(river)

    # A slight bend: extra quads offset a bit
    bend1 = _flat_quad(80, 4000, color=water_col)
    bend1.setPos(6100, 4500, 0.02)
    bend1.setH(-3)
    bend1.reparentTo(river)

    bend2 = _flat_quad(80, 4000, color=water_col)
    bend2.setPos(5900, -4500, 0.02)
    bend2.setH(3)
    bend2.reparentTo(river)

    # Banks (slightly darker sand color)
    bank_col = (0.55, 0.48, 0.32, 1)
    for side in (-1, 1):
        bank = _flat_quad(6, 16000, color=bank_col)
        bank.setPos(6000 + side * 43, 0, 0.015)
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
    """Large terminal buildings north of the runway."""
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

    for cx, cy, radius, n, max_h, is_dt in clusters:
        for _ in range(n):
            r = rng.random() ** 0.5 * radius
            th = rng.random() * 2 * math.pi
            x = cx + r * math.cos(th)
            y = cy + r * math.sin(th)
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

    _grass_patches(world, seed=seed + 1)
    build_roads().reparentTo(world)
    build_river().reparentTo(world)
    build_terminals().reparentTo(world)
    build_hangars().reparentTo(world)
    build_buildings(seed=seed).reparentTo(world)
    build_trees(seed=seed + 3).reparentTo(world)

    return world


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
    sun_np.setHpr(-40, -50, 0)
    render.setLight(sun_np)

    return amb_np, sun_np