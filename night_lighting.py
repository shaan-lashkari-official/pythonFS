"""
night_lighting.py
-----------------
Drop-in night lighting for the flight sim. Everything designed for speed:

  * Street-lamp pools: ONE batched Geom for ~1500 additive ground pools
    (was ~5000 NodePaths in the old build_city_lights — huge FPS win)
  * Building windows: ONE batched Geom for tens of thousands of window
    quads across all districts, placed on real vertical building faces
  * Ambient district glow: broad soft warm quads under dense areas
  * Dynamic PointLights: a pool of 6 real point lights that follow the
    aircraft, snapping to the nearest street lamps every 10 frames.
    Only these produce real illumination on surrounding geometry.

Usage from main.py (3 additions):

    from night_lighting import (
        create_dynamic_night_lights, update_dynamic_night_lights,
        set_night_mode,
    )

    # After scenery is built:
    self.night_pool = create_dynamic_night_lights(self.render, count=6)

    # In your per-frame update task:
    update_dynamic_night_lights(self.night_pool, self.plane.getPos())

    # From your start-menu time-of-day handler:
    set_night_mode(self.render, enabled=True, pool=self.night_pool)
"""

import math
import random

from panda3d.core import (
    Geom, GeomNode, GeomVertexData, GeomVertexFormat, GeomVertexWriter,
    GeomTriangles, NodePath,
    TransparencyAttrib, ColorBlendAttrib, PointLight, Fog,
)


# ---------------------------------------------------------------------
# District specs — must match build_airport_vicinity + build_nearby_neighborhoods
# in scenery.py so windows and pools line up with actual buildings.
# ---------------------------------------------------------------------
DISTRICT_SPECS = [
    # (cx, cy, cols, rows, spacing, is_apartments)
    (1200,  2750,  9, 7, 105, False),
    (2600,  2850,  8, 6, 115, True),
    (1500, -2900, 10, 7, 100, False),
    (4300,  -850,  8, 6, 125, True),
    (-5000, 1050,  9, 6, 115, False),
    (-3000, 2350,  7, 4, 105, True),
    (-700,  2450,  6, 4, 105, True),
    (1450, -2300,  7, 4, 105, False),
    (3200,  1800,  6, 4, 105, False),
]


# ---------------------------------------------------------------------
# Street-lamp positions — cached at module load
# ---------------------------------------------------------------------
def _generate_streetlamp_positions():
    positions = []

    # Divided highways (y = 2500 and y = -2000, both lanes)
    for main_y in (2500, -2000):
        for lane_y in (main_y - 12, main_y + 12):
            for x in range(-11000, 11001, 220):
                positions.append((x, lane_y))

    # N-S main roads (x = 3500 and x = -4500)
    for main_x in (3500, -4500):
        for y in range(-11000, 11001, 220):
            positions.append((main_x, y))

    # District perimeter roads
    for cx, cy, cols, rows, spacing, _ in DISTRICT_SPECS:
        w = cols * spacing
        h = rows * spacing
        # Top and bottom edges
        for c in range(cols + 1):
            x = cx - w / 2 + c * spacing
            positions.append((x, cy - h / 2))
            positions.append((x, cy + h / 2))
        # Left and right edges (skip corners — already added above)
        for r in range(1, rows):
            y = cy - h / 2 + r * spacing
            positions.append((cx - w / 2, y))
            positions.append((cx + w / 2, y))

    return positions


STREETLAMP_POSITIONS = _generate_streetlamp_positions()


