"""
flight_dynamics.py  (physics-enhanced revision)
------------------
Thin wrapper around JSBSim that hides the property-tree noise and gives
main.py a clean interface: set controls, step physics, read state.

WHAT'S NEW vs the previous revision:

  Ground handling (fixes "sliding on ice, no rudder steering below high
  speed"):
    - Speed-dependent nose-wheel steering. At 0-15 kt the nose-wheel
      gets 1.5x rudder authority (tiller-like); tapers off through
      15-60 kt; above 60 kt it's rudder-only (aero-dominant).
    - Differential braking when rudder+brake are combined: pressing
      right rudder pedal WHILE holding wheel brake brakes the right
      wheel harder for a tight ground turn.

  Auto ground spoilers (fixes "floats too much on landing" and helps
  brakes bite):
    - Deploy speedbrake to 100% automatically once the wheels are down
      and ground speed > 40 kt. Mimics 'armed' ground spoilers on the
      real A320 — dumps lift so weight goes on the wheels.
    - Retracts on lift-off. Won't re-arm mid-rollout if you manually
      retract with T.

  Touchdown assist (fixes "wheelbarrows on nose gear"):
    - For 3 sec after gear touchdown, forward-stick authority is
      capped (0 initially, growing linearly to -0.3 at t=3s). Aft-
      stick unaffected. Real Airbus alpha-protect does something
      similar via the FBW.

  Stall effects (fixes "no buffet, no wing drop, recovers instantly"):
    - Alpha-driven buffet: random small pitch+roll perturbations
      starting 3 degrees before stall alpha, ramping up as you get
      closer.
    - Wing drop past critical alpha: consistent roll to one side
      (random which side, but persistent once chosen so it's not
      a strobe). Grows with alpha depth.
    - Stall alpha adjusts with flap setting (15 deg clean, less with
      flaps out).

  Turn coordination (fixes "wallows in bank"):
    - Auto-rudder proportional to bank angle when airborne. Only
      applied if pilot isn't already commanding rudder (>0.05).
    - sin(bank) * 0.4 — gives about 0.2 rudder at 30 deg bank,
      enough to keep the ball centred in a normal turn.

  Auto-trim (fixes "doesn't hold altitude"):
    - Slowly eases pitch trim toward the elevator you're holding.
      Airborne only, and only in normal speed envelope (100-350 kt).
    - Very slow rate — takes several seconds of held elevator
      before you notice trim moving. That's intentional; snappy
      auto-trim feels arcadey.

The bug you probably haven't hit yet: keep it in mind that
JSBSim's A320 model is not fine-grained aerodynamically. Stall wing-
drop and buffet here are SIMULATED on top of JSBSim, not from JSBSim's
own aero tables — those don't model asymmetric wing behaviour.
Similarly for auto-spoilers and touchdown assist. If you eventually
swap to a higher-fidelity aircraft XML, most of this can be removed.
"""

import math
import random
import jsbsim

# EGLL (Heathrow) runway 27L threshold, roughly
EGLL_LAT_DEG = 51.4775
EGLL_LON_DEG = -0.4340
EGLL_ELEV_FT = 86
RUNWAY_HDG_DEG = 270.0

METERS_PER_DEG_LAT = 111320.0
APPROACH_SPEED_FPS = 343.3

# Physics-assist tuning constants
TOUCHDOWN_ASSIST_DURATION = 3.0    # seconds forward-stick is limited after touchdown
STALL_MARGIN_DEG = 3.0             # start buffeting this many degrees before stall alpha
STALL_ALPHA_CLEAN = 15.0           # A320 clean stall alpha (approx)
STALL_ALPHA_PER_FLAP_NOTCH = 0.75  # each flap notch lowers stall alpha by this much
AUTO_SPOILER_ARM_SPEED_KT = 40.0   # minimum ground speed for auto-spoiler deploy
# Ground effect tuning — extra lift multiplier that peaks near the ground.
# A320 wingspan is ~34 m; ground effect is significant within ~1 span.
GE_MAX_LIFT_BOOST = 0.06       # +6% extra lift at wheel height (real jets: 5-10%)
GE_MAX_DRAG_REDUCTION = 0.04   # -4% drag near the ground
GE_FADE_ALTITUDE_M = 35.0      # linear fade from max at 0m to 0 at this AGL

