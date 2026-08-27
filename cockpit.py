"""
cockpit.py — A320 glass cockpit from captain's perspective.

Layout mirrors real A320: windscreen visible through top ~45% of screen,
solid dark dashboard fills bottom ~55%, with PFD (left) and ND (right)
as compact screens embedded in the panel. Thick window pillars, glareshield,
and overhead strip frame the view.

All 2D in aspect2d (OnscreenText + CardMaker). 3D shell provides depth
when panning with RMB.
"""

import math
from panda3d.core import (
    CardMaker, NodePath, TextNode,
    Geom, GeomNode, GeomVertexData, GeomVertexFormat, GeomVertexWriter,
    GeomTriangles,
)
from direct.gui.OnscreenText import OnscreenText

# ── Colours ──────────────────────────────────────────────────────────
CLR_GREEN   = (0.2, 1.0, 0.4, 1)
CLR_CYAN    = (0.4, 0.92, 1.0, 1)
CLR_AMBER   = (1.0, 0.75, 0.1, 1)
CLR_RED     = (1.0, 0.25, 0.15, 1)
CLR_WHITE   = (0.92, 0.95, 0.92, 1)
CLR_DIM     = (0.40, 0.48, 0.40, 1)
CLR_MAGENTA = (0.9, 0.3, 0.9, 1)

# Dashboard / frame colours
_DASH   = (0.028, 0.032, 0.038, 1)   # main dashboard surface
_GLARE  = (0.042, 0.046, 0.052, 1)   # glareshield
_PILLAR = (0.032, 0.036, 0.042, 1)   # window pillars
_SCREEN = (0.04, 0.055, 0.08, 1)     # LCD screen background
_SKY    = (0.12, 0.30, 0.72, 0.92)   # attitude sky
_GND    = (0.50, 0.32, 0.10, 0.92)   # attitude ground


# ── Helpers ──────────────────────────────────────────────────────────
def _card(parent, x, z, w, h, color, sort=0):
    cm = CardMaker('c')
    cm.setFrame(-w / 2, w / 2, -h / 2, h / 2)
    cm.setColor(*color)
    np = parent.attachNewNode(cm.generate())
    np.setPos(x, 0, z)
    np.setTransparency(1)
    if sort:
        np.setBin('fixed', sort)
    return np


def _txt(parent, x, z, text, align='left', scale=0.032, fg=CLR_GREEN, sort=0):
    a = {'left': TextNode.ALeft, 'right': TextNode.ARight,
         'center': TextNode.ACenter}.get(align, TextNode.ALeft)
    t = OnscreenText(
        text=text, pos=(x, z), scale=scale, fg=fg,
        align=a, mayChange=True, shadow=(0, 0, 0, 0.85),
        shadowOffset=(0.04, 0.04), parent=parent,
    )
    if sort:
        t.setBin('fixed', sort)
    return t