# ---------------------------------------------------------------------
# Batched street-lamp ground pools (additive blend)
# ---------------------------------------------------------------------
def build_streetlamp_pools():
    """
    One Geom, one draw call, ~1500 warm street lamp pools.

    Each lamp gets TWO radial discs (fan-triangulated):
      - inner core: bright, tight (6m radius)
      - outer glow: dim, wide (22m radius)
    Per-vertex color goes from warm-orange center to transparent edge,
    which Panda3D interpolates across the fan triangles. Combined with
    additive blending, this reads as soft natural light spread on the
    ground instead of hard rectangles.
    """
    import math

    fmt = GeomVertexFormat.getV3n3c4()
    vdata = GeomVertexData('pools', fmt, Geom.UHStatic)
    vw = GeomVertexWriter(vdata, 'vertex')
    nw = GeomVertexWriter(vdata, 'normal')
    cw = GeomVertexWriter(vdata, 'color')
    tris = GeomTriangles(Geom.UHStatic)

    edge_color = (1.0, 0.55, 0.15, 0.0)   # transparent rim
    core_color = (1.0, 0.75, 0.30, 0.95)  # bright warm center
    glow_color = (1.0, 0.55, 0.15, 0.35)  # softer wide halo

    segments = 12   # rim vertices per disc
    idx = 0

    for x, y in STREETLAMP_POSITIONS:
        # Inner core - bright, small
        # Center vertex
        vw.addData3(x, y, 0.20)
        nw.addData3(0, 0, 1)
        cw.addData4(*core_color)
        # Rim vertices
        for i in range(segments):
            a = 2 * math.pi * i / segments
            vx = x + math.cos(a) * 6.0
            vy = y + math.sin(a) * 6.0
            vw.addData3(vx, vy, 0.20)
            nw.addData3(0, 0, 1)
            cw.addData4(*edge_color)
        # Fan triangles
        for i in range(segments):
            ni = (i + 1) % segments
            tris.addVertices(idx, idx + 1 + i, idx + 1 + ni)
        idx += 1 + segments   # center + rim

        # Outer glow - dim, wide
        vw.addData3(x, y, 0.15)
        nw.addData3(0, 0, 1)
        cw.addData4(*glow_color)
        for i in range(segments):
            a = 2 * math.pi * i / segments
            vx = x + math.cos(a) * 22.0
            vy = y + math.sin(a) * 22.0
            vw.addData3(vx, vy, 0.15)
            nw.addData3(0, 0, 1)
            cw.addData4(*edge_color)
        for i in range(segments):
            ni = (i + 1) % segments
            tris.addVertices(idx, idx + 1 + i, idx + 1 + ni)
        idx += 1 + segments

    geom = Geom(vdata); geom.addPrimitive(tris)
    node = GeomNode('streetlamp_pools'); node.addGeom(geom)
    np = NodePath(node)
    np.setName('streetlamp_pools')
    np.setTransparency(TransparencyAttrib.MAlpha)
    np.setAttrib(ColorBlendAttrib.make(ColorBlendAttrib.MAdd,
                                       ColorBlendAttrib.OIncomingAlpha,
                                       ColorBlendAttrib.OOne))
    np.setLightOff()
    np.setDepthWrite(False)
    np.setBin('transparent', 20)
    return np

