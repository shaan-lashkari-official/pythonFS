"""
hud.py
------
Text-based HUD with color-coded warnings, radio altitude, flight phase
annunciator, camera mode indicator, and reverse thrust display.
"""

from panda3d.core import TextNode
from direct.gui.DirectGui import DirectFrame
from direct.gui.OnscreenText import OnscreenText


# Color constants
CLR_NORMAL  = (0.2, 1.0, 0.4, 1)
CLR_CAUTION = (1.0, 0.85, 0.15, 1)
CLR_WARNING = (1.0, 0.25, 0.15, 1)
CLR_INFO    = (0.4, 0.85, 1.0, 1)
CLR_DIM     = (0.5, 0.7, 0.5, 1)


class HUD:
    def __init__(self):
        self.left_panel = DirectFrame(
            frameColor=(0.02, 0.06, 0.08, 0.72),
            frameSize=(-1.92, -1.42, 0.56, 0.98),
            pos=(0, 0, 0), relief=None,
        )
        self.right_panel = DirectFrame(
            frameColor=(0.02, 0.06, 0.08, 0.72),
            frameSize=(1.40, 1.92, 0.56, 0.98),
            pos=(0, 0, 0), relief=None,
        )

        # Top-left: primary flight numbers
        self.spd  = self._make(-1.78,  0.90, 'SPD  ---')
        self.alt  = self._make(-1.78,  0.83, 'ALT  ---')
        self.hdg  = self._make(-1.78,  0.76, 'HDG  ---')
        self.vs   = self._make(-1.78,  0.69, 'VS   ---')
        self.gs   = self._make(-1.78,  0.62, 'GS   ---')

        # Top-right: engine + config
        self.n1    = self._make( 1.82,  0.90, 'N1   ---', align='right')
        self.thr   = self._make( 1.82,  0.83, 'THR  ---', align='right')
        self.flaps = self._make( 1.82,  0.76, 'FLAP ---', align='right')
        self.gear  = self._make( 1.82,  0.69, 'GEAR ---', align='right')
        self.brk   = self._make( 1.82,  0.62, 'BRK  ---', align='right')
        self.spbrk = self._make( 1.82,  0.55, 'SPBRK ---', align='right')

        # Camera mode indicator (right panel, dim)
        self.cam_mode = self._make(1.82, 0.48, 'CAM  ---', align='right')

        # Flight phase annunciator (top center)
        self.phase = self._make(0.0, 0.93, '', align='center', scale=0.050)

        # Radio altitude (center-bottom area, large)
        self.ra = self._make(0.0, -0.72, '', align='center', scale=0.060)

        # Gear warning (center)
        self.gear_warn = self._make(0.0, -0.80, '', align='center', scale=0.050)

        # Bottom center: control inputs (bar-ish text)
        self.ctrl = self._make(0.0, -0.90, '', align='center')

        # Bottom-right: yoke mode indicator
        self.yoke = self._make(1.82, -0.90, 'YOKE MOUSE', align='right')

        # Bottom-left: help hint
        self.help = self._make(
            -1.78, -0.95,
            'M mouse  W/S pitch  A/D roll  Q/E rudder  Shift/Ctrl throttle  '
            'F1-F8/C camera  T speedbrake  Space brake  G gear  F/V flaps  O park  P menu  Home reset  Esc quit',
            scale=0.032,
        )

    def _make(self, x, y, text, align='left', scale=0.045):
        a = TextNode.ALeft
        if align == 'right':  a = TextNode.ARight
        if align == 'center': a = TextNode.ACenter
        return OnscreenText(
            text=text, pos=(x, y), scale=scale, fg=CLR_NORMAL,
            align=a, mayChange=True, shadow=(0, 0, 0, 0.7),
            shadowOffset=(0.06, 0.06),
        )

    @staticmethod
    def _detect_phase(fd):
        """Determine current flight phase from physics state."""
        on_ground = fd.on_ground()
        gs = fd.ground_speed_kt()
        agl = fd.agl_ft()
        vs = fd.vertical_speed_fpm()
        gear = fd.gear_down

        if on_ground:
            if gs < 1.0:
                return 'PARKED'
            elif gs < 40:
                return 'TAXI'
            else:
                return 'TAKEOFF'
        else:
            if agl < 50 and vs < -100:
                return 'FLARE'
            elif agl < 500 and gear and vs < -200:
                return 'FINAL'
            elif agl < 3000 and gear and vs < -100:
                return 'APPROACH'
            elif vs < -500:
                return 'DESCENT'
            elif vs > 500:
                return 'CLIMB'
            else:
                return 'CRUISE'

    # ------------------------------------------------------------------
    def update(self, fd, throttle, wheel_brake, park_brake,
               mouse_yoke=True, camera_mode='chase'):
        airspeed = fd.airspeed_kt()
        altitude = fd.altitude_ft()
        agl = fd.agl_ft()
        vs = fd.vertical_speed_fpm()
        n1 = fd.n1_percent()
        on_ground = fd.on_ground()

        # --- Speed display with color coding
        spd_color = CLR_NORMAL
        if not on_ground:
            if airspeed < 100:
                spd_color = CLR_WARNING  # stall
            elif airspeed > 300:
                spd_color = CLR_CAUTION  # overspeed
        self.spd.setText(f'SPD  {airspeed:5.0f} kt')
        self.spd['fg'] = spd_color

        # --- Altitude
        alt_color = CLR_NORMAL
        if not on_ground:
            if agl < 100:
                alt_color = CLR_WARNING
            elif agl < 500:
                alt_color = CLR_CAUTION
        self.alt.setText(f'ALT  {altitude:6.0f} ft')
        self.alt['fg'] = alt_color

        # --- Heading
        self.hdg.setText(f'HDG  {fd.heading_deg():5.1f}\xb0')
        self.hdg['fg'] = CLR_NORMAL

        # --- Vertical speed
        vs_color = CLR_NORMAL
        if abs(vs) > 2000:
            vs_color = CLR_CAUTION
        if vs < -1500 and agl < 500 and not on_ground:
            vs_color = CLR_WARNING
        self.vs.setText(f'VS   {vs:+6.0f} fpm')
        self.vs['fg'] = vs_color

        # --- Ground speed
        self.gs.setText(f'GS   {fd.ground_speed_kt():5.0f} kt')
        self.gs['fg'] = CLR_NORMAL

        # --- N1
        n1_color = CLR_NORMAL
        if n1 > 95:
            n1_color = CLR_WARNING
        elif n1 > 85:
            n1_color = CLR_CAUTION
        self.n1.setText(f'N1   {n1:5.1f}%')
        self.n1['fg'] = n1_color

        # --- Throttle / Reverse
        if fd.reverser and on_ground:
            self.thr.setText(f'REV  {throttle * 100:5.1f}%')
            self.thr['fg'] = CLR_CAUTION
        else:
            self.thr.setText(f'THR  {throttle * 100:5.1f}%')
            self.thr['fg'] = CLR_NORMAL

        # --- Flaps
        flap_names = ['UP', '1', '2', '3', 'FULL']
        self.flaps.setText(f'FLAP {flap_names[fd.flap_setting]}')
        self.flaps['fg'] = CLR_NORMAL

        # --- Gear
        self.gear.setText(f'GEAR {"DOWN" if fd.gear_down else "UP"}')
        self.gear['fg'] = CLR_NORMAL

        # --- Brakes
        if park_brake:
            self.brk.setText('BRK  PARK')
            self.brk['fg'] = CLR_CAUTION
        else:
            self.brk.setText(f'BRK  {wheel_brake * 100:3.0f}%')
            self.brk['fg'] = CLR_NORMAL

        # --- Speedbrake
        self.spbrk.setText(f'SPBRK {fd.speedbrake * 100:3.0f}%')
        self.spbrk['fg'] = CLR_NORMAL

        # --- Camera mode
        cam_labels = {
            'chase': 'CHASE', 'cockpit': 'COCKPIT',
            'pax_left': 'PAX L', 'pax_right': 'PAX R',
            'gear': 'GEAR', 'tail': 'TAIL',
            'tower': 'TOWER', 'topdown': 'TOP DN',
        }
        self.cam_mode.setText(f'CAM  {cam_labels.get(camera_mode, camera_mode.upper())}')
        self.cam_mode['fg'] = CLR_DIM

        # --- Flight phase
        phase = self._detect_phase(fd)
        phase_color = CLR_INFO
        if phase in ('FLARE', 'FINAL'):
            phase_color = CLR_CAUTION
        elif phase == 'TAKEOFF':
            phase_color = CLR_NORMAL
        self.phase.setText(phase)
        self.phase['fg'] = phase_color

        # --- Radio altitude (visible below 2500 ft AGL, airborne only)
        if not on_ground and agl < 2500:
            ra_color = CLR_NORMAL
            if agl < 50:
                ra_color = CLR_WARNING
            elif agl < 200:
                ra_color = CLR_CAUTION
            self.ra.setText(f'{agl:.0f} RA')
            self.ra['fg'] = ra_color
        else:
            self.ra.setText('')

        # --- Gear-up warning (gear up below 1000 ft AGL, airborne)
        if not on_ground and not fd.gear_down and agl < 1000:
            self.gear_warn.setText('GEAR UP!')
            self.gear_warn['fg'] = CLR_WARNING
        else:
            self.gear_warn.setText('')

        # Control bar: crude visualisation of stick position
        def bar(v):
            slots = 11
            idx = int(round((v + 1) / 2 * (slots - 1)))
            idx = max(0, min(slots - 1, idx))
            return '[' + '.' * idx + '*' + '.' * (slots - 1 - idx) + ']'

        self.ctrl.setText(
            f'ELEV {bar(-fd.elevator)}   '
            f'AIL {bar(fd.aileron)}   '
            f'RUD {bar(fd.rudder)}'
        )
        self.yoke.setText('YOKE MOUSE' if mouse_yoke else 'YOKE KBD ONLY')
