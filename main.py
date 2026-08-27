"""
main.py
-------
Panda3D app tying together JSBSim physics, procedural A320, EGLL 27L
scenery, and HUD. Eight camera views (F1-F8), cycled with C.

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
    R               toggle full reverse thrust (only works on ground)
    Space  (hold)   wheel brakes
    O               parking brake toggle
    P               open setup menu / resume flight
    G               gear toggle
    F / V           flaps down / up notch
    Home            reset to threshold
    F1              chase camera (smoothed orbit, RMB pan)
    F2              cockpit camera (fixed forward, g-force shake)
    F3              passenger left wing view
    F4              passenger right wing view
    F5              gear cam (under belly, looking at gear/runway)
    F6              tail cam (from fin top, forward over fuselage)
    F7              tower cam (ATC tower, tracks aircraft)
    F8              top-down camera (+200m above aircraft)
    C               cycle through all 8 camera views
    Esc             quit
"""
import math
from math import sin, cos, radians
import sys
from night_lighting import (
    create_dynamic_night_lights, update_dynamic_night_lights,
    set_night_mode, apply_night_fog, apply_day_fog,
)

from scenery import update_rabbit_lights
from shadow import create_aircraft_shadow, update_aircraft_shadow
from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from direct.gui.DirectGui import (
    DirectFrame, DirectButton, DirectLabel, DirectOptionMenu, DirectSlider,
)
from direct.gui.OnscreenText import OnscreenText
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
    build_ground, build_runway, build_runway_lights,
    build_heathrow_parallel_runway, build_city, build_city_lights,
    add_lighting, update_papi,
)
from hud import HUD
from minimap import Minimap
from audio import AudioSystem


PHYSICS_HZ = 120
PHYSICS_DT = 1.0 / PHYSICS_HZ

