"""
minimap.py
----------
Top-right 2D overlay showing aircraft position relative to scenery.
North-up orientation (north always at top of map). Aircraft indicator
stays centered and rotates to show heading. Features scroll under it.

Redraws each frame — cheap enough for the small number of features we
have. If you add many more features, batch static ones.
"""

from panda3d.core import (
    NodePath, CardMaker, LineSegs, TransparencyAttrib, Vec4, TextNode,
)
from direct.gui.OnscreenText import OnscreenText


# Static features in world coords (east_m, north_m). Must match scenery.py.
# Format: dict with type and geometry.
FEATURES = [
    # Runway 27L: line from threshold (0,0) west to (-3902, 0)
    dict(type='line', a=(0, 0), b=(-3902, 0),
         color=(0.95, 0.95, 0.95, 1), width=2.5),
    # Heathrow's parallel northern runway 27R.
    dict(type='line', a=(0, 1800), b=(-3650, 1800),
         color=(0.95, 0.95, 0.95, 1), width=2.5),
    # Parallel taxiway
    dict(type='line', a=(-100, 100), b=(-3900, 100),
         color=(0.85, 0.7, 0.15, 1), width=1.2),
        dict(type='line', a=(-100, 1680), b=(-3800, 1680),
            color=(0.85, 0.7, 0.15, 1), width=1.2),
    # River (X ≈ 6000, running north-south)
    dict(type='line', a=(6000, -8000), b=(6000, 8000),
         color=(0.30, 0.55, 0.85, 1), width=1.8),

    # City clusters (rectangles roughly matching scenery.py)
    dict(type='circle', center=( 5000,  4000), r=1400,
         color=(0.55, 0.55, 0.60, 1), fill=True),  # downtown
    dict(type='circle', center=( 4500, -3500), r=1000,
         color=(0.50, 0.50, 0.55, 1), fill=True),
    dict(type='circle', center=(-5500,  3000), r=1200,
         color=(0.45, 0.50, 0.45, 1), fill=True),
    dict(type='circle', center=(-4000, -5000), r=800,
         color=(0.45, 0.50, 0.45, 1), fill=True),
    dict(type='circle', center=(-1000,  6000), r=900,
         color=(0.45, 0.50, 0.45, 1), fill=True),
    dict(type='circle', center=( 8500, -1000), r=700,
         color=(0.55, 0.50, 0.42, 1), fill=True),   # industrial

    # Airport area (terminals, hangars) — small rectangles by the runway
    dict(type='rect', center=(-1500, 350), sx=600, sy=90,
         color=(0.7, 0.7, 0.8, 1)),
    dict(type='rect', center=(-2400, -400), sx=800, sy=100,
         color=(0.55, 0.55, 0.6, 1)),
        dict(type='rect', center=(-1250, 950), sx=520, sy=110,
            color=(0.35, 0.55, 0.65, 1)),
]