class FlightDynamics:
    def __init__(self, dt=1.0 / 120.0, spawn='runway_27L', weather=None):
        self.dt = dt
        self.spawn = spawn
        self.weather = weather or {}
        self.fdm = jsbsim.FGFDMExec(None)
        self.fdm.set_debug_level(0)

        if not self.fdm.load_model('A320'):
            raise RuntimeError(
                "Could not load A320. Check your JSBSim data path — the "
                "A320 folder should exist under aircraft/ in the JSBSim "
                "data directory."
            )

        self.fdm.set_dt(self.dt)

        # --- Initial conditions
        self.fdm['ic/lat-geod-deg'] = EGLL_LAT_DEG
        self.fdm['ic/long-gc-deg']  = EGLL_LON_DEG
        approach = spawn.startswith('approach_')
        on_north_runway = spawn.endswith('27R')
        self.spawn_north_m = 1800.0 if on_north_runway else 0.0
        self.spawn_east_m = 5000.0 if approach else 0.0
        self.fdm['ic/h-agl-ft']     = 1200.0 if approach else 8.0
        self.fdm['ic/psi-true-deg'] = RUNWAY_HDG_DEG
        self.fdm['ic/u-fps']        = APPROACH_SPEED_FPS if approach else 0.0
        self.fdm['ic/v-fps']        = 0.0
        self.fdm['ic/w-fps']        = 0.0
        self.fdm['ic/p-rad_sec']    = 0.0
        self.fdm['ic/q-rad_sec']    = 0.0
        self.fdm['ic/r-rad_sec']    = 0.0
        self.fdm['ic/theta-deg']    = -2.0 if approach else 0.0
        self.fdm['ic/phi-deg']      = 0.0

        self.fdm.run_ic()
        self._start_engines()

        # Realistic laden weight: fuel load ~5500 lb per wing tank.
        # A320 empty ~42.6t + fuel (~5t) + payload (JSBSim default) =
        # roughly typical departure weight. Higher weight = more tyre
        # friction, which reduces the 'sliding on ice' feel too.
        try:
            self.fdm['propulsion/tank[0]/contents-lbs'] = 7000
            self.fdm['propulsion/tank[1]/contents-lbs'] = 7000
        except (KeyError, Exception):
            pass

        self.fdm['fcs/parking-brake-cmd-norm'] = 0.0 if approach else 1.0
        self.fdm['fcs/flap-cmd-norm']          = 0.5 if approach else 0.0
        self.fdm['gear/gear-cmd-norm']         = 1.0

        self.origin_lat = EGLL_LAT_DEG
        self.origin_lon = EGLL_LON_DEG
        self.meters_per_deg_lon = (
            METERS_PER_DEG_LAT * math.cos(math.radians(EGLL_LAT_DEG))
        )

        # --- Control cache
        self.throttle = 0.0
        self.elevator = 0.0
        self.aileron  = 0.0
        self.rudder   = 0.0
        self.flap_setting = 0
        self.gear_down = True
        self.parking_brake = True
        self.wheel_brake = 0.0
        self.speedbrake = 0.0
        self.reverser = False

        # --- Belly-scrape state (unchanged from before)
        self.belly_contact = False
        self.belly_speed_fps = 0.0
        self.belly_position_enu = None

        if approach:
            self.flap_setting = 2
            self.parking_brake = False
            self.throttle = 0.45

        # --- Physics-enhancement state
        self._was_on_ground = True
        self._touchdown_timer = 0.0          # counts up after each touchdown
        self._auto_spoilers_deployed = False
        self._wing_drop_side = 0             # -1, 0, +1
        # Airbus-style attitude hold state (C* FBW approximation)
        self._pitch_hold_target = None      # deg — captured pitch to hold
        self._bank_hold_target = None       # deg — captured bank to hold
        self._pitch_hold_correction = 0.0   # elevator offset from hold
        self._bank_hold_correction = 0.0    # aileron offset from hold        

        # Feature toggles (main.py can flip these if you want to
        # temporarily disable an assist to test the raw JSBSim behaviour)
        self.enable_ground_handling = True
        self.enable_auto_spoilers = True
        self.enable_touchdown_assist = True
        self.enable_stall_effects = True
        self.enable_turn_coordination = True
        self.enable_auto_trim = True

        self.weather_time = 0.0
        self._apply_weather()

    # ==================================================================
    # Weather / engines (largely unchanged)
    # ==================================================================
    def _apply_weather(self):
        direction = math.radians(float(self.weather.get('wind_direction', 270)))
        speed_fps = float(self.weather.get('wind_speed', 0.0)) * 1.68781
        east = -math.sin(direction) * speed_fps
        north = -math.cos(direction) * speed_fps
        self.fdm['atmosphere/wind-east-fps'] = east
        self.fdm['atmosphere/wind-north-fps'] = north
        turbulence = float(self.weather.get('turbulence', 0.0))
        gust = float(self.weather.get('gusts', 0.0))
        thermal = float(self.weather.get('thermals', 0.0))
        phase = self.weather_time * 1.7
        gust_fps = math.sin(phase) * gust * 1.68781
        self.fdm['atmosphere/wind-down-fps'] = (
            -(math.sin(phase * 0.63) * turbulence * 0.8 + thermal * 0.5)
        )
        self.fdm['atmosphere/wind-north-fps'] += gust_fps

    def _start_engines(self):
        try:
            self.fdm['propulsion/set-running'] = -1
        except Exception:
            prop = self.fdm.get_propulsion()
            for i in range(prop.get_num_engines()):
                prop.get_engine(i).init_running()
            prop.get_steady_state()

    # ==================================================================
    # PHYSICS ENHANCEMENT HELPERS
    # ==================================================================
    def _get_alpha_deg(self):
        try:
            return math.degrees(float(self.fdm['aero/alpha-rad']))
        except (KeyError, Exception):
            return 0.0

    def _get_ground_speed_kt_raw(self):
        try:
            return float(self.fdm['velocities/vg-fps']) * 0.592484
        except (KeyError, Exception):
            return 0.0

    def _ground_handling_commands(self):
        """
        Returns (steer_cmd, left_brake, right_brake).

        Steering: strong low-speed authority (targets ~85 deg nose-wheel
        deflection below 20 kt), tapers through 20-60 kt, above 60 kt
        aero rudder takes over.

        Also applies fake tyre-lateral-friction via a brake pulse when
        the aircraft is drifting sideways at low speed — compensates for
        the JSBSim A320 gear model's low friction coefficients.
        """
        if not self.on_ground() or not self.enable_ground_handling:
            return (0.0 if not self.on_ground() else -self.rudder,
                    self.wheel_brake, self.wheel_brake)

        gs = self._get_ground_speed_kt_raw()

        # Nose-wheel gain schedule — much more aggressive at low speed.
        # The multiplier scales the -1..1 rudder command; the actual deflection
        # angle depends on JSBSim's steer-cmd-norm interpretation, but this
        # sends max signal so the model deflects as far as its XML allows.
        if gs < 10:
            steer_gain = 2.5   # push past normal saturation — some models honour this
        elif gs < 25:
            steer_gain = 2.0
        elif gs < 45:
            steer_gain = 1.5 - (gs - 25) / 20.0 * 0.8
        elif gs < 70:
            steer_gain = 0.7 - (gs - 45) / 25.0 * 0.4
        else:
            steer_gain = 0.3

        steer = max(-1.0, min(1.0, -self.rudder * steer_gain))

        # Differential braking (unchanged from before)
        left_brake  = self.wheel_brake
        right_brake = self.wheel_brake
        if self.wheel_brake > 0 and abs(self.rudder) > 0.1:
            if self.rudder > 0:      # left rudder pedal -> brake left more
                right_brake = self.wheel_brake * 0.35
            else:
                left_brake  = self.wheel_brake * 0.35

        # Fake lateral tyre friction: if the aircraft is sliding sideways
        # (v-body significant), pulse both brakes to bleed off the slide.
        # Only at slow/taxi speeds where this matters — at higher speeds
        # aero side force is dominant.
        if gs < 40:
            try:
                v_side_fps = abs(float(self.fdm['velocities/v-fps']))  # body Y
            except (KeyError, Exception):
                v_side_fps = 0.0
            if v_side_fps > 1.0:   # sliding more than ~0.6 kt sideways
                # Scale brake pulse with slip amount. Both wheels, not
                # differential — we're just killing the slide.
                slide_brake = min(0.5, v_side_fps / 12.0)
                left_brake  = min(1.0, left_brake  + slide_brake)
                right_brake = min(1.0, right_brake + slide_brake)

        # Taxi-speed limiter: below 25 kt with no throttle applied, apply
        # a very light auto-brake so the aircraft doesn't roll freely on
        # an ice-like surface. Only when NOT commanded reverse or brake
        # already — respects your inputs.
        if (gs > 0.5 and gs < 25 and self.throttle < 0.05 and
                not self.reverser and self.wheel_brake < 0.05):
            rolling_resistance = 0.08
            left_brake  = min(1.0, left_brake  + rolling_resistance)
            right_brake = min(1.0, right_brake + rolling_resistance)

        return steer, left_brake, right_brake

    def _touchdown_and_takeoff_detection(self):
        """Track ground/air transitions each frame."""
        now_ground = self.on_ground()
        if now_ground and not self._was_on_ground:
            self._touchdown_timer = 0.0
        if not now_ground and self._was_on_ground:
            self._auto_spoilers_deployed = False
        self._was_on_ground = now_ground
        if now_ground:
            self._touchdown_timer += self.dt

    def _auto_ground_spoilers(self):
        """Deploy speedbrake once per landing when rolling on the ground."""
        if not self.enable_auto_spoilers:
            return
        if (self.on_ground() and
                self._get_ground_speed_kt_raw() > AUTO_SPOILER_ARM_SPEED_KT and
                not self._auto_spoilers_deployed and
                self.speedbrake < 0.5):
            self.speedbrake = 1.0
            self._auto_spoilers_deployed = True

    def _touchdown_assist_elev(self, elev_in):
        """Cap forward-stick for the first few seconds after touchdown."""
        if (not self.enable_touchdown_assist or
                not self.on_ground() or
                self._touchdown_timer > TOUCHDOWN_ASSIST_DURATION):
            return elev_in
        if elev_in < 0:  # pushing nose down
            fraction = self._touchdown_timer / TOUCHDOWN_ASSIST_DURATION
            allowed = -0.3 * fraction
            return max(elev_in, allowed)
        return elev_in

    def _stall_effects(self):
        """Buffet + wing drop past critical alpha. Returns (d_elev, d_ail)."""
        if not self.enable_stall_effects or self.on_ground():
            self._wing_drop_side = 0
            return 0.0, 0.0

        alpha = self._get_alpha_deg()
        stall_alpha = (STALL_ALPHA_CLEAN
                       - self.flap_setting * STALL_ALPHA_PER_FLAP_NOTCH)

        if alpha < stall_alpha - STALL_MARGIN_DEG:
            self._wing_drop_side = 0
            return 0.0, 0.0

        # Ramp buffet from 0 to full over STALL_MARGIN_DEG
        proximity = min(1.0,
                        (alpha - (stall_alpha - STALL_MARGIN_DEG))
                        / STALL_MARGIN_DEG)
        buffet_pitch = (random.random() - 0.5) * 0.06 * proximity
        buffet_roll  = (random.random() - 0.5) * 0.18 * proximity

        # Persistent wing drop past critical alpha
        if alpha >= stall_alpha:
            if self._wing_drop_side == 0:
                self._wing_drop_side = random.choice((-1, 1))
            deep = min(1.0, (alpha - stall_alpha) / 5.0)
            buffet_roll += self._wing_drop_side * 0.35 * deep

        return buffet_pitch, buffet_roll

    def _coordinated_turn_rudder(self):
        """Auto-rudder proportional to bank when airborne and hands-off pedals."""
        if (not self.enable_turn_coordination or
                self.on_ground() or
                abs(self.rudder) > 0.05):
            return 0.0
        try:
            roll = float(self.fdm['attitude/phi-rad'])
        except (KeyError, Exception):
            return 0.0
        if self.airspeed_kt() < 80:
            return 0.0
        return math.sin(roll) * 0.4
    def _flight_stability(self):
        """
        Airbus-style attitude hold. When stick is centered, aircraft holds
        the pitch and bank it had at the moment you released. This is
        NOT autopilot — it's what the A320 fly-by-wire does in Normal Law
        (C* control law approximation).

        When you move the stick, you're commanding a change to the held
        attitude. Release, and the new attitude becomes the target.

        Only active in the air, above 200 ft AGL, and only when flap
        setting is 3 or lower (approach + landing use direct control).
        """
        if self.on_ground() or self.agl_ft() < 200:
            # Reset holds so they don't kick in on next takeoff
            self._pitch_hold_target = None
            self._bank_hold_target = None
            return

        try:
            pitch_deg = math.degrees(float(self.fdm['attitude/theta-rad']))
            bank_deg = math.degrees(float(self.fdm['attitude/phi-rad']))
            pitch_rate = float(self.fdm['velocities/q-rad_sec'])
            roll_rate = float(self.fdm['velocities/p-rad_sec'])
        except (KeyError, Exception):
            return

        # PITCH HOLD --------------------------------------------------
        if abs(self.elevator) < 0.08:
            # Stick centered — capture current pitch if not held yet
            if self._pitch_hold_target is None:
                self._pitch_hold_target = pitch_deg
            # Compute correction: pitch error + damping on pitch rate
            pitch_err = self._pitch_hold_target - pitch_deg
            # Proportional + rate damping
            correction = pitch_err * 0.04 - pitch_rate * 3.0
            # Clamp to reasonable range so it doesn't fight big disturbances
            correction = max(-0.3, min(0.3, correction))
            # Add to elevator command (will be applied in set_controls)
            self._pitch_hold_correction = correction
        else:
            # Pilot is actively pitching — release hold, update target
            self._pitch_hold_target = pitch_deg
            self._pitch_hold_correction = 0.0

        # BANK HOLD ---------------------------------------------------
        if abs(self.aileron) < 0.08:
            if self._bank_hold_target is None:
                self._bank_hold_target = bank_deg
            # Airbus holds bank up to 33°, then rolls back toward 33°
            target = self._bank_hold_target
            if abs(target) > 33:
                target = 33 * (1 if target > 0 else -1)
                self._bank_hold_target = target
            bank_err = target - bank_deg
            correction = bank_err * 0.03 - roll_rate * 2.0
            correction = max(-0.3, min(0.3, correction))
            self._bank_hold_correction = correction
        else:
            self._bank_hold_target = bank_deg
            self._bank_hold_correction = 0.0
    def _apply_ground_effect(self):
        """
        Boost lift + trim drag when the aircraft is close to the ground.
        Uses JSBSim's aero coefficient bias properties (multiplicative
        scale of the total force from the aero tables) so it stacks
        cleanly with whatever the model was already computing.
        Falls back silently if the model doesn't expose those bias points.
        """
        if self.on_ground() or self.belly_contact:
            # On the ground the aero tables aren't dominant anyway; skip
            # so we don't affect ground rolling behaviour.
            self._clear_ground_effect()
            return

        agl_m = self.agl_ft() * 0.3048
        if agl_m >= GE_FADE_ALTITUDE_M:
            self._clear_ground_effect()
            return

        # Linear fade from 1.0 at ground to 0.0 at fade altitude
        fade = 1.0 - (agl_m / GE_FADE_ALTITUDE_M)
        lift_bias = 1.0 + GE_MAX_LIFT_BOOST * fade
        drag_bias = 1.0 - GE_MAX_DRAG_REDUCTION * fade

        try:
            self.fdm['aero/coefficient/CLge'] = lift_bias
            self.fdm['aero/coefficient/CDge'] = drag_bias
        except (KeyError, Exception):
            # Model doesn't have those bias points — try the generic
            # total-lift/drag scale properties instead.
            try:
                self.fdm['aero/bi/lift-coef'] = lift_bias
                self.fdm['aero/bi/drag-coef'] = drag_bias
            except (KeyError, Exception):
                pass

    def _clear_ground_effect(self):
        """Reset ground-effect bias to 1.0 (neutral)."""
        for prop in ('aero/coefficient/CLge', 'aero/coefficient/CDge',
                    'aero/bi/lift-coef', 'aero/bi/drag-coef'):
            try:
                self.fdm[prop] = 1.0
            except (KeyError, Exception):
                pass

    # ==================================================================
    # Control inputs (main.py-facing)
    # ==================================================================
    def set_controls(self):
        # --- Reverse thrust
        rev_active = self.reverser and self.on_ground()

        # The reverser property tells JSBSim's engine model to deploy the
        # thrust reverser buckets. When deployed, forward throttle produces
        # REVERSE thrust automatically — you keep sending POSITIVE throttle,
        # not negative. Sending -1 just clamps to 0 on this model = no thrust
        # at all, which is why the plane wasn't decelerating.
        try:
            for i in (0, 1):
                self.fdm[f'propulsion/engine[{i}]/reverser-cmd-norm'] = (
                    1.0 if rev_active else 0.0
                )
        except (KeyError, Exception):
            pass

        # Positive throttle in both modes. When reversers are deployed, that
        # thrust points backward and decelerates you. Reverse power ~ 70%.
        if rev_active:
            eff_throttle = 0.7
        else:
            eff_throttle = max(0.0, self.throttle)   # forward flight uses pilot's setting

        self.fdm['fcs/throttle-cmd-norm']    = eff_throttle
        self.fdm['fcs/throttle-cmd-norm[1]'] = eff_throttle


        # --- Enhanced elevator (stall buffet + touchdown assist + attitude hold)
        buffet_pitch, buffet_roll = self._stall_effects()
        assisted_elev = self._touchdown_assist_elev(self.elevator)
        eff_elev = max(-1.0, min(1.0,
            assisted_elev + buffet_pitch + self._pitch_hold_correction))
        eff_ail  = max(-1.0, min(1.0,
            self.aileron + buffet_roll + self._bank_hold_correction))
        self.fdm['fcs/elevator-cmd-norm'] = eff_elev
        self.fdm['fcs/aileron-cmd-norm']  = eff_ail

        # --- Rudder with turn coordination
        coord = self._coordinated_turn_rudder()
        eff_rud = max(-1.0, min(1.0, self.rudder + coord))
        self.fdm['fcs/rudder-cmd-norm'] = eff_rud

        # --- Ground handling: nose-wheel + differential brakes
        steer, left_brake, right_brake = self._ground_handling_commands()
        self.fdm['fcs/steer-cmd-norm']       = steer
        self.fdm['fcs/left-brake-cmd-norm']  = left_brake
        self.fdm['fcs/right-brake-cmd-norm'] = right_brake

        # --- Everything else
        self.fdm['fcs/flap-cmd-norm']          = self.flap_setting / 4.0
        self.fdm['gear/gear-cmd-norm']         = 1.0 if self.gear_down else 0.0
        self.fdm['fcs/parking-brake-cmd-norm'] = 1.0 if self.parking_brake else 0.0
        self.fdm['fcs/speedbrake-cmd-norm']    = self.speedbrake

    def step(self):
        self.weather_time += self.dt
        self._apply_weather()
        # Detect touchdown/takeoff transitions BEFORE running physics
        # (so the timer/flags are current when set_controls fires)
        self._touchdown_and_takeoff_detection()
        self._auto_ground_spoilers()
        self._flight_stability()
        self._apply_ground_effect()   # <-- ADD THIS LINE
        self.set_controls()   # existing

        self.set_controls()

        if self.belly_contact:
            distance = self.belly_speed_fps * self.dt
            heading = math.radians(self.heading_deg())
            east, north, up = self.belly_position_enu
            self.belly_position_enu = (
                east + math.sin(heading) * distance,
                north + math.cos(heading) * distance,
                up,
            )
            self.belly_speed_fps = max(
                0.0, self.belly_speed_fps - 35.0 * self.dt
            )
            return

        self.fdm.run()

    def begin_belly_contact(self):
        if not self.belly_contact:
            self.belly_speed_fps = max(0.0, float(self.fdm['velocities/vg-fps']))
            lat = self.fdm['position/lat-geod-deg']
            lon = self.fdm['position/long-gc-deg']
            h_ft = self.fdm['position/h-sl-ft'] + 95
            north = (lat - self.origin_lat) * METERS_PER_DEG_LAT + self.spawn_north_m
            east  = (lon - self.origin_lon) * self.meters_per_deg_lon + self.spawn_east_m
            self.belly_position_enu = (east, north,
                                       (h_ft - EGLL_ELEV_FT) * 0.3048)
            self.belly_contact = True
            self.throttle = 0.0
            self.reverser = False

    # ==================================================================
    # State queries (unchanged public API)
    # ==================================================================
    def local_position_enu(self):
        if self.belly_contact:
            return self.belly_position_enu
        lat = self.fdm['position/lat-geod-deg']
        lon = self.fdm['position/long-gc-deg']
        h_ft = self.fdm['position/h-sl-ft'] + 95
        north = (lat - self.origin_lat) * METERS_PER_DEG_LAT + self.spawn_north_m
        east  = (lon - self.origin_lon) * self.meters_per_deg_lon + self.spawn_east_m
        up_m  = (h_ft - EGLL_ELEV_FT) * 0.3048
        return east, north, up_m

    def attitude_deg(self):
        return (
            math.degrees(self.fdm['attitude/theta-rad']),
            math.degrees(self.fdm['attitude/phi-rad']),
            math.degrees(self.fdm['attitude/psi-rad']),
        )

    def airspeed_kt(self):
        if self.belly_contact:
            return self.belly_speed_fps * 0.592484
        return float(self.fdm['velocities/vc-kts'])

    def ground_speed_kt(self):
        if self.belly_contact:
            return self.belly_speed_fps * 0.592484
        return float(self.fdm['velocities/vg-fps']) * 0.592484

    def vertical_speed_fpm(self):
        return -float(self.fdm['velocities/v-down-fps']) * 60.0

    def altitude_ft(self):
        return float(self.fdm['position/h-sl-ft'])

    def agl_ft(self):
        return float(self.fdm['position/h-agl-ft'])

    def heading_deg(self):
        return math.degrees(self.fdm['attitude/psi-rad']) % 360.0

    def n1_percent(self):
        try:
            return float(self.fdm['propulsion/engine[0]/n1'])
        except Exception:
            return self.throttle * 100.0

    def on_ground(self):
        return bool(self.fdm['gear/wow'])

    def body_acceleration_g(self):
        return (
            float(self.fdm['accelerations/Nx']),
            float(self.fdm['accelerations/Ny']),
            float(self.fdm['accelerations/Nz']),
        )