# ---------------------------------------------------------------------
# Batched district windows — vertical quads on real building faces
# ---------------------------------------------------------------------
def build_district_windows(seed=17):
    """
    One Geom with thousands of window quads on the north/south/east/west
    faces of every district building. Emissive (setLightOff), so they
    always look "lit" regardless of ambient light in the scene.
    """
    rng = random.Random(seed)

    fmt = GeomVertexFormat.getV3n3c4()
    vdata = GeomVertexData('windows', fmt, Geom.UHStatic)
    vw = GeomVertexWriter(vdata, 'vertex')
    nw = GeomVertexWriter(vdata, 'normal')
    cw = GeomVertexWriter(vdata, 'color')
    tris = GeomTriangles(Geom.UHStatic)

    warm = [
        (1.0, 0.72, 0.28, 1),
        (1.0, 0.85, 0.48, 1),
        (0.98, 0.62, 0.22, 1),
    ]
    cool = [
        (0.72, 0.85, 1.0, 1),
        (0.85, 0.92, 1.0, 1),
    ]

    win_w, win_h = 1.5, 1.2
    floor_h = 3.5
    idx = 0

    for cx, cy, cols, rows, spacing, apartments in DISTRICT_SPECS:
        for col in range(cols):
            for row in range(rows):
                x = cx + (col - (cols - 1) / 2) * spacing
                y = cy + (row - (rows - 1) / 2) * spacing
                # Match scenery.py's airport clearance skip
                if -4300 < x < 400 and -300 < y < 2100:
                    continue

                if apartments and (col + row) % 3 == 0:
                    height, sx, sy = 42, 72, 52
                    palette = warm + cool           # some blue office lights
                else:
                    height, sx, sy = 12, 45, 38
                    palette = warm

                n_floors = max(1, int(height / floor_h))
                n_wx = max(3, int(sx / 3.5))
                n_wy = max(3, int(sy / 3.5))
                lit_prob = 0.55 if apartments else 0.35

                # Four faces: (face_name, normal, base coords)
                faces = [
                    ('north', (0,  1, 0), 'x', x - sx/2, sx / n_wx, y + sy/2 + 0.05, n_wx),
                    ('south', (0, -1, 0), 'x', x - sx/2, sx / n_wx, y - sy/2 - 0.05, n_wx),
                    ('east',  ( 1, 0, 0), 'y', y - sy/2, sy / n_wy, x + sx/2 + 0.05, n_wy),
                    ('west',  (-1, 0, 0), 'y', y - sy/2, sy / n_wy, x - sx/2 - 0.05, n_wy),
                ]
                for face_name, normal, along, axis_start, axis_step, fixed_c, n_w in faces:
                    for floor in range(n_floors):
                        zc = floor * floor_h + 1.8
                        if zc > height - 0.5:
                            break
                        for wi in range(n_w):
                            if rng.random() > lit_prob:
                                continue
                            color = rng.choice(palette)
                            ax_c = axis_start + axis_step * (wi + 0.5)

                            if along == 'x':
                                # Quad in XZ plane at y = fixed_c
                                corners = [
                                    (ax_c - win_w/2, fixed_c, zc - win_h/2),
                                    (ax_c + win_w/2, fixed_c, zc - win_h/2),
                                    (ax_c + win_w/2, fixed_c, zc + win_h/2),
                                    (ax_c - win_w/2, fixed_c, zc + win_h/2),
                                ]
                            else:
                                # Quad in YZ plane at x = fixed_c
                                corners = [
                                    (fixed_c, ax_c - win_w/2, zc - win_h/2),
                                    (fixed_c, ax_c + win_w/2, zc - win_h/2),
                                    (fixed_c, ax_c + win_w/2, zc + win_h/2),
                                    (fixed_c, ax_c - win_w/2, zc + win_h/2),
                                ]

                            for cnr in corners:
                                vw.addData3(*cnr)
                                nw.addData3(*normal)
                                cw.addData4(*color)
                            tris.addVertices(idx,     idx + 1, idx + 2)
                            tris.addVertices(idx,     idx + 2, idx + 3)
                            idx += 4

    geom = Geom(vdata); geom.addPrimitive(tris)
    node = GeomNode('district_windows'); node.addGeom(geom)
    np = NodePath(node)
    np.setName('district_windows')
    np.setLightOff()
    np.setTwoSided(True)   # don't fuss over facing direction
    return np


# ---------------------------------------------------------------------
# Ambient district glow — broad soft warm quads under dense areas
# ---------------------------------------------------------------------
def build_ambient_glow_patches():
    """Deprecated — was creating fake dark AO patches under buildings.
    Real dynamic PointLights now handle this properly."""
    return NodePath('ambient_glow_disabled')

# ---------------------------------------------------------------------
# One-shot: build everything as a hideable group
# ---------------------------------------------------------------------
def build_night_lighting_group(seed=17):
    root = NodePath('night_lighting')
    build_streetlamp_pools().reparentTo(root)
    build_district_windows(seed=seed).reparentTo(root)
    root.hide()
    return root

# ---------------------------------------------------------------------
# Real PointLights that follow the aircraft
# ---------------------------------------------------------------------
def create_dynamic_night_lights(render, count=6,
                                color=(1.0, 0.72, 0.32, 1),
                                attenuation=(1.0, 0.02, 0.002)):
    """
    Create `count` PointLight nodes attached to `render`. They start
    off-screen and disabled. Call enable_dynamic_night_lights() and
    update_dynamic_night_lights() from your main loop.
    """
    pool = {'lights': [], 'enabled': False, 'tick': 0, 'render': render}
    for i in range(count):
        pl = PointLight(f'dyn_night_{i}')
        pl.setColor(color)
        pl.setAttenuation(attenuation)
        pl_np = render.attachNewNode(pl)
        pl_np.setPos(0, 0, -1000)
        pool['lights'].append(pl_np)
    return pool


