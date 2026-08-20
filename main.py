"""
main.py
-------
Panda3D app tying together JSBSim physics, procedural A320, EGLL 27L
scenery, and HUD. Two camera modes: chase (F1) and cockpit-ish (F2).

Run:
    python main.py

Controls:
    Mouse           yoke — X = aileron, Y = elevator (mouse-down = pull back)
    M               toggle mouse yoke on/off
    W / S           elevator (nose down / nose up)  -- overrides mouse
    A / D           roll left / right               -- overrides mouse
    Q / E           rudder left / right
    Left Shift/Ctrl throttle up / down
    T               speedbrake toggle (full deploy / stow)
    R  (hold)       reverse thrust (only works on ground)
    Space  (hold)   wheel brakes
    P               parking brake toggle
    G               gear toggle
    F / V           flaps down / up notch
    Home            reset to threshold
    F1 / F2         camera: chase / cockpit
    Esc             quit
"""

import math
import sys

from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from panda3d.core import (
    Vec3, Point3, WindowProperties, ClockObject, AntialiasAttrib,
    Fog, loadPrcFileData,
)

# Slightly larger default window and disable Panda's pixel-perfect vsync
# jitter (helps physics feel smoother during dev). Comment out if you prefer.
loadPrcFileData('', 'window-title Basic A320 Sim - EGLL 27L')
loadPrcFileData('', 'win-size 1400 900')
loadPrcFileData('', 'sync-video true')
loadPrcFileData('', 'framebuffer-multisample 1')
loadPrcFileData('', 'multisamples 4')

from flight_dynamics import FlightDynamics, RUNWAY_HDG_DEG
from plane_model import build_a320
from scenery import (
    build_ground, build_runway, build_runway_lights, build_city,
    add_lighting, update_papi,
)
from hud import HUD
from minimap import Minimap


PHYSICS_HZ = 120
PHYSICS_DT = 1.0 / PHYSICS_HZ