# ── 3D cockpit shell (unchanged) ────────────────────────────────────
def _make_box_geom(sx, sy, sz, color=(1, 1, 1, 1)):
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    faces = [
        ((0,0,1),  [(-hx,-hy,hz),(hx,-hy,hz),(hx,hy,hz),(-hx,hy,hz)]),
        ((0,0,-1), [(-hx,hy,-hz),(hx,hy,-hz),(hx,-hy,-hz),(-hx,-hy,-hz)]),
        ((0,1,0),  [(hx,hy,-hz),(-hx,hy,-hz),(-hx,hy,hz),(hx,hy,hz)]),
        ((0,-1,0), [(-hx,-hy,-hz),(hx,-hy,-hz),(hx,-hy,hz),(-hx,-hy,hz)]),
        ((1,0,0),  [(hx,-hy,-hz),(hx,hy,-hz),(hx,hy,hz),(hx,-hy,hz)]),
        ((-1,0,0), [(-hx,hy,-hz),(-hx,-hy,-hz),(-hx,-hy,hz),(-hx,hy,hz)]),
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
            vwr.addData3(*c); nwr.addData3(*normal); cwr.addData4(*color)
        tris.addVertices(idx, idx+1, idx+2)
        tris.addVertices(idx, idx+2, idx+3)
        idx += 4
    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode('box')
    node.addGeom(geom)
    return NodePath(node)


def build_cockpit_shell(plane_node):
    shell = NodePath('cockpit_shell')
    shell.reparentTo(plane_node)
    for _, pos, size, color in [
        ('dashboard',    (0,17.5,1.3),    (3.0,0.1,1.0),  (0.08,0.08,0.10,1)),
        ('glareshield',  (0,17.8,2.0),    (2.8,0.3,0.08), (0.06,0.06,0.08,1)),
        ('left_pillar',  (-1.6,17.0,2.0), (0.12,1.2,1.8), (0.07,0.07,0.09,1)),
        ('right_pillar', (1.6,17.0,2.0),  (0.12,1.2,1.8), (0.07,0.07,0.09,1)),
        ('center_ped',   (0,16.5,0.6),    (0.5,1.0,0.8),  (0.05,0.05,0.07,1)),
        ('left_console', (-1.4,16.5,0.8), (0.4,1.0,0.3),  (0.06,0.06,0.08,1)),
        ('right_console',(1.4,16.5,0.8),  (0.4,1.0,0.3),  (0.06,0.06,0.08,1)),
        ('overhead',     (0,17.0,3.0),    (2.0,0.8,0.06), (0.05,0.05,0.07,1)),
        ('coaming',      (0,17.9,1.95),   (2.5,0.2,0.05), (0.04,0.04,0.06,1)),
    ]:
        box = _make_box_geom(*size, color=color)
        box.setPos(*pos)
        box.reparentTo(shell)
    shell.flattenStrong()
    return shell


# =====================================================================
# GlassCockpit — 2D overlay
# =====================================================================
class GlassCockpit:

    # ── PFD / ND anchor points ──
    # PFD screen centre          ND screen centre
    PX, PZ = -0.55, -0.47       # PFD
    NX, NZ =  0.55, -0.47       # ND

    def __init__(self, parent_2d):
        self.root = parent_2d.attachNewNode('cockpit_root')
        self.root.hide()

        # ==============================================================
        # LAYER 2 — instrument screen backgrounds (sort=15)
        # No opaque frame panels — the 3D cockpit model provides framing.
        # ==============================================================
        _card(self.root, self.PX, self.PZ, 0.58, 0.60, _SCREEN, sort=15)
        _card(self.root, self.NX, self.NZ, 0.58, 0.60, _SCREEN, sort=15)
        # ECAM strip (below PFD/ND)
        _card(self.root, 0, -0.90, 1.50, 0.20, _SCREEN, sort=15)

        # ==============================================================
        # LAYER 3 — instrument content (sort=20+)
        # ==============================================================
        S = 20  # base sort for all text/cards in instruments

        # ────────── PFD ──────────
        px, pz = self.PX, self.PZ   # (-0.55, -0.47)

        # Attitude indicator
        self.att_sky = _card(self.root, px, pz + 0.05, 0.34, 0.22, _SKY, sort=S)
        self.att_gnd = _card(self.root, px, pz - 0.15, 0.34, 0.22, _GND, sort=S)

        # Pitch ladder (7 labels, -15 to +15 in 5-deg steps)
        self.pitch_labels = []
        for deg in range(-15, 20, 5):
            t = _txt(self.root, px, pz, '', align='center',
                     scale=0.020, fg=CLR_WHITE, sort=S+2)
            self.pitch_labels.append((deg, t))

        # Roll readout (top of attitude ball)
        self.roll_txt = _txt(self.root, px, pz + 0.20, '',
                             align='center', scale=0.022, fg=CLR_WHITE, sort=S+2)

        # Aircraft symbol (fixed wings at center of attitude)
        self.acft_sym = _txt(self.root, px, pz - 0.02, '-  +  -',
                             align='center', scale=0.024, fg=CLR_GREEN, sort=S+3)

        # ── Speed tape (left strip of PFD) ──
        self.spd_bg = _card(self.root, px - 0.24, pz, 0.10, 0.50,
                            (0.025, 0.035, 0.05, 0.95), sort=S+1)
        self.spd_main = _txt(self.root, px - 0.24, pz - 0.01, '---',
                             align='center', scale=0.036, fg=CLR_GREEN, sort=S+4)
        self.spd_box = _card(self.root, px - 0.24, pz - 0.01, 0.09, 0.045,
                             (0.06, 0.08, 0.12, 0.9), sort=S+3)
        self.spd_pool = []
        for _ in range(8):
            t = _txt(self.root, px - 0.24, 0, '', align='center',
                     scale=0.019, fg=CLR_WHITE, sort=S+2)
            self.spd_pool.append(t)
        # V-speed markers
        self.v1_txt  = _txt(self.root, px - 0.20, 0, '1', align='left',
                            scale=0.017, fg=CLR_CYAN, sort=S+2)
        self.vr_txt  = _txt(self.root, px - 0.20, 0, 'R', align='left',
                            scale=0.017, fg=CLR_CYAN, sort=S+2)
        self.v2_txt  = _txt(self.root, px - 0.20, 0, '2', align='left',
                            scale=0.017, fg=CLR_MAGENTA, sort=S+2)
        # Mach readout
        self.mach_txt = _txt(self.root, px - 0.24, pz - 0.27, '',
                             align='center', scale=0.020, fg=CLR_GREEN, sort=S+2)

        # ── Altitude tape (right strip of PFD) ──
        self.alt_bg = _card(self.root, px + 0.24, pz, 0.10, 0.50,
                            (0.025, 0.035, 0.05, 0.95), sort=S+1)
        self.alt_main = _txt(self.root, px + 0.24, pz - 0.01, '-----',
                             align='center', scale=0.032, fg=CLR_GREEN, sort=S+4)
        self.alt_box = _card(self.root, px + 0.24, pz - 0.01, 0.10, 0.040,
                             (0.06, 0.08, 0.12, 0.9), sort=S+3)
        self.alt_pool = []
        for _ in range(8):
            t = _txt(self.root, px + 0.24, 0, '', align='center',
                     scale=0.019, fg=CLR_WHITE, sort=S+2)
            self.alt_pool.append(t)
        # Radio altitude
        self.ra_txt = _txt(self.root, px + 0.24, pz - 0.27, '',
                           align='center', scale=0.028, fg=CLR_GREEN, sort=S+2)

        # ── Heading strip (bottom of PFD) ──
        self.hdg_bg = _card(self.root, px, pz - 0.25, 0.40, 0.06,
                            (0.025, 0.035, 0.05, 0.95), sort=S+1)
        self.hdg_main = _txt(self.root, px, pz - 0.21, '',
                             align='center', scale=0.026, fg=CLR_GREEN, sort=S+4)
        self.hdg_box = _card(self.root, px, pz - 0.21, 0.07, 0.032,
                             (0.06, 0.08, 0.12, 0.9), sort=S+3)
        self.hdg_pool = []
        for _ in range(7):
            t = _txt(self.root, px, pz - 0.26, '', align='center',
                     scale=0.017, fg=CLR_WHITE, sort=S+2)
            self.hdg_pool.append(t)

        # ── VS indicator (far right edge of PFD) ──
        self.vs_txt = _txt(self.root, px + 0.28, pz + 0.08, '',
                           align='left', scale=0.022, fg=CLR_GREEN, sort=S+2)

        # ── FMA (top of PFD screen) ──
        self.fma_thr = _txt(self.root, px - 0.16, pz + 0.25, '---',
                            align='center', scale=0.022, fg=CLR_GREEN, sort=S+2)
        self.fma_lat = _txt(self.root, px, pz + 0.25, '---',
                            align='center', scale=0.022, fg=CLR_DIM, sort=S+2)
        self.fma_ver = _txt(self.root, px + 0.16, pz + 0.25, '---',
                            align='center', scale=0.022, fg=CLR_GREEN, sort=S+2)

        # ────────── ND ──────────
        nx, nz = self.NX, self.NZ   # (0.55, -0.47)

        # Compass rose labels
        compass_data = [
            (0,'N'), (30,'3'), (60,'6'), (90,'E'),
            (120,'12'), (150,'15'), (180,'S'), (210,'21'),
            (240,'24'), (270,'W'), (300,'30'), (330,'33'),
        ]
        self.nd_compass = []
        for deg, label in compass_data:
            t = _txt(self.root, nx, nz, label, align='center',
                     scale=0.022, fg=CLR_WHITE, sort=S+2)
            self.nd_compass.append((deg, t))
        # Aircraft triangle symbol
        self.nd_acft = _txt(self.root, nx, nz - 0.02, '^',
                            align='center', scale=0.032, fg=CLR_GREEN, sort=S+3)
        # Range ring (visual circle — approximate with dashes)
        self.nd_ring = _txt(self.root, nx, nz, '',
                            align='center', scale=0.020, fg=CLR_DIM, sort=S+1)
        # Heading readout at top
        self.nd_hdg = _txt(self.root, nx, nz + 0.26, 'HDG ---',
                           align='center', scale=0.026, fg=CLR_GREEN, sort=S+2)
        # GS + TAS at bottom
        self.nd_gs  = _txt(self.root, nx - 0.18, nz - 0.26, 'GS ---',
                           align='left', scale=0.020, fg=CLR_WHITE, sort=S+2)
        self.nd_tas = _txt(self.root, nx + 0.05, nz - 0.26, 'TAS ---',
                           align='left', scale=0.020, fg=CLR_WHITE, sort=S+2)

        # ────────── ECAM (lower centre strip) ──────────
        # Engine 1 (left half)
        ex1 = -0.32
        self.e1_lbl = _txt(self.root, ex1, -0.83, 'N1', align='left',
                           scale=0.019, fg=CLR_WHITE, sort=S+2)
        self.e1_n1  = _txt(self.root, ex1 + 0.18, -0.83, '--.-', align='right',
                           scale=0.026, fg=CLR_GREEN, sort=S+2)
        self.e1_bar = _txt(self.root, ex1, -0.87, '[          ]', align='left',
                           scale=0.016, fg=CLR_GREEN, sort=S+2)
        self.e1_egt = _txt(self.root, ex1, -0.91, 'EGT ---', align='left',
                           scale=0.018, fg=CLR_GREEN, sort=S+2)
        self.e1_ff  = _txt(self.root, ex1, -0.95, 'FF ----', align='left',
                           scale=0.018, fg=CLR_GREEN, sort=S+2)
        # Engine 2 (right half)
        ex2 = 0.04
        self.e2_lbl = _txt(self.root, ex2, -0.83, 'N1', align='left',
                           scale=0.019, fg=CLR_WHITE, sort=S+2)
        self.e2_n1  = _txt(self.root, ex2 + 0.18, -0.83, '--.-', align='right',
                           scale=0.026, fg=CLR_GREEN, sort=S+2)
        self.e2_bar = _txt(self.root, ex2, -0.87, '[          ]', align='left',
                           scale=0.016, fg=CLR_GREEN, sort=S+2)
        self.e2_egt = _txt(self.root, ex2, -0.91, 'EGT ---', align='left',
                           scale=0.018, fg=CLR_GREEN, sort=S+2)
        self.e2_ff  = _txt(self.root, ex2, -0.95, 'FF ----', align='left',
                           scale=0.018, fg=CLR_GREEN, sort=S+2)
        # Fuel + flap
        self.fuel_txt = _txt(self.root, 0, -0.99, 'FUEL ---- LBS', align='center',
                             scale=0.018, fg=CLR_GREEN, sort=S+2)
        self.flap_txt = _txt(self.root, 0.38, -0.83, 'FLAP UP', align='left',
                             scale=0.022, fg=CLR_GREEN, sort=S+2)

        # ────────── FCU strip (on glareshield) ──────────
        self.fcu_spd = _txt(self.root, -0.50, -0.03, 'SPD ---', align='center',
                            scale=0.024, fg=CLR_CYAN, sort=S+5)
        self.fcu_hdg = _txt(self.root, -0.17, -0.03, 'HDG ---', align='center',
                            scale=0.024, fg=CLR_CYAN, sort=S+5)
        self.fcu_alt = _txt(self.root, 0.17, -0.03, 'ALT -----', align='center',
                            scale=0.024, fg=CLR_CYAN, sort=S+5)
        self.fcu_vs  = _txt(self.root, 0.50, -0.03, 'V/S ----', align='center',
                            scale=0.024, fg=CLR_CYAN, sort=S+5)

        # ────────── Gear indicator (lower right dashboard) ──────────
        _card(self.root, 0.95, -0.88, 0.18, 0.18, (0.03, 0.04, 0.05, 1), sort=S)
        self.gear_title = _txt(self.root, 0.95, -0.80, 'GEAR', align='center',
                               scale=0.020, fg=CLR_WHITE, sort=S+2)
        self.gear_n = _txt(self.root, 0.95, -0.85, 'N', align='center',
                           scale=0.024, fg=CLR_DIM, sort=S+2)
        self.gear_l = _txt(self.root, 0.91, -0.92, 'L', align='center',
                           scale=0.024, fg=CLR_DIM, sort=S+2)
        self.gear_r = _txt(self.root, 0.99, -0.92, 'R', align='center',
                           scale=0.024, fg=CLR_DIM, sort=S+2)

        # ────────── Annunciators (lower left dashboard) ──────────
        _card(self.root, -0.95, -0.88, 0.22, 0.18, (0.03, 0.04, 0.05, 1), sort=S)
        self.ann_pbrk = _txt(self.root, -0.95, -0.82, 'PARK BRK', align='center',
                             scale=0.020, fg=CLR_DIM, sort=S+2)
        self.ann_sbrk = _txt(self.root, -0.95, -0.87, 'SPDBRK', align='center',
                             scale=0.020, fg=CLR_DIM, sort=S+2)
        self.ann_rev  = _txt(self.root, -0.95, -0.92, 'REVERSER', align='center',
                             scale=0.020, fg=CLR_DIM, sort=S+2)
        self.ann_abrk = _txt(self.root, -0.95, -0.97, 'AUTO BRK', align='center',
                             scale=0.020, fg=CLR_DIM, sort=S+2)

    # ──────────────────────────────────────────────────────────────────
    def show(self):  self.root.show()
    def hide(self):  self.root.hide()

    # ──────────────────────────────────────────────────────────────────
    def update(self, fd):
        airspeed  = fd.airspeed_kt()
        altitude  = fd.altitude_ft()
        agl       = fd.agl_ft()
        heading   = fd.heading_deg()
        vs        = fd.vertical_speed_fpm()
        pitch_deg, roll_deg, _ = fd.attitude_deg()
        on_ground = fd.on_ground()
        gear_pos  = fd.gear_position_norm()
        mach      = fd.mach_number()
        n1_1, n1_2 = fd.n1_percent_both()
        fuel      = fd.fuel_lbs()
        gs_kt     = fd.ground_speed_kt()

        px, pz = self.PX, self.PZ
        nx, nz = self.NX, self.NZ

        # ── PFD attitude ──
        ppd = 0.008   # screen-units per degree of pitch
        ps = pitch_deg * ppd
        self.att_sky.setZ(pz + 0.05 + ps)
        self.att_gnd.setZ(pz - 0.15 + ps)

        for deg, t in self.pitch_labels:
            y = pz - 0.02 + (deg - pitch_deg) * ppd
            if pz - 0.22 < y < pz + 0.20:
                t.setPos(px, y)
                t.setText(f'{deg:+d}' if deg != 0 else '---')
                t.show()
            else:
                t.hide()

        self.roll_txt.setText(f'{roll_deg:+.0f}\xb0')

        # ── Speed tape ──
        self.spd_main.setText(f'{airspeed:.0f}')
        if not on_ground and airspeed < 100:
            self.spd_main['fg'] = CLR_RED
        elif airspeed > 300:
            self.spd_main['fg'] = CLR_AMBER
        else:
            self.spd_main['fg'] = CLR_GREEN

        base_spd = int(round(airspeed / 10.0)) * 10
        sx = px - 0.24
        for i, t in enumerate(self.spd_pool):
            sv = base_spd + (i - 4) * 10
            y = pz + (sv - airspeed) * 0.004
            if pz - 0.23 < y < pz + 0.23 and sv >= 0:
                t.setPos(sx, y); t.setText(str(sv)); t.show()
            else:
                t.hide()

        # V-speeds
        for txt, ref in [(self.v1_txt,145),(self.vr_txt,150),(self.v2_txt,157)]:
            y = pz + (ref - airspeed) * 0.004
            if pz - 0.23 < y < pz + 0.23:
                txt.setPos(sx + 0.06, y); txt.show()
            else:
                txt.hide()

        if mach > 0.4:
            self.mach_txt.setText(f'.{mach:.3f}'[1:]); self.mach_txt.show()
        else:
            self.mach_txt.hide()

        # ── Altitude tape ──
        self.alt_main.setText(f'{altitude:.0f}')
        if not on_ground and agl < 100:    self.alt_main['fg'] = CLR_RED
        elif not on_ground and agl < 500:  self.alt_main['fg'] = CLR_AMBER
        else:                              self.alt_main['fg'] = CLR_GREEN

        base_alt = int(round(altitude / 100.0)) * 100
        ax = px + 0.24
        for i, t in enumerate(self.alt_pool):
            av = base_alt + (i - 4) * 100
            y = pz + (av - altitude) * 0.0004
            if pz - 0.23 < y < pz + 0.23:
                t.setPos(ax, y); t.setText(str(av)); t.show()
            else:
                t.hide()

        # Radio alt
        if not on_ground and agl < 2500:
            self.ra_txt.setText(f'{agl:.0f}')
            self.ra_txt['fg'] = CLR_RED if agl < 50 else (
                CLR_AMBER if agl < 200 else CLR_GREEN)
            self.ra_txt.show()
        else:
            self.ra_txt.hide()

        # ── Heading strip ──
        self.hdg_main.setText(f'{heading:03.0f}')
        base_hdg = int(round(heading / 10.0)) * 10
        for i, t in enumerate(self.hdg_pool):
            hv = (base_hdg + (i - 3) * 10) % 360
            delta = hv - heading
            if delta > 180:  delta -= 360
            if delta < -180: delta += 360
            x = px + delta * 0.008
            if px - 0.19 < x < px + 0.19:
                t.setPos(x, pz - 0.26); t.setText(f'{hv:03.0f}'); t.show()
            else:
                t.hide()

        # ── VS ──
        if abs(vs) > 200:
            self.vs_txt.setText(f'{vs:+.0f}')
            self.vs_txt['fg'] = (CLR_AMBER if abs(vs) > 2000
                                 else CLR_RED if (vs < -1500 and agl < 500
                                                  and not on_ground)
                                 else CLR_GREEN)
            self.vs_txt.show()
        else:
            self.vs_txt.hide()

        # ── FMA ──
        if fd.reverser and on_ground:
            self.fma_thr.setText('REV');  self.fma_thr['fg'] = CLR_AMBER
        elif fd.throttle > 0.85:
            self.fma_thr.setText('TOGA'); self.fma_thr['fg'] = CLR_AMBER
        elif fd.throttle < 0.02:
            self.fma_thr.setText('IDLE'); self.fma_thr['fg'] = CLR_GREEN
        else:
            self.fma_thr.setText('THR');  self.fma_thr['fg'] = CLR_GREEN

        if vs > 500:     self.fma_ver.setText('CLB'); self.fma_ver['fg'] = CLR_GREEN
        elif vs < -500:  self.fma_ver.setText('DES'); self.fma_ver['fg'] = CLR_GREEN
        elif abs(vs)>100:self.fma_ver.setText('VS');  self.fma_ver['fg'] = CLR_GREEN
        else:            self.fma_ver.setText('---'); self.fma_ver['fg'] = CLR_DIM

        # ── ND compass rose ──
        self.nd_hdg.setText(f'{heading:03.0f}\xb0')
        r = 0.20
        for deg, t in self.nd_compass:
            a = math.radians(deg - heading)
            t.setPos(nx + math.sin(a) * r, nz + math.cos(a) * r)

        self.nd_gs.setText(f'GS {gs_kt:.0f}')
        self.nd_tas.setText(f'TAS {airspeed:.0f}')

        # ── ECAM engines ──
        for n1_val, n1t, bart, egtt, fft in [
            (n1_1, self.e1_n1, self.e1_bar, self.e1_egt, self.e1_ff),
            (n1_2, self.e2_n1, self.e2_bar, self.e2_egt, self.e2_ff),
        ]:
            n1t.setText(f'{n1_val:4.1f}')
            n1t['fg'] = CLR_RED if n1_val>95 else CLR_AMBER if n1_val>85 else CLR_GREEN
            filled = int(min(10, max(0, n1_val / 10.0)))
            bart.setText('[' + '=' * filled + ' ' * (10 - filled) + ']')
            bart['fg'] = CLR_GREEN if n1_val < 85 else CLR_AMBER
            egt = 200 + n1_val * 5.5
            egtt.setText(f'EGT {egt:4.0f}')
            egtt['fg'] = CLR_GREEN if egt < 750 else CLR_AMBER
            fft.setText(f'FF {max(0, n1_val * 25):.0f}')

        self.fuel_txt.setText(f'FUEL {fuel:.0f} LBS')

        flap_names = ['UP', '1', '2', '3', 'FULL']
        fi = min(fd.flap_setting, 4)
        self.flap_txt.setText(f'FLAP {flap_names[fi]}')
        flap_lim = [350, 230, 200, 185, 177]
        self.flap_txt['fg'] = CLR_AMBER if airspeed > flap_lim[fi] else CLR_GREEN

        # ── FCU ──
        self.fcu_spd.setText(f'SPD {airspeed:.0f}')
        self.fcu_hdg.setText(f'HDG {heading:03.0f}')
        self.fcu_alt.setText(f'ALT {altitude:.0f}')
        self.fcu_vs.setText(f'V/S {vs:+.0f}')

        # ── Gear ──
        for dot in (self.gear_n, self.gear_l, self.gear_r):
            dot['fg'] = (CLR_GREEN if gear_pos > 0.99
                         else CLR_AMBER if gear_pos > 0.01
                         else CLR_DIM)

        # ── Annunciators ──
        self.ann_pbrk['fg'] = CLR_AMBER if fd.parking_brake else CLR_DIM
        self.ann_sbrk['fg'] = CLR_AMBER if fd.speedbrake > 0.01 else CLR_DIM
        self.ann_rev['fg']  = CLR_RED if (fd.reverser and on_ground) else CLR_DIM