class Minimap:
    def __init__(self, parent, size=0.5, center=(1.03, 0.6),
                 view_radius_m=8000):
        """
        parent:        base.aspect2d
        size:          side length in aspect2d units (0..2 range)
        center:        (x, z) center of map in aspect2d
        view_radius_m: world meters from center to edge of map
        """
        self.size = size
        self.center = center
        self.view_radius = view_radius_m
        # world meters -> aspect2d units
        self.mps = (size / 2) / view_radius_m

        self.root = parent.attachNewNode('minimap')
        self.root.setPos(center[0], 0, center[1])

        # Background: semi-transparent dark
        cm = CardMaker('minimap_bg')
        cm.setFrame(-size / 2, size / 2, -size / 2, size / 2)
        bg = self.root.attachNewNode(cm.generate())
        bg.setColor(0.03, 0.08, 0.03, 0.70)
        bg.setTransparency(TransparencyAttrib.MAlpha)

        # Border
        border = LineSegs()
        border.setColor(0.4, 0.9, 0.4, 0.9)
        border.setThickness(2.0)
        h = size / 2
        border.moveTo(-h, 0, -h)
        border.drawTo( h, 0, -h)
        border.drawTo( h, 0,  h)
        border.drawTo(-h, 0,  h)
        border.drawTo(-h, 0, -h)
        self.root.attachNewNode(border.create())

        # Container that we clear + repopulate each frame (dynamic features)
        self.content = self.root.attachNewNode('content')

        # Aircraft indicator (persistent, rotated each frame)
        self.aircraft_marker = self._make_aircraft_marker()
        self.aircraft_marker.reparentTo(self.root)

        # "N" label at top edge = north indicator
        self.n_label = OnscreenText(
            text='N', pos=(center[0], center[1] + size / 2 - 0.03),
            scale=0.035, fg=(0.9, 1.0, 0.9, 1),
            align=TextNode.ACenter, mayChange=False,
            shadow=(0, 0, 0, 0.8), shadowOffset=(0.05, 0.05),
        )

        # Scale label at bottom-right of map
        self.scale_label = OnscreenText(
            text=f'{int(view_radius_m / 1000)}km',
            pos=(center[0] + size / 2 - 0.04, center[1] - size / 2 + 0.02),
            scale=0.028, fg=(0.7, 1.0, 0.7, 1),
            align=TextNode.ARight, mayChange=False,
            shadow=(0, 0, 0, 0.8), shadowOffset=(0.05, 0.05),
        )

    # ------------------------------------------------------------------
    def _make_aircraft_marker(self):
        """Small triangle pointing 'up' (north). Rotated by heading each frame."""
        ls = LineSegs()
        ls.setColor(1.0, 0.9, 0.2, 1)
        ls.setThickness(2.5)
        # Triangle: nose up, base at bottom (a bit wider than tall)
        nose = (0, 0, 0.03)
        left = (-0.02, 0, -0.02)
        right = (0.02, 0, -0.02)
        ls.moveTo(*nose); ls.drawTo(*left)
        ls.drawTo(*right); ls.drawTo(*nose)
        # Little tail line down the middle for orientation
        ls.moveTo(0, 0, -0.02); ls.drawTo(0, 0, -0.005)
        return NodePath(ls.create())

    # ------------------------------------------------------------------
    def _world_to_map(self, wx, wy, aircraft_east, aircraft_north):
        """World meters (east, north) → map coords (map_x, map_z)."""
        dx = wx - aircraft_east
        dy = wy - aircraft_north
        return dx * self.mps, dy * self.mps

    def _in_view(self, mx, mz, margin=0):
        h = self.size / 2 + margin
        return -h <= mx <= h and -h <= mz <= h

    # ------------------------------------------------------------------
    def update(self, aircraft_east, aircraft_north, heading_deg):
        # Clear old dynamic content
        self.content.node().removeAllChildren()

        # Redraw all features relative to current aircraft position
        for f in FEATURES:
            if f['type'] == 'line':
                self._draw_line(f, aircraft_east, aircraft_north)
            elif f['type'] == 'circle':
                self._draw_circle(f, aircraft_east, aircraft_north)
            elif f['type'] == 'rect':
                self._draw_rect(f, aircraft_east, aircraft_north)

        # Rotate aircraft marker to show heading. Panda2D 'R' rotates
        # around the axis pointing into the screen. Heading in world:
        # The marker nose points toward +Z (north). Panda3D's positive R
        # rotates that vector clockwise on this x/z overlay, matching a
        # clockwise aviation heading.
        self.aircraft_marker.setR(heading_deg)

    # ------------------------------------------------------------------
    def _draw_line(self, f, ae, an):
        ax, az = self._world_to_map(*f['a'], ae, an)
        bx, bz = self._world_to_map(*f['b'], ae, an)
        # Cheap clip: skip if both endpoints are far outside
        if not (self._in_view(ax, az, 0.05) or self._in_view(bx, bz, 0.05)):
            # Both off-screen; skip only if same side
            if (ax < -self.size/2 and bx < -self.size/2) or \
               (ax >  self.size/2 and bx >  self.size/2) or \
               (az < -self.size/2 and bz < -self.size/2) or \
               (az >  self.size/2 and bz >  self.size/2):
                return
        ls = LineSegs()
        ls.setColor(*f['color'])
        ls.setThickness(f.get('width', 1.5))
        ls.moveTo(ax, 0, az)
        ls.drawTo(bx, 0, bz)
        self.content.attachNewNode(ls.create())

    def _draw_circle(self, f, ae, an):
        cx, cz = self._world_to_map(*f['center'], ae, an)
        r = f['r'] * self.mps
        # Skip if entirely off-screen
        h = self.size / 2
        if cx + r < -h or cx - r > h or cz + r < -h or cz - r > h:
            return
        ls = LineSegs()
        ls.setColor(*f['color'])
        ls.setThickness(1.5)
        import math
        segments = 20
        for i in range(segments + 1):
            a = 2 * math.pi * i / segments
            x = cx + math.cos(a) * r
            z = cz + math.sin(a) * r
            if i == 0:
                ls.moveTo(x, 0, z)
            else:
                ls.drawTo(x, 0, z)
        self.content.attachNewNode(ls.create())

    def _draw_rect(self, f, ae, an):
        cx, cz = self._world_to_map(*f['center'], ae, an)
        sx, sz = f['sx'] * self.mps / 2, f['sy'] * self.mps / 2
        h = self.size / 2
        if cx + sx < -h or cx - sx > h or cz + sz < -h or cz - sz > h:
            return
        ls = LineSegs()
        ls.setColor(*f['color'])
        ls.setThickness(1.5)
        ls.moveTo(cx - sx, 0, cz - sz)
        ls.drawTo(cx + sx, 0, cz - sz)
        ls.drawTo(cx + sx, 0, cz + sz)
        ls.drawTo(cx - sx, 0, cz + sz)
        ls.drawTo(cx - sx, 0, cz - sz)
        self.content.attachNewNode(ls.create())