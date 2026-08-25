"""
shadow.py
---------
Fake aircraft shadow projected onto the ground directly below the plane.
Dark aircraft-shaped silhouette (fuselage + wings + H-stab), scales and
fades with altitude so it reads as a depth/altitude cue on approach.

Not a real shader-projected shadow — no sun-position math — but it's the
altitude-judgement cue pilots actually use (and what most indie sims
implement). Zero shader work, essentially free at runtime.

Usage from main.py (3 lines total):

    from shadow import create_aircraft_shadow, update_aircraft_shadow

    # In Sim.__init__, after scenery is built:
    self.shadow = create_aircraft_shadow(self.render)

    # In your per-frame update task:
    east, north, up = self.fd.local_position_enu()
    update_aircraft_shadow(self.shadow, east, north, up,
                           self.fd.heading_deg())
"""

from panda3d.core import (
    Geom, GeomNode, GeomVertexData, GeomVertexFormat, GeomVertexWriter,
    GeomTriangles, NodePath, TransparencyAttrib,
)


# ------------------------------------------------------------------
# Primitive: single dark quad
# ------------------------------------------------------------------
def _shadow_quad(sx, sy, color=(0.05, 0.05, 0.08, 1.0)):
    """Flat horizontal quad centered on origin, sx wide (X), sy long (Y)."""
    fmt = GeomVertexFormat.getV3n3c4()
    vdata = GeomVertexData('shadow_quad', fmt, Geom.UHStatic)
    vdata.setNumRows(4)
    vw = GeomVertexWriter(vdata, 'vertex')
    nw = GeomVertexWriter(vdata, 'normal')
    cw = GeomVertexWriter(vdata, 'color')

    hx, hy = sx / 2, sy / 2
    for x, y in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)):
        vw.addData3(x, y, 0)
        nw.addData3(0, 0, 1)
        cw.addData4(*color)

    tris = GeomTriangles(Geom.UHStatic)
    tris.addVertices(0, 1, 2)
    tris.addVertices(0, 2, 3)

    geom = Geom(vdata); geom.addPrimitive(tris)
    node = GeomNode('shadow_quad'); node.addGeom(geom)
    return NodePath(node)


# ------------------------------------------------------------------
# Build shadow silhouette
# ------------------------------------------------------------------
def create_aircraft_shadow(render):
    """
    Build an A320-shaped shadow silhouette (fuselage + wings + H-stab)
    and attach it to render. Convention: aircraft nose points +Y (same
    as plane_model.py), so the shadow's H matches the aircraft's H.
    """
    shadow = NodePath('aircraft_shadow')

    # Fuselage (37.6m long, 4m wide)
    fuse = _shadow_quad(4.0, 37.6)
    fuse.reparentTo(shadow)

    # Main wings (34m span, ~4.5m avg chord). Positioned slightly aft of
    # CG to match a real A320's wing station.
    wing = _shadow_quad(34.0, 4.5)
    wing.setY(-1.0)
    wing.reparentTo(shadow)

    # Horizontal stabilizer (12m span, ~2.5m chord), near tail
    hstab = _shadow_quad(12.0, 2.5)
    hstab.setY(-16.0)
    hstab.reparentTo(shadow)

    # --- Rendering setup ---
    shadow.setTransparency(TransparencyAttrib.MAlpha)
    shadow.setDepthWrite(False)      # don't occlude other transparent stuff
    shadow.setDepthOffset(1)          # nudge toward camera, avoids Z-fight
    shadow.setLightOff()              # shadow is a flat dark shape, unaffected by lights
    shadow.setTwoSided(True)          # visible from above OR below
    shadow.setBin('fixed', 5)         # render after opaque ground but before UI
    shadow.flattenStrong()            # one draw call

    shadow.reparentTo(render)
    return shadow


# ------------------------------------------------------------------
# Per-frame update
# ------------------------------------------------------------------
def update_aircraft_shadow(shadow_np, aircraft_east, aircraft_north,
                           aircraft_up_m, heading_deg,
                           ground_z=0.0,
                           full_dark_below_m=15.0,
                           fade_range_m=700.0,
                           min_alpha=0.06,
                           max_alpha=0.75,
                           max_scale_altitude_m=3000.0):
    """
    Project shadow under aircraft. Scale + fade with altitude:
      - Below `full_dark_below_m`: sharp dark shadow, 1:1 size
      - Above that: grows slightly (simulates penumbra spread) and fades
      - Very high (>fade_range_m): faint but still visible for reference

    Tuning:
      full_dark_below_m — altitude at which shadow is at max darkness
      fade_range_m      — altitude at which shadow fades to min_alpha
      max_alpha         — darkness at ground contact (0.75 = 75% opaque)
      min_alpha         — floor when high up so shadow doesn't fully vanish
      max_scale_altitude_m — altitude at which shadow is 2× real plane size
    """
    # Skip if somehow below ground
    if aircraft_up_m < -5:
        shadow_np.hide()
        return
    shadow_np.show()

    # Position: directly under aircraft, slightly above ground surface
    shadow_np.setPos(aircraft_east, aircraft_north, ground_z + 0.20)

    # Heading: match aircraft's Panda H convention. main.py sets
    # plane.setHpr(-heading_deg, ...), so we use the same expression.
    shadow_np.setH((-heading_deg) % 360.0)

    # Altitude for cue calc: use height above ground
    agl = max(0.0, aircraft_up_m - ground_z)

    if agl <= full_dark_below_m:
        alpha = max_alpha
        scale = 1.0
    else:
        # Fade toward min_alpha over fade_range_m
        fade_t = min(1.0, (agl - full_dark_below_m) / fade_range_m)
        alpha = max_alpha - (max_alpha - min_alpha) * fade_t
        # Grow slightly with altitude (penumbra sim)
        scale = 1.0 + min(1.0, agl / max_scale_altitude_m)

    shadow_np.setColorScale(1, 1, 1, alpha)
    shadow_np.setScale(scale)