"""
flight_dynamics.py
------------------
Thin wrapper around JSBSim that hides the property-tree noise and gives
main.py a clean interface: set controls, step physics, read state.

JSBSim ships an A320 model in its aircraft data. We initialise it on the
27L threshold at EGLL (Heathrow), engines running, brakes on.

Coordinate conventions:
  JSBSim body axes: X forward, Y right, Z down (standard aerospace)
  JSBSim Euler: phi = roll (right-wing-down +), theta = pitch (nose-up +),
                psi = heading (0 = north, clockwise from above)
  We convert to a local ENU (East-North-Up) frame for rendering. Origin
  is the initial lat/lon; a flat-earth approximation is fine within a few
  km of the airport.
"""

import math
import jsbsim

# EGLL (Heathrow) runway 27L threshold, roughly
EGLL_LAT_DEG = 51.4775
EGLL_LON_DEG = -0.4340
EGLL_ELEV_FT = 83.0
RUNWAY_HDG_DEG = 270.0  # 27L points west

# Earth radius for flat-earth conversion (meters per degree)
METERS_PER_DEG_LAT = 111320.0


class FlightDynamics:
    def __init__(self, dt=1.0 / 120.0):
        self.dt = dt
        self.fdm = jsbsim.FGFDMExec(None)   # None = use bundled aircraft data
        self.fdm.set_debug_level(0)

        # Load A320. If your JSBSim install spells it differently, try
        # 'a320' or check <jsbsim-data>/aircraft/ for the exact folder name.
        if not self.fdm.load_model('A320'):
            raise RuntimeError(
                "Could not load A320. Check your JSBSim data path — the "
                "A320 folder should exist under aircraft/ in the JSBSim "
                "data directory."
            )

        self.fdm.set_dt(self.dt)

        # --- Initial conditions: on runway, engines off (we start them below)
        self.fdm['ic/lat-geod-deg'] = EGLL_LAT_DEG
        self.fdm['ic/long-gc-deg']  = EGLL_LON_DEG
        self.fdm['ic/h-agl-ft']     = 8.0            # gear on ground
        self.fdm['ic/psi-true-deg'] = RUNWAY_HDG_DEG
        self.fdm['ic/u-fps']        = 0.0
        self.fdm['ic/v-fps']        = 0.0
        self.fdm['ic/w-fps']        = 0.0
        self.fdm['ic/p-rad_sec']    = 0.0
        self.fdm['ic/q-rad_sec']    = 0.0
        self.fdm['ic/r-rad_sec']    = 0.0
        self.fdm['ic/theta-deg']    = 0.0
        self.fdm['ic/phi-deg']      = 0.0

        self.fdm.run_ic()

        # Start engines and set trims
        self._start_engines()

        # Parking brake on, flaps up, gear down
        self.fdm['fcs/parking-brake-cmd-norm'] = 1.0
        self.fdm['fcs/flap-cmd-norm']          = 0.0
        self.fdm['gear/gear-cmd-norm']         = 1.0     # 1 = down

        # Remember origin for local ENU conversion
        self.origin_lat = EGLL_LAT_DEG
        self.origin_lon = EGLL_LON_DEG
        self.meters_per_deg_lon = (
            METERS_PER_DEG_LAT * math.cos(math.radians(EGLL_LAT_DEG))
        )

        # Control cache (0..1 or -1..1 as appropriate)
        self.throttle = 0.0
        self.elevator = 0.0
        self.aileron  = 0.0
        self.rudder   = 0.0
        self.flap_setting = 0     # 0..4 (Airbus notches: 0, 1, 2, 3, FULL)
        self.gear_down = True
        self.parking_brake = True
        self.wheel_brake = 0.0
        self.speedbrake = 0.0     # 0 = clean, 1 = fully deployed
        self.reverser = False     # true = reverse thrust engaged

    # ------------------------------------------------------------------
    def _start_engines(self):
        """Cold-and-dark → running. -1 targets all engines."""
        try:
            self.fdm['propulsion/set-running'] = -1
        except Exception:
            # Fallback: iterate
            prop = self.fdm.get_propulsion()
            for i in range(prop.get_num_engines()):
                prop.get_engine(i).init_running()
            prop.get_steady_state()

    # ------------------------------------------------------------------
    # Control inputs (called each frame from main.py)
    # ------------------------------------------------------------------
    def set_controls(self):
        # Reverse thrust: when engaged AND on ground, deploy reverser
        # buckets and command reverse power. JSBSim A320 uses negative
        # throttle for reverse when reverser is deployed. If your model
        # doesn't have the reverser-cmd-norm property, the try/except
        # keeps it from crashing.
        rev_active = self.reverser and self.on_ground()
        try:
            for i in (0, 1):
                self.fdm[f'propulsion/engine[{i}]/reverser-cmd-norm'] = (
                    1.0 if rev_active else 0.0
                )
        except (KeyError, Exception):
            pass  # Model doesn't expose reverser property; harmless

        # Effective throttle: when reverser active, apply high negative
        # thrust command. Otherwise use pilot throttle.
        eff_throttle = -0.8 if rev_active else self.throttle

        self.fdm['fcs/throttle-cmd-norm']      = eff_throttle
        self.fdm['fcs/throttle-cmd-norm[1]']   = eff_throttle
        self.fdm['fcs/elevator-cmd-norm']      = self.elevator
        self.fdm['fcs/aileron-cmd-norm']       = self.aileron
        self.fdm['fcs/rudder-cmd-norm']        = self.rudder
        self.fdm['fcs/flap-cmd-norm']          = self.flap_setting / 4.0
        self.fdm['gear/gear-cmd-norm']         = 1.0 if self.gear_down else 0.0
        self.fdm['fcs/left-brake-cmd-norm']    = self.wheel_brake
        self.fdm['fcs/right-brake-cmd-norm']   = self.wheel_brake
        self.fdm['fcs/parking-brake-cmd-norm'] = 1.0 if self.parking_brake else 0.0
        self.fdm['fcs/speedbrake-cmd-norm']    = self.speedbrake

    def step(self):
        self.set_controls()
        self.fdm.run()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------
    def local_position_enu(self):
        """Return (east_m, north_m, up_m) relative to origin (EGLL threshold)."""
        lat = self.fdm['position/lat-geod-deg']
        lon = self.fdm['position/long-gc-deg']
        h_ft = self.fdm['position/h-sl-ft'] + 95

        north = (lat - self.origin_lat) * METERS_PER_DEG_LAT
        east  = (lon - self.origin_lon) * self.meters_per_deg_lon
        up_m  = (h_ft - EGLL_ELEV_FT) * 0.3048
        return east, north, up_m

    def attitude_deg(self):
        """(pitch, roll, heading) in degrees."""
        return (
            math.degrees(self.fdm['attitude/theta-rad']),
            math.degrees(self.fdm['attitude/phi-rad']),
            math.degrees(self.fdm['attitude/psi-rad']),
        )

    def airspeed_kt(self):
        return float(self.fdm['velocities/vc-kts'])

    def ground_speed_kt(self):
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