# Camera view order for C-key cycling
CAMERA_VIEWS = [
    'chase', 'cockpit', 'pax_left', 'pax_right',
    'gear', 'tail', 'tower', 'topdown',
]


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

        self.loading_panel = DirectFrame(
            frameColor=(0.025, 0.05, 0.07, 1),
            frameSize=(-2, 2, -1.15, 1.15),
        )
        self.loading_panel.setBin('fixed', 100)
        self.loading_title = OnscreenText(
            text='A320 FLIGHT SIM', pos=(0, 0.18), scale=0.09,
            fg=(0.85, 0.95, 1, 1), align=2, mayChange=False,
        )
        self.loading_title.setBin('fixed', 101)
        self.loading_status = OnscreenText(
            text='Preparing Heathrow scenery...', pos=(0, -0.02), scale=0.045,
            fg=(0.55, 0.85, 0.65, 1), align=2, mayChange=True,
        )
        self.loading_status.setBin('fixed', 101)
        self.loading_bar = DirectFrame(
            frameColor=(0.25, 0.75, 0.45, 1),
            frameSize=(-0.65, 0.65, -0.018, 0.018),
            pos=(0, 0, -0.20),
        )
        self.loading_bar.setBin('fixed', 101)
        self._loading_update('Building terrain...', 0.12)

        # --- Scene
        build_ground().reparentTo(self.render)
        self._loading_update('Laying out runways and taxiways...', 0.28)
        build_runway().reparentTo(self.render)
        build_heathrow_parallel_runway().reparentTo(self.render)
        build_runway_lights().reparentTo(self.render)
        build_runway_lights(
            length=3650.0, center_y=1800.0,
            name='northern_runway_lights', prefix='north_',
        ).reparentTo(self.render)

        # Cache light NodePaths once (avoid find() every frame)
        self.rabbit_cache = [
            self.render.find(f'**/rabbit_{i}') for i in range(20)
        ]
        self.papi_cache = [
            self.render.find(f'**/papi_{i}') for i in range(4)
        ]
        self.north_papi_cache = [
            self.render.find(f'**/north_papi_{i}') for i in range(4)
        ]

        self._loading_update('Generating Heathrow airport districts...', 0.52)
        build_city().reparentTo(self.render)
        self.night_pool = create_dynamic_night_lights(self.render, count=12)
        self.city_lights = build_city_lights()
        self.city_lights.reparentTo(self.render)
        self._loading_update('Adding aircraft systems and instruments...', 0.72)
        self.amb_np, self.sun_np = add_lighting(self.render)
        self._loading_update('Preparing flight audio...', 0.84)
        self.audio = AudioSystem(self.loader)

        self._cam_lookat_pos = None   # populated on first frame of chase camera use

        self.shadow = create_aircraft_shadow(self.render)
        # --- Aircraft
        self.plane = build_a320()
        self.plane.reparentTo(self.render)

        # Find animatable nodes once (avoid find() every frame)
        self.n_aileron_l = self.plane.find('**/aileron_left')
        self.n_aileron_r = self.plane.find('**/aileron_right')
        self.n_elevator_l = self.plane.find('**/elevator_left')
        self.n_elevator_r = self.plane.find('**/elevator_right')
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

        # Aircraft exterior light groups (for animation)
        self.n_strobes        = self.plane.find('**/strobes')
        self.n_beacons        = self.plane.find('**/beacons')
        self.n_landing_lights = self.plane.find('**/landing_lights')
        self.n_turnoff_lights = self.plane.find('**/turnoff_lights')
        self.n_taxi_light     = self.plane.find('**/taxi_light')
        self.n_logo_lights    = self.plane.find('**/logo_lights')

        # --- Physics
        self.fd = FlightDynamics(dt=PHYSICS_DT)
        self.sim_started = False

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
                  'o', 'p', 'g', 'f', 'v', 't', 'r', 'm', 'home',
                  'escape', 'f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'c'):
            self.accept(k,        self._key_down, [k])
            self.accept(k + '-up', self._key_up,   [k])
        # Panda3D emits 'lshift' / 'lcontrol' by default — map both
        for k, alias in (('lshift', 'shift'), ('lcontrol', 'control')):
            self.accept(k,        self._key_down, [alias])
            self.accept(k + '-up', self._key_up,   [alias])

        # Right mouse button — camera look-around
        self.accept('mouse3', self._rmb_down)
        self.accept('mouse3-up', self._rmb_up)

        # Camera pan state
        self.rmb_held = False
        self.cam_pan_yaw_deg = 0.0      # + = looking right
        self.cam_pan_pitch_deg = 0.0    # + = looking up
        self._last_mouse_x = None
        self._last_mouse_y = None
        self.cam_pan_sensitivity = 120.0   # degrees per unit of mouse movement

        self.camera_mode = 'chase'    # 'chase' or 'cockpit'
        self.physics_accum = 0.0
        self.camera_motion = Vec3(0, 0, 0)
        self.camera_motion_hpr = Vec3(0, 0, 0)
        self.touchdown_kick = 0.0
        self.crash_kick = 0.0
        self.suspension_offset = 0.0
        self.was_on_ground = self.fd.on_ground()
        self.impact_latched = False

        # Fixed-timestep physics decoupled from render
        self.taskMgr.add(self._update, 'update')

        # Give JSBSim a moment to settle: run a few IC steps
        for _ in range(30):
            self.fd.step()

        self._loading_update('Ready for departure', 1.0)
        self.loading_panel.destroy()
        self.loading_title.destroy()
        self.loading_status.destroy()
        self.loading_bar.destroy()
        self._build_setup_screen()

    def _loading_update(self, message, progress):
        self.loading_status.setText(message)
        self.loading_bar['frameSize'] = (-0.65, 1.3 * progress - 0.65,
                                         -0.018, 0.018)
        self.graphicsEngine.renderFrame()

    def _build_setup_screen(self):
        self.setup_root = self.aspect2d.attachNewNode('flight_setup')
        self.setup_panel = DirectFrame(
            parent=self.setup_root, frameColor=(0.025, 0.05, 0.07, 0.96),
            frameSize=(-1.55, 1.55, -0.92, 0.92), pos=(0, 0, 0),
        )
        DirectLabel(parent=self.setup_root, text='FLIGHT SETUP',
                    scale=0.075, pos=(0, 0, 0.74),
                    text_fg=(0.85, 0.95, 1, 1), frameColor=(0, 0, 0, 0))
        DirectLabel(parent=self.setup_root,
                    text='EGLL HEATHROW  |  A320  |  MANUAL FLIGHT',
                    scale=0.027, pos=(0, 0, 0.64),
                    text_fg=(0.45, 0.78, 0.65, 1), frameColor=(0, 0, 0, 0))

        self.setup_values = {}
        self.spawn_menu = DirectOptionMenu(
            parent=self.setup_root, items=[
                'RUNWAY 27L', 'RUNWAY 27R', 'APPROACH 27L', 'APPROACH 27R'
            ], initialitem=0, scale=0.045, pos=(-1.18, 0, 0.43),
            frameColor=(0.10, 0.18, 0.20, 1),
            text_fg=(0.85, 0.95, 1, 1),
        )
        self._setup_label('SPAWN LOCATION', -1.18, 0.54)
        self._setup_label('WEATHER AND LIGHT', 0.28, 0.54)
        self._add_slider('TIME', 0.0, 24.0, 14.0, 0.28, 0.42, '{:04.1f} h')
        self._add_slider('WIND SPEED', 0.0, 40.0, 8.0, 0.28, 0.20, '{:02.0f} kt')
        self._add_slider('WIND DIRECTION', 0.0, 360.0, 270.0, 0.28, -0.02, '{:03.0f} deg')
        self._add_slider('GUSTS', 0.0, 30.0, 5.0, 0.28, -0.24, '{:02.0f} kt')
        self._add_slider('TURBULENCE', 0.0, 10.0, 1.0, 0.28, -0.46, '{:02.1f}')
        self._add_slider('THERMALS', 0.0, 10.0, 0.0, 0.28, -0.68, '{:02.1f}')

        self._setup_label('GRAPHICS', -1.18, 0.22)
        self.graphics_menu = DirectOptionMenu(
            parent=self.setup_root, items=['ENHANCED', 'PERFORMANCE'],
            initialitem=0, scale=0.045, pos=(-1.18, 0, 0.10),
            frameColor=(0.10, 0.18, 0.20, 1),
            text_fg=(0.85, 0.95, 1, 1),
        )
        self._setup_label('CAMERA', -1.18, -0.06)
        self.camera_menu = DirectOptionMenu(
            parent=self.setup_root, items=[
                'CHASE', 'COCKPIT', 'PAX LEFT', 'PAX RIGHT',
                'GEAR', 'TAIL', 'TOWER', 'TOP DOWN',
            ], initialitem=0,
            scale=0.045, pos=(-1.18, 0, -0.18),
            frameColor=(0.10, 0.18, 0.20, 1),
            text_fg=(0.85, 0.95, 1, 1),
        )
        self._setup_label('FLIGHT ASSIST', -1.18, -0.34)
        DirectLabel(parent=self.setup_root,
                    text='Mouse yoke enabled after launch', scale=0.030,
                    pos=(-1.18, 0, -0.44), text_fg=(0.62, 0.72, 0.72, 1),
                    frameColor=(0, 0, 0, 0), text_align=0)
        is_resume = self.sim_started
        DirectButton(parent=self.setup_root,
                 text='RESUME FLIGHT' if is_resume else 'START FLIGHT',
                 scale=0.055,
                     pos=(-0.32, 0, -0.70),
                     frameColor=(0.18, 0.62, 0.38, 1),
                     text_fg=(1, 1, 1, 1), relief=1,
                 command=(self._resume_flight if is_resume
                      else self._start_configured_flight))

    def _setup_label(self, text, x, z):
        DirectLabel(parent=self.setup_root, text=text, scale=0.030,
                    pos=(x, 0, z), text_fg=(0.55, 0.85, 0.65, 1),
                    frameColor=(0, 0, 0, 0), text_align=0)

    def _add_slider(self, name, minimum, maximum, value, x, z, fmt):
        self._setup_label(name, x, z + 0.055)
        value_label = DirectLabel(parent=self.setup_root, text=fmt.format(value),
                                  scale=0.030, pos=(1.35, 0, z + 0.055),
                                  text_fg=(0.85, 0.95, 1, 1),
                                  frameColor=(0, 0, 0, 0), text_align=2)
        slider = DirectSlider(parent=self.setup_root, range=(minimum, maximum),
                              value=value, pageSize=(maximum - minimum) / 10,
                              scale=0.46, pos=(0.78, 0, z),
                              frameColor=(0.08, 0.13, 0.15, 1),
                              thumb_frameColor=(0.25, 0.75, 0.45, 1),
                              command=self._setup_slider_changed)
        self.setup_values[name] = (slider, value_label, fmt)

    def _setup_slider_changed(self):
        for slider, label, fmt in self.setup_values.values():
            label['text'] = fmt.format(slider.getValue())

    def _start_configured_flight(self):
        spawn_names = ['runway_27L', 'runway_27R', 'approach_27L', 'approach_27R']
        weather = {
            key.lower().replace(' ', '_'): slider.getValue()
            for key, (slider, _, _) in self.setup_values.items()
        }
        spawn_names = {
            'RUNWAY 27L': 'runway_27L',
            'RUNWAY 27R': 'runway_27R',
            'APPROACH 27L': 'approach_27L',
            'APPROACH 27R': 'approach_27R',
        }
        self.fd = FlightDynamics(dt=PHYSICS_DT,
                                 spawn=spawn_names[self.spawn_menu.get()],
                                 weather=weather)
        self.current_spawn = spawn_names[self.spawn_menu.get()]
        self.current_weather = weather.copy()
        self._apply_time_of_day(weather['time'])
        cam_map = {
            'CHASE': 'chase', 'COCKPIT': 'cockpit',
            'PAX LEFT': 'pax_left', 'PAX RIGHT': 'pax_right',
            'GEAR': 'gear', 'TAIL': 'tail',
            'TOWER': 'tower', 'TOP DOWN': 'topdown',
        }
        self.camera_mode = cam_map.get(self.camera_menu.get(), 'chase')
        if self.graphics_menu.get() == 'PERFORMANCE':
            self.render.clearAntialias()
            self.render.getFog().setLinearRange(1200, 18000)
        else:
            self.render.setAntialias(AntialiasAttrib.MMultisample)
            self.render.getFog().setLinearRange(2000, 25000)
        self.sim_started = True
        self.physics_accum = 0.0
        self.setup_root.removeNode()

    def _resume_flight(self):
        """Close the setup overlay and continue the current flight."""
        self.setup_root.removeNode()
        self.sim_started = True

    def _apply_time_of_day(self, hour):
        """Set sky colour, sun direction, lighting colour, and fog from hour.

        Uses simplified solar geometry for EGLL latitude (51.5 N).
        Sun direction is set here — scenery.py no longer hardcodes it.
        """
        # --- Solar geometry (simplified) ---
        lat_rad = math.radians(51.5)  # EGLL latitude
        # Approximate solar declination for mid-summer (~+23.4 deg)
        # A proper sim would use the date; we pick a mild 10 deg declination
        # so the sun is never directly overhead but still gets reasonably high.
        dec_rad = math.radians(10.0)
        hour_angle_rad = math.radians((hour - 12.0) * 15.0)  # 15 deg per hour

        sin_elev = (math.sin(lat_rad) * math.sin(dec_rad) +
                    math.cos(lat_rad) * math.cos(dec_rad) *
                    math.cos(hour_angle_rad))
        elevation_deg = math.degrees(math.asin(max(-1.0, min(1.0, sin_elev))))

        # Azimuth (from north, clockwise)
        cos_elev = math.cos(math.radians(elevation_deg))
        if cos_elev > 0.001:
            cos_az = ((math.sin(dec_rad) -
                        math.sin(lat_rad) * sin_elev) /
                       (math.cos(lat_rad) * cos_elev))
            cos_az = max(-1.0, min(1.0, cos_az))
            azimuth_deg = math.degrees(math.acos(cos_az))
            if hour_angle_rad > 0:
                azimuth_deg = 360.0 - azimuth_deg
        else:
            azimuth_deg = 180.0  # straight south at zenith

        # Set directional light heading + pitch
        # Panda3D HPR: H = heading (CW from -Y in our world), P = pitch down
        sun_heading = azimuth_deg
        sun_pitch = -max(elevation_deg, -5)  # clamp so light doesn't go underground
        self.sun_np.setHpr(sun_heading, sun_pitch, 0)

        # --- Daylight / colour ramps ---
        daylight = max(0.0, math.sin((hour - 6.0) / 12.0 * math.pi))
        dawn = max(0.0, 1.0 - abs(hour - 6.5) / 1.7)
        dusk = max(0.0, 1.0 - abs(hour - 17.5) / 1.7)
        golden_hour = max(dawn, dusk) * daylight

        # Enhanced golden hour: deep warm orange when sun elevation < 5 deg
        low_sun = max(0.0, 1.0 - max(0.0, elevation_deg) / 5.0) if elevation_deg < 5 else 0.0
        golden = max(golden_hour, low_sun * daylight)

        if daylight < 0.08:
            sky = (0.015, 0.025, 0.07)
            fog_color = (0.025, 0.045, 0.10)
            set_night_mode(self.render, enabled=True, pool=self.night_pool,
                           sun_light_np=self.sun_np, ambient_light_np=self.amb_np)
            apply_night_fog(self.render)
        else:
            sky = (0.24 + daylight * 0.30 + golden * 0.22,
                   0.38 + daylight * 0.30 - golden * 0.10,
                   0.50 + daylight * 0.32 - golden * 0.18)
            fog_color = sky
            set_night_mode(self.render, enabled=False, pool=self.night_pool,
                           sun_light_np=self.sun_np, ambient_light_np=self.amb_np)
            apply_day_fog(self.render)
        self.setBackgroundColor(*sky)
        self.render.getFog().setColor(*fog_color)

        # Ambient gets warm fill tint during golden hour
        self.amb_np.node().setColor(
            (0.08 + daylight * 0.32 + golden * 0.12,
             0.10 + daylight * 0.32 + golden * 0.06,
             0.16 + daylight * 0.30 - golden * 0.08, 1)
        )

        # Sun colour: warm orange at low elevation, neutral white above 30 deg
        warmth = max(0.0, 1.0 - max(0.0, elevation_deg) / 30.0)
        self.sun_np.node().setColor(
            (0.12 + daylight * 0.83 + warmth * 0.05,
             0.16 + daylight * 0.72 - warmth * 0.20,
             0.25 + daylight * 0.55 - warmth * 0.35, 1)
        )

    # ------------------------------------------------------------------
    def _rmb_down(self):
        self.rmb_held = True
        # Capture starting mouse position so first frame doesn't jump
        if self.mouseWatcherNode.hasMouse():
            self._last_mouse_x = self.mouseWatcherNode.getMouseX()
            self._last_mouse_y = self.mouseWatcherNode.getMouseY()

    def _rmb_up(self):
        self.rmb_held = False
        self._last_mouse_x = None
        self._last_mouse_y = None
    
    def _key_down(self, k):
        was_down = self.keys.get(k, False)
        self.keys[k] = True
        # Discrete toggles fired on keydown
        if k == 'escape':
            sys.exit(0)
        elif k == 'g':
            self.fd.gear_down = not self.fd.gear_down
        elif k == 'o':
            self.fd.parking_brake = not self.fd.parking_brake
        elif k == 'p':
            if self.sim_started:
                self.sim_started = False
                self._build_setup_screen()
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
            self.cam_pan_yaw_deg = 0.0
            self.cam_pan_pitch_deg = 0.0
            self._cam_lookat_pos = None
        elif k == 'f2':
            self.camera_mode = 'cockpit'
        elif k == 'f3':
            self.camera_mode = 'pax_left'
        elif k == 'f4':
            self.camera_mode = 'pax_right'
        elif k == 'f5':
            self.camera_mode = 'gear'
        elif k == 'f6':
            self.camera_mode = 'tail'
        elif k == 'f7':
            self.camera_mode = 'tower'
        elif k == 'f8':
            self.camera_mode = 'topdown'
        elif k == 'c':
            idx = CAMERA_VIEWS.index(self.camera_mode) if self.camera_mode in CAMERA_VIEWS else -1
            self.camera_mode = CAMERA_VIEWS[(idx + 1) % len(CAMERA_VIEWS)]
            if self.camera_mode == 'chase':
                self.cam_pan_yaw_deg = 0.0
                self.cam_pan_pitch_deg = 0.0
                self._cam_lookat_pos = None
        elif k == 'r' and not was_down:
            self.fd.reverser = not self.fd.reverser

    def _key_up(self, k):
        self.keys[k] = False

    def _reset(self):
        """Rebuild flight dynamics using the current setup preset."""
        self.fd = FlightDynamics(
            dt=PHYSICS_DT,
            spawn=getattr(self, 'current_spawn', 'runway_27L'),
            weather=getattr(self, 'current_weather', {}),
        )
        for _ in range(30):
            self.fd.step()
        self.touchdown_kick = 0.0
        self.crash_kick = 0.0
        self.suspension_offset = 0.0
        self.was_on_ground = self.fd.on_ground()
        self.impact_latched = False
        self.audio.reset_callouts()

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
        if self.rmb_held:
            return None, None
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
        elev_rate = 3 if (self.mouse_yoke and kb_elev == 0.0) else 2
        ail_rate  = 4 if (self.mouse_yoke and kb_ail  == 0.0) else 3
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
        self.plane.setPos(east, north, up + self.suspension_offset)

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
        for n in (self.n_elevator_l, self.n_elevator_r):
            if not n.isEmpty():
                n.setP(self.fd.elevator * 15)
        # Rudder
        if not self.n_rudder.isEmpty():
            self.n_rudder.setH(-self.fd.rudder * 25)
        # Flaps: droop down with setting
        flap_deg = self.fd.flap_setting * 8   # 0..32°
        if not self.n_flap_l.isEmpty():
            self.n_flap_l.setP(flap_deg)
        if not self.n_flap_r.isEmpty():
            self.n_flap_r.setP(flap_deg)

        # Spoilers: pivot at forward/bottom edge, negative P lifts aft edge up
        sp_deg = self.fd.speedbrake * -50.0
        for n in self.n_spoilers:
            if not n.isEmpty():
                n.setP(sp_deg)

        # Gear: smooth retraction animation driven by JSBSim gear-pos-norm.
        # Always visible — rotation handles the visual.
        gear_pos = self.fd.gear_position_norm()  # 1.0 = down, 0.0 = up
        if not self.n_gear_nose.isEmpty():
            # Nose gear rotates forward (pitch) into belly
            nose_retract = (1.0 - gear_pos) * -90
            steer_h = -self.fd.rudder * 25 if self.fd.on_ground() else 0
            self.n_gear_nose.setHpr(steer_h, nose_retract, 0)
        if not self.n_gear_l.isEmpty():
            # Left main gear folds inward (positive roll)
            self.n_gear_l.setR((1.0 - gear_pos) * 90)
        if not self.n_gear_r.isEmpty():
            # Right main gear folds inward (negative roll)
            self.n_gear_r.setR((1.0 - gear_pos) * -90)

    def _animate_lights(self):
        """Flash strobes and beacons, toggle landing/taxi/logo lights."""
        t = globalClock.getRealTime()

        # Strobe: Airbus-style double flash, ~1.09 s cycle.
        # Two quick 50ms flashes separated by a 50ms gap, then dark.
        phase = t % 1.09
        strobe_on = 1.0 if (phase < 0.05 or 0.10 < phase < 0.15) else 0.0
        if not self.n_strobes.isEmpty():
            self.n_strobes.setColorScale(strobe_on, strobe_on,
                                         strobe_on, 1)

        # Beacon: smooth red pulse ~55 flashes/min (0.917 Hz).
        # Cube-power gives a sharper flash-then-dark shape.
        beacon_v = max(0.0, math.sin(t * 2.0 * math.pi * 0.917)) ** 3
        if not self.n_beacons.isEmpty():
            self.n_beacons.setColorScale(beacon_v, beacon_v,
                                         beacon_v, 1)

        # Landing lights: on when gear mostly extended
        gear_pos = self.fd.gear_position_norm()
        ldg = 1.0 if gear_pos > 0.5 else 0.0
        if not self.n_landing_lights.isEmpty():
            self.n_landing_lights.setColorScale(ldg, ldg, ldg, 1)

        # Runway turnoff lights: on when on ground with gear down
        ground_on = 1.0 if (self.fd.on_ground() and gear_pos > 0.8) else 0.0
        if not self.n_turnoff_lights.isEmpty():
            self.n_turnoff_lights.setColorScale(ground_on, ground_on,
                                                ground_on, 1)

        # Taxi / takeoff light: on when on ground with gear down
        if not self.n_taxi_light.isEmpty():
            self.n_taxi_light.setColorScale(ground_on, ground_on,
                                            ground_on, 1)

        # Logo lights: always on (real A320 auto-on with gear/flaps)
        # No animation needed — they stay lit.

    def _update_camera(self,dt):
        forward_g, lateral_g, vertical_g = self.fd.body_acceleration_g()
        vertical_g -= 1.0

        def clamp(value, limit):
            return max(-limit, min(limit, value))

        # A low-pass filter keeps turbulence and physics-step noise subtle.
        crash = self.crash_kick
        impact = self.touchdown_kick + crash
        target_motion = Vec3(
            clamp(-lateral_g * 0.24, 0.24),
            clamp(-forward_g * 0.26, 0.26),
            clamp(-vertical_g * 0.20, 0.20),
        )
        target_motion.y += impact * 0.42
        target_motion.z -= impact * 0.38
        target_hpr = Vec3(
            clamp(-lateral_g * 3.0, 3.0),
            clamp(forward_g * 3.2, 3.2),
            clamp(-lateral_g * 2.1, 2.1),
        )
        target_hpr.y -= impact * 7.0
        blend = min(1.0, ClockObject.getGlobalClock().getDt() * 8.0)
        self.camera_motion += (target_motion - self.camera_motion) * blend
        self.camera_motion_hpr += (target_hpr - self.camera_motion_hpr) * blend

        if self.camera_mode == 'chase':
            # --- Smoothed orbit chase camera with RMB pan
            base_dist = 50.0
            base_height = 12.0

            yaw = radians(self.cam_pan_yaw_deg)
            pitch = radians(self.cam_pan_pitch_deg)
            plane_h = radians(self.plane.getH())
            total_yaw = plane_h + yaw

            horiz_dist = base_dist * cos(pitch)
            vert_offset = base_height + base_dist * sin(pitch)

            target_cam_x = self.plane.getX() - sin(total_yaw) * horiz_dist
            target_cam_y = self.plane.getY() + cos(total_yaw) * horiz_dist
            target_cam_z = self.plane.getZ() + vert_offset

            pos_smoothing = 3.5
            alpha = min(1.0, dt * pos_smoothing)

            current = self.camera.getPos()
            new_x = current.x + (target_cam_x - current.x) * alpha
            new_y = current.y + (target_cam_y - current.y) * alpha
            new_z = current.z + (target_cam_z - current.z) * alpha
            self.camera.setPos(new_x, new_y, new_z)

            if self._cam_lookat_pos is None:
                self._cam_lookat_pos = self.plane.getPos() + Vec3(0, 0, 3)

            target_lookat = self.plane.getPos() + Vec3(0, 0, 3)
            lookat_smoothing = 4.5
            beta = min(1.0, dt * lookat_smoothing)

            lx = self._cam_lookat_pos.x + (target_lookat.x - self._cam_lookat_pos.x) * beta
            ly = self._cam_lookat_pos.y + (target_lookat.y - self._cam_lookat_pos.y) * beta
            lz = self._cam_lookat_pos.z + (target_lookat.z - self._cam_lookat_pos.z) * beta
            self._cam_lookat_pos = Vec3(lx, ly, lz)

            self.camera.lookAt(self._cam_lookat_pos)

        elif self.camera_mode == 'cockpit':
            # Fixed forward with g-force shake
            fwd_offset = self.plane.getQuat().xform(Vec3(0, 16.5, 2.5))
            motion = self.plane.getQuat().xform(self.camera_motion)
            self.camera.setPos(self.plane.getPos() + fwd_offset + motion)
            self.camera.setHpr(self.plane.getHpr() + self.camera_motion_hpr)
            self.camera.setP(self.camera.getP() - 3)

        elif self.camera_mode == 'pax_left':
            # Passenger left window, looking out toward left wing
            offset = self.plane.getQuat().xform(Vec3(-1.6, 2.0, 0.8))
            motion = self.plane.getQuat().xform(self.camera_motion)
            self.camera.setPos(self.plane.getPos() + offset + motion)
            self.camera.setHpr(self.plane.getHpr() + self.camera_motion_hpr)
            self.camera.setH(self.camera.getH() + 90)  # look left

        elif self.camera_mode == 'pax_right':
            # Passenger right window, looking out toward right wing
            offset = self.plane.getQuat().xform(Vec3(1.6, 2.0, 0.8))
            motion = self.plane.getQuat().xform(self.camera_motion)
            self.camera.setPos(self.plane.getPos() + offset + motion)
            self.camera.setHpr(self.plane.getHpr() + self.camera_motion_hpr)
            self.camera.setH(self.camera.getH() - 90)  # look right

        elif self.camera_mode == 'gear':
            # Under belly, looking down at gear/runway
            offset = self.plane.getQuat().xform(Vec3(0, -1, -4))
            motion = self.plane.getQuat().xform(self.camera_motion)
            self.camera.setPos(self.plane.getPos() + offset + motion)
            self.camera.setHpr(self.plane.getHpr() + self.camera_motion_hpr)
            self.camera.setP(self.camera.getP() - 45)  # tilt down toward runway

        elif self.camera_mode == 'tail':
            # From fin top, forward over fuselage
            offset = self.plane.getQuat().xform(Vec3(0, -17, 7.5))
            motion = self.plane.getQuat().xform(self.camera_motion)
            self.camera.setPos(self.plane.getPos() + offset + motion)
            self.camera.setHpr(self.plane.getHpr() + self.camera_motion_hpr)
            self.camera.setP(self.camera.getP() - 8)  # slight downward tilt

        elif self.camera_mode == 'tower':
            # ATC tower — world-fixed position, tracks aircraft
            self.camera.setPos(-800, 250, 55)
            self.camera.lookAt(self.plane.getPos() + Vec3(0, 0, 2))

        elif self.camera_mode == 'topdown':
            # Overhead, heading-aligned, 200m above aircraft
            pos = self.plane.getPos()
            self.camera.setPos(pos.x, pos.y, pos.z + 200)
            self.camera.setHpr(self.plane.getH(), -90, 0)  # straight down
            
    def _update_camera_pan(self):
        if not self.rmb_held or not self.mouseWatcherNode.hasMouse():
            return
        mx = self.mouseWatcherNode.getMouseX()
        my = self.mouseWatcherNode.getMouseY()
        if self._last_mouse_x is None:
            self._last_mouse_x = mx
            self._last_mouse_y = my
            return
        dx = mx - self._last_mouse_x
        dy = my - self._last_mouse_y
        self._last_mouse_x = mx
        self._last_mouse_y = my

        # Accumulate pan angles
        self.cam_pan_yaw_deg   += dx * self.cam_pan_sensitivity
        self.cam_pan_pitch_deg += dy * self.cam_pan_sensitivity

        # Clamp so you can't spin all the way around/underneath
        self.cam_pan_yaw_deg   = max(-180, min(180, self.cam_pan_yaw_deg))
        self.cam_pan_pitch_deg = max(-60,  min(60,  self.cam_pan_pitch_deg))
    # ------------------------------------------------------------------
    def _update(self, task):
        if not self.sim_started:
            return Task.cont
        dt = ClockObject.getGlobalClock().getDt()
        # Cap dt to avoid physics blowup on hitches
        dt = min(dt, 0.1)
        
        self._apply_inputs(dt)
        self._update_camera_pan() 
        self.touchdown_kick *= max(0.0, 1.0 - dt * 4.5)
        self.crash_kick *= max(0.0, 1.0 - dt * 2.8)
        suspension_target = -self.touchdown_kick * 0.16
        suspension_target -= self.crash_kick * 0.42
        self.suspension_offset += (
            suspension_target - self.suspension_offset
        ) * min(1.0, dt * 14.0)

        # Fixed-step physics
        self.physics_accum += dt
        steps = 0
        while self.physics_accum >= PHYSICS_DT and steps < 20:
            was_on_ground = self.fd.on_ground()
            descent_speed_fps = abs(float(
                self.fd.fdm['velocities/v-down-fps']
            ))
            self.fd.step()
            now_on_ground = self.fd.on_ground()
            near_ground_impact = (
                self.fd.gear_down and self.fd.agl_ft() < 25.0 and
                descent_speed_fps > 12.0
            )
            belly_contact = (
                not self.fd.gear_down and self.fd.agl_ft() <= 5.0 and
                self.fd.ground_speed_kt() > 8.0
            )
            if self.fd.agl_ft() > 40.0 and not now_on_ground:
                self.impact_latched = False
            impact_event = (
                not self.impact_latched and
                ((not was_on_ground and now_on_ground) or
                 near_ground_impact or belly_contact)
            )
            if impact_event:
                impact = min(2.5, max(0.0, descent_speed_fps / 8.0))
                if self.fd.gear_down:
                    self.touchdown_kick = max(self.touchdown_kick, impact)
                else:
                    self.crash_kick = max(self.crash_kick, impact)
                    self.fd.begin_belly_contact()
                self.audio.touchdown(impact)
                self.impact_latched = True
            self.was_on_ground = now_on_ground
            self.physics_accum -= PHYSICS_DT
            steps += 1

        self._sync_plane_to_physics()
        self._animate_surfaces()
        self._animate_lights()
        self._update_camera(dt)
        self.audio.update(self.fd)
        update_dynamic_night_lights(self.night_pool, self.plane.getPos())
        
        update_rabbit_lights(self.rabbit_cache, globalClock.getRealTime())

        # PAPI needs aircraft east + altitude in world coords
        pos = self.plane.getPos()
        update_papi(self.papi_cache, pos.x, pos.z)
        update_papi(self.north_papi_cache, pos.x, pos.z, center_y=1800.0)

        self.hud.update(
            self.fd,
            self.fd.throttle,
            self.fd.wheel_brake,
            self.fd.parking_brake,
            mouse_yoke=self.mouse_yoke,
            camera_mode=self.camera_mode,
        )
        east, north, up = self.fd.local_position_enu()
        update_aircraft_shadow(self.shadow, east, north, up, self.fd.heading_deg())
        self.minimap.update(east, north, self.fd.heading_deg())


        return Task.cont


if __name__ == '__main__':
    Sim().run()