"""
hud.py
------
Text-based HUD in the corners. Not a real PFD — that's a big project on
its own (attitude tape, speed tape, altitude tape, ILS diamonds, FMA).
This just gets you the numbers pilots and simmers actually watch.
"""

from panda3d.core import TextNode
from direct.gui.OnscreenText import OnscreenText


class HUD:
    def __init__(self):
        # Top-left: primary flight numbers
        self.spd  = self._make(-1.75,  0.90, 'SPD  ---')
        self.alt  = self._make(-1.75,  0.83, 'ALT  ---')
        self.hdg  = self._make(-1.75,  0.76, 'HDG  ---')
        self.vs   = self._make(-1.75,  0.69, 'VS   ---')
        self.gs   = self._make(-1.75,  0.62, 'GS   ---')

        # Top-right: engine + config
        self.n1    = self._make( 1.15,  0.90, 'N1   ---', align='right')
        self.thr   = self._make( 1.15,  0.83, 'THR  ---', align='right')
        self.flaps = self._make( 1.15,  0.76, 'FLAP ---', align='right')
        self.gear  = self._make( 1.15,  0.69, 'GEAR ---', align='right')
        self.brk   = self._make( 1.15,  0.62, 'BRK  ---', align='right')
        self.spbrk = self._make( 1.15,  0.55, 'SPBRK ---', align='right')

        # Bottom center: control inputs (bar-ish text)
        self.ctrl = self._make(0.0, -0.90, '', align='center')

        # Bottom-right: yoke mode indicator
        self.yoke = self._make(1.15, -0.90, 'YOKE MOUSE', align='right')

        # Bottom-left: help hint
        self.help = self._make(
            -1.75, -0.95,
            'Mouse=yoke  M=toggle  W/S=pitch  A/D=roll  Q/E=rudder  '
            'Shift/Ctrl=throttle  H/J=speedbrake  B=brake  G=gear  '
            'F/V=flaps  P=park brake  R=reset  Esc=quit',
            scale=0.030,
        )

    def _make(self, x, y, text, align='left', scale=0.045):
        a = TextNode.ALeft
        if align == 'right':  a = TextNode.ARight
        if align == 'center': a = TextNode.ACenter
        return OnscreenText(
            text=text, pos=(x, y), scale=scale, fg=(0.2, 1.0, 0.4, 1),
            align=a, mayChange=True, shadow=(0, 0, 0, 0.7),
            shadowOffset=(0.06, 0.06),
        )

    # ------------------------------------------------------------------
    def update(self, fd, throttle, wheel_brake, park_brake, mouse_yoke=True):
        self.spd.setText(f'SPD  {fd.airspeed_kt():5.0f} kt')
        self.alt.setText(f'ALT  {fd.altitude_ft():6.0f} ft')
        self.hdg.setText(f'HDG  {fd.heading_deg():5.1f}\xb0')
        self.vs .setText(f'VS   {fd.vertical_speed_fpm():+6.0f} fpm')
        self.gs .setText(f'GS   {fd.ground_speed_kt():5.0f} kt')

        self.n1   .setText(f'N1   {fd.n1_percent():5.1f}%')
        self.thr  .setText(f'THR  {throttle * 100:5.1f}%')
        flap_names = ['UP', '1', '2', '3', 'FULL']
        self.flaps.setText(f'FLAP {flap_names[fd.flap_setting]}')
        self.gear .setText(f'GEAR {"DOWN" if fd.gear_down else "UP"}')
        self.brk  .setText(
            f'BRK  {"PARK" if park_brake else f"{wheel_brake*100:3.0f}%"}'
        )
        self.spbrk.setText(f'SPBRK {fd.speedbrake*100:3.0f}%')

        # Control bar: crude visualisation of stick position
        def bar(v):
            # v in -1..1 -> 11-char bar with * at position
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