def enable_dynamic_night_lights(scene_root, pool, enable=True):
    """Attach (or detach) all point lights to the given scene root."""
    for pl_np in pool['lights']:
        if enable:
            scene_root.setLight(pl_np)
        else:
            scene_root.clearLight(pl_np)
    pool['enabled'] = enable


def update_dynamic_night_lights(pool, aircraft_pos, refresh_every=10,
                                search_radius=2500.0, height=6.0):
    """
    Reposition point lights onto the nearest street lamps to the
    aircraft. `aircraft_pos` should be a Point3 or 3-tuple; only x/y
    are used. Cheap enough to call every frame (throttled internally).
    """
    if not pool['enabled']:
        return
    pool['tick'] += 1
    if pool['tick'] < refresh_every:
        return
    pool['tick'] = 0

    try:
        ax, ay = aircraft_pos[0], aircraft_pos[1]
    except TypeError:
        ax, ay = aircraft_pos.getX(), aircraft_pos.getY()

    close = []
    sr = search_radius
    for x, y in STREETLAMP_POSITIONS:
        if abs(x - ax) > sr or abs(y - ay) > sr:
            continue
        close.append((x, y, (x - ax) ** 2 + (y - ay) ** 2))
    close.sort(key=lambda p: p[2])

    for i, pl_np in enumerate(pool['lights']):
        if i < len(close):
            x, y, _ = close[i]
            pl_np.setPos(x, y, height)
        else:
            pl_np.setPos(0, 0, -1000)


# ---------------------------------------------------------------------
# Convenience: full-scene night mode toggle
# ---------------------------------------------------------------------
def set_night_mode(scene_root, enabled, pool=None,
                   sun_light_np=None, ambient_light_np=None):
    """
    Show/hide night lighting elements. Optionally dim the sun and
    warm the ambient light if you pass their NodePaths from
    add_lighting(). Also enables/disables the dynamic PointLight pool.
    """
    # Show/hide batched groups by their node name
    for name in ('streetlamp_pools', 'district_windows',
                 'ambient_glow', 'night_lighting', 'city_lights'):
        for np in scene_root.findAllMatches(f'**/{name}'):
            if enabled:
                np.show()
            else:
                np.hide()

    # Adjust sun + ambient if the caller passed them
    if sun_light_np is not None:
        sun = sun_light_np.node()
        if enabled:
            sun.setColor((0.12, 0.14, 0.22, 1))   # deep blue "moonlight"
        else:
            sun.setColor((0.95, 0.88, 0.75, 1))   # warm daylight

    if ambient_light_np is not None:
        amb = ambient_light_np.node()
        if enabled:
            amb.setColor((0.10, 0.12, 0.18, 1))   # very dark blue ambient
        else:
            amb.setColor((0.38, 0.38, 0.44, 1))

    if pool is not None:
        enable_dynamic_night_lights(scene_root, pool, enabled)


# ---------------------------------------------------------------------
# Fog helper for FPS + atmospheric depth at night
# ---------------------------------------------------------------------
def apply_night_fog(render, near=800.0, far=6500.0,
                    color=(0.03, 0.04, 0.09)):
    """
    Aggressive linear fog for night mode. Culls distant detail visually
    (big FPS win at night) and gives depth. Call when entering night;
    call apply_day_fog() when leaving.
    """
    fog = Fog('night_fog')
    fog.setColor(*color)
    fog.setLinearRange(near, far)
    render.setFog(fog)
    # Tint the sky/backdrop to match
    try:
        base = __import__('builtins').base
        base.setBackgroundColor(*color, 1)
    except Exception:
        pass


def apply_day_fog(render, near=2000.0, far=25000.0,
                  color=(0.55, 0.72, 0.88)):
    fog = Fog('day_fog')
    fog.setColor(*color)
    fog.setLinearRange(near, far)
    render.setFog(fog)
    try:
        base = __import__('builtins').base
        base.setBackgroundColor(*color, 1)
    except Exception:
        pass