class Sim(ShowBase):
    def __init__(self):
        ShowBase.__init__(self)

        # --- Rendering niceties
        self.render.setAntialias(AntialiasAttrib.MMultisample)
        self.setBackgroundColor(0.55, 0.72, 0.88)   # sky blue
        fog = Fog('distanceFog')
        fog.setColor(0.55, 0.72, 0.88)
        fog.setLinearRange(2000, 25000)
        self.render.setFog(fog)

        self.disableMouse()   # we drive the camera manually

        # --- Scene
        build_ground().reparentTo(self.render)
        build_runway().reparentTo(self.render)
        build_runway_lights().reparentTo(self.render)
        build_city().reparentTo(self.render)
        add_lighting(self.render)

        # --- Aircraft
        self.plane = build_a320()
        self.plane.reparentTo(self.render)

        # Find animatable nodes once (avoid find() every frame)
        self.n_aileron_l = self.plane.find('**/aileron_left')
        self.n_aileron_r = self.plane.find('**/aileron_right')
        self.n_elevator  = self.plane.find('**/elevator')
        self.n_rudder    = self.plane.find('**/rudder')
        self.n_flap_l    = self.plane.find('**/flap_left')
        self.n_flap_r    = self.plane.find('**/flap_right')
        self.n_spoilers  = [
            self.plane.find('**/spoiler_left_1'),
            self.plane.find('**/spoiler_left_2'),
            self.plane.find('**/spoiler_right_1'),
            self.plane.find('**/spoiler_right_2'),
        ]
        self.n_gear_nose = self.plane.find('**/gear_nose')
        self.n_gear_l    = self.plane.find('**/gear_left')
        self.n_gear_r    = self.plane.find('**/gear_right')

        # --- Physics
        self.fd = FlightDynamics(dt=PHYSICS_DT)

        # --- HUD
        self.hud = HUD()

        # --- Minimap (top-right, 8km viewing radius, north-up)
        self.minimap = Minimap(self.aspect2d, size=0.5,
                               center=(1.03, 0.60), view_radius_m=8000)

        # --- Input state
        self.mouse_yoke = True     # M to toggle
        self.mouse_deadzone = 0.08
        self.mouse_sensitivity = 1.1

        self.keys = {}
        for k in ('w', 's', 'a', 'd', 'q', 'e', 'shift', 'control', 'space',
                  'p', 'g', 'f', 'v', 't', 'r', 'm', 'home',
                  'escape', 'f1', 'f2'):
            self.accept(k,        self._key_down, [k])
            self.accept(k + '-up', self._key_up,   [k])
        # Panda3D emits 'lshift' / 'lcontrol' by default — map both
        for k, alias in (('lshift', 'shift'), ('lcontrol', 'control')):
            self.accept(k,        self._key_down, [alias])
            self.accept(k + '-up', self._key_up,   [alias])

        self.camera_mode = 'chase'    # 'chase' or 'cockpit'
        self.physics_accum = 0.0

        # Fixed-timestep physics decoupled from render
        self.taskMgr.add(self._update, 'update')

        # Give JSBSim a moment to settle: run a few IC steps
        for _ in range(30):
            self.fd.step()

    # ------------------------------------------------------------------
    def _key_down(self, k):
        self.keys[k] = True
        # Discrete toggles fired on keydown
        if k == 'escape':
            sys.exit(0)
        elif k == 'g':
            self.fd.gear_down = not self.fd.gear_down
        elif k == 'p':
            self.fd.parking_brake = not self.fd.parking_brake
        elif k == 'f':
            self.fd.flap_setting = min(4, self.fd.flap_setting + 1)
        elif k == 'v':
            self.fd.flap_setting = max(0, self.fd.flap_setting - 1)
        elif k == 't':
            # Speedbrake toggle: if any deployment, stow; otherwise deploy full
            self.fd.speedbrake = 0.0 if self.fd.speedbrake > 0.01 else 1.0
        elif k == 'home':
            self._reset()
        elif k == 'm':
            self.mouse_yoke = not self.mouse_yoke
        elif k == 'f1':
            self.camera_mode = 'chase'
        elif k == 'f2':
            self.camera_mode = 'cockpit'

    def _key_up(self, k):
        self.keys[k] = False

    def _reset(self):
        """Rebuild flight dynamics fresh at threshold."""
        self.fd = FlightDynamics(dt=PHYSICS_DT)
        for _ in range(30):
            self.fd.step()

    # ------------------------------------------------------------------
    def _read_mouse_yoke(self):
        """
        Return (elevator_target, aileron_target) from mouse position,
        or (None, None) if the mouse isn't usable this frame.

        Panda3D's mouseX / mouseY are in [-1, +1] relative to the window.
        mouseY = +1 at the top of the screen.
        Yoke convention: mouse UP on screen = push stick forward = nose
        DOWN = negative elevator in our sign scheme. So elevator = -mouseY.
        Mouse RIGHT = right roll = positive aileron. Aileron = mouseX.
        """
        if not self.mouseWatcherNode.hasMouse():
            return None, None
        mx = self.mouseWatcherNode.getMouseX()
        my = self.mouseWatcherNode.getMouseY()

        def shape(v):
            # Deadzone + soft curve so small movements are gentle
            dz = self.mouse_deadzone
            if abs(v) < dz:
                return 0.0
            sign = 1.0 if v > 0 else -1.0
            v = (abs(v) - dz) / (1.0 - dz)   # 0..1 outside deadzone
            v = v * v                         # quadratic curve for finesse
            return max(-1.0, min(1.0, sign * v * self.mouse_sensitivity))

        return shape(my), shape(mx)

    def _apply_inputs(self, dt):
        """Continuous inputs (mouse + held keys) → JSBSim control values."""
        k = self.keys

        # --- Elevator target: keyboard overrides, else mouse, else zero
        kb_elev = 0.0
        if k.get('w'): kb_elev -= 1.0
        if k.get('s'): kb_elev += 1.0

        # --- Aileron target: same idea
        kb_ail = 0.0
        if k.get('d'): kb_ail += 1.0
        if k.get('a'): kb_ail -= -1.0

        mouse_elev, mouse_ail = (None, None)
        if self.mouse_yoke:
            mouse_elev, mouse_ail = self._read_mouse_yoke()

        target_elev = kb_elev if kb_elev != 0.0 else (
            mouse_elev if mouse_elev is not None else 0.0
        )
        target_ail = kb_ail if kb_ail != 0.0 else (
            mouse_ail if mouse_ail is not None else 0.0
        )

        # Rate-limit toward target so inputs feel less twitchy. Mouse is
        # already smooth, so allow a snappier response when mouse-driven.
        elev_rate = 8 if (self.mouse_yoke and kb_elev == 0.0) else 4
        ail_rate  = 10 if (self.mouse_yoke and kb_ail  == 0.0) else 6
        self.fd.elevator += (target_elev - self.fd.elevator) * min(1, dt * elev_rate)
        self.fd.aileron  += (target_ail  - self.fd.aileron)  * min(1, dt * ail_rate)

        # Rudder
        target_rud = 0.0
        if k.get('e'): target_rud -= 1.0
        if k.get('q'): target_rud += 1.0
        self.fd.rudder += (target_rud - self.fd.rudder) * min(1, dt * 5)

        # Throttle
        if k.get('shift'):
            self.fd.throttle = min(1.0, self.fd.throttle + 0.4 * dt)
        if k.get('control'):
            self.fd.throttle = max(0.0, self.fd.throttle - 0.4 * dt)

        # Wheel brakes (hold SPACE)
        self.fd.wheel_brake = 1.0 if k.get('space') else 0.0

        # Reverse thrust (hold R) — only effective on ground
        self.fd.reverser = bool(k.get('r'))

        # Auto-center only when there's genuinely no input from either
        # source (mouse-driven axes settle to the mouse position, they
        # don't need extra centering).
        if kb_elev == 0.0 and mouse_elev in (None, 0.0):
            self.fd.elevator *= max(0.0, 1.0 - dt * 1.5)
        if kb_ail == 0.0 and mouse_ail in (None, 0.0):
            self.fd.aileron *= max(0.0, 1.0 - dt * 3)
        if target_rud == 0.0:
            self.fd.rudder *= max(0.0, 1.0 - dt * 3)

    # ------------------------------------------------------------------
    def _sync_plane_to_physics(self):
        """Copy JSBSim state → Panda3D aircraft NodePath."""
        east, north, up = self.fd.local_position_enu()
        # Our runway world uses +X east, +Y north. Threshold is at origin.
        self.plane.setPos(east, north, up)

        pitch_deg, roll_deg, hdg_deg = self.fd.attitude_deg()
        # Panda3D HPR: H = heading (0 = -Y, CCW). JSBSim psi = 0 (N), CW.
        # Our world +Y = north, so heading 0 → aircraft nose along +Y → H=180.
        # heading 90 (east) → nose along +X → H=90. So H = 180 - psi_deg.
        h = (-hdg_deg) % 360.0
        # JSBSim phi: right-wing-down positive. Panda R: (with our HPR) roll
        # sign that "looks right" is -phi (verify visually and flip if needed).
        self.plane.setHpr(h, pitch_deg, roll_deg)

    def _animate_surfaces(self):
        """Deflect control surfaces so you can see inputs on the model."""
        # Ailerons: opposite deflection
        if not self.n_aileron_l.isEmpty():
            self.n_aileron_l.setR( self.fd.aileron * 20)
        if not self.n_aileron_r.isEmpty():
            self.n_aileron_r.setR(-self.fd.aileron * 20)
        # Elevator: single node
        if not self.n_elevator.isEmpty():
            self.n_elevator.setP(self.fd.elevator * 15)
        # Rudder
        if not self.n_rudder.isEmpty():
            self.n_rudder.setH(self.fd.rudder * 25)
        # Flaps: droop down with setting
        flap_deg = self.fd.flap_setting * 8   # 0..32°
        if not self.n_flap_l.isEmpty():
            self.n_flap_l.setP(-flap_deg)
        if not self.n_flap_r.isEmpty():
            self.n_flap_r.setP(-flap_deg)

        # Spoilers: pitch upward with speedbrake command (0..50°)
        sp_deg = self.fd.speedbrake * 50.0
        for n in self.n_spoilers:
            if not n.isEmpty():
                n.setP(sp_deg)

        # Gear: hide when up (simple placeholder — real animation is a big job)
        vis = self.fd.gear_down
        for n in (self.n_gear_nose, self.n_gear_l, self.n_gear_r):
            if n.isEmpty():
                continue
            if vis:
                n.show()
            else:
                n.hide()

    def _update_camera(self):
        if self.camera_mode == 'chase':
            # 40m behind and 10m above the aircraft, looking at it
            offset = self.plane.getQuat().xform(Vec3(0, -50, 12))
            cam_pos = self.plane.getPos() + offset
            self.camera.setPos(cam_pos)
            self.camera.lookAt(self.plane, Point3(0, 0, 3))
        else:  # cockpit-ish: at nose, looking forward with plane
            fwd_offset = self.plane.getQuat().xform(Vec3(0, 16.5, 2.5))
            self.camera.setPos(self.plane.getPos() + fwd_offset)
            self.camera.setHpr(self.plane.getHpr())
            # Nudge pitch down a touch so horizon sits naturally
            self.camera.setP(self.camera.getP() - 3)

    # ------------------------------------------------------------------
    def _update(self, task):
        dt = ClockObject.getGlobalClock().getDt()
        # Cap dt to avoid physics blowup on hitches
        dt = min(dt, 0.1)

        self._apply_inputs(dt)

        # Fixed-step physics
        self.physics_accum += dt
        steps = 0
        while self.physics_accum >= PHYSICS_DT and steps < 20:
            self.fd.step()
            self.physics_accum -= PHYSICS_DT
            steps += 1

        self._sync_plane_to_physics()
        self._animate_surfaces()
        self._update_camera()

        # PAPI needs aircraft east + altitude in world coords
        pos = self.plane.getPos()
        update_papi(self.render, pos.x, pos.z)

        self.hud.update(
            self.fd,
            self.fd.throttle,
            self.fd.wheel_brake,
            self.fd.parking_brake,
            mouse_yoke=self.mouse_yoke,
        )
        # Minimap: aircraft east/north come from local ENU already computed
        east, north, _ = self.fd.local_position_enu()
        self.minimap.update(east, north, self.fd.heading_deg())
        return Task.cont


if __name__ == '__main__':
    Sim().run()