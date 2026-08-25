# Basic A320 Sim — Panda3D + JSBSim

A minimal working flight simulator: procedurally-modelled A320-ish aircraft,
JSBSim physics, EGLL 27L runway with proper lights (edge / centerline /
threshold / end / PAPI / approach), a stylized city for visual reference,
2D HUD, and keyboard flying.

Runs on top of stock Panda3D + JSBSim. Nothing else needed.

## Install

```bash
pip install panda3d jsbsim
```

That's it. JSBSim's pip wheel bundles the aircraft data, including A320.

## Run

```bash
cd flightsim
python main.py
```

## Files

| File | What it does |
|---|---|
| `main.py` | Panda3D app, main loop, input, camera, animation |
| `flight_dynamics.py` | JSBSim wrapper — loads A320, exposes clean API |
| `plane_model.py` | Procedural A320 from primitives (boxes, cylinders) |
| `scenery.py` | Runway, markings, lights (incl. PAPI), ground, city |
| `hud.py` | Text HUD in the corners |
| `audio.py` | Engine, runway, warning, and altitude callout audio |

## Controls

Primary: **mouse is the yoke** (on by default).

| Input | Action |
|---|---|
| **Mouse** | Yoke — X = aileron, Y = elevator. Mouse *down* on screen = pull back = nose up (real-yoke convention). Small deadzone in the center. |
| `M` | Toggle mouse yoke on/off |
| `W` / `S` | Elevator (pitch down / up) — overrides mouse while held |
| `A` / `D` | Aileron (roll left / right) — overrides mouse while held |
| `Q` / `E` | Rudder |
| `Shift` / `Ctrl` | Throttle up / down |
| `B` (hold) | Wheel brakes |
| `O` | Parking brake toggle |
| `P` | Open setup menu / resume flight |
| `G` | Landing gear toggle |
| `F` / `V` | Flaps down / up one notch (0, 1, 2, 3, FULL) |
| `R` | Toggle full reverse thrust on/off while on the ground |
| `F1` / `F2` | Chase camera / cockpit-ish camera |
| `Esc` | Quit |

The bottom-right HUD readout shows `YOKE MOUSE` or `YOKE KBD ONLY` so
you always know which mode you're in.

**Sensitivity tuning:** `main.py::__init__` has `self.mouse_deadzone`
(default 0.08 = 8% of window half-height/width dead in the center) and
`self.mouse_sensitivity` (default 1.1). Bump sensitivity down to ~0.7
if the aircraft feels too twitchy at cruise, or up to ~1.5 for
snappier response on approach.

Audio is generated and cached in `audio_cache/` on first launch. To use
your own properly licensed recordings, place WAV files in `audio_assets/`
using names such as `3000.wav`, `approaching_minimums.wav`, `retard.wav`,
and `10.wav`; those files take priority over generated callouts.

## Starting position

You spawn on EGLL runway 27L threshold, engines running, parking brake on.
To take off:

1. Press `P` to release parking brake
2. Hold `Shift` to spool engines to takeoff thrust (~90% N1)
3. Aircraft accelerates down the runway
4. At ~150 kt, gentle back-pressure on `S` to rotate
5. Positive rate: `G` to raise gear
6. Above 210 kt, `V` to retract flaps

The runway is 3902m long and you're pointed 270° (west), the correct
heading for 27L. Approach lights extend east (the direction landing
traffic would come from).

## What's realistic

- **Physics**: JSBSim's A320 model. Real 6-DOF aerodynamics, engine
  thrust curves, ground reactions, control response.
- **Speeds**: rotation ~145–150 kt, approach ~135–140 kt, stall ~110 kt
  clean, all in the right ballpark for typical weights.
- **Runway lights**: standard ICAO layout — white edges, centerline
  turning red at the far end, red end lights, green threshold, PAPI
  showing 4W / 3W1R / 2W2R / 1W3R / 4R based on your actual glideslope
  angle to the touchdown zone.
- **Control surface animation**: ailerons, elevator, rudder, flaps
  visibly deflect with your inputs on the exterior model.

## What's deliberately not realistic (yet)

- **No cockpit interior / PFD / MCDU** — you get a text HUD, not an
  Airbus display suite. A real PFD is a significant sub-project.
- **No fly-by-wire control laws** — you're flying JSBSim's raw
  aerodynamic response, not Airbus's protection-shaped feel.
- **No autopilot** — manual only.
- **No FMS / flight planning / autothrust**.
- **No weather** — clear, still air.
- **No ATC / traffic**.
- **No sound**.
- **Procedural model, not a real 3D scan** — clearly an airliner shape
  but obviously polygonal. Replace with a proper `.gltf` or `.bam`
  model whenever you have one and swap `build_a320()` for
  `loader.loadModel(...)`.
- **Runway designator "27L" is a blank white bar** — real text needs a
  font texture and is easy to add later.

## Sign conventions to verify

The Euler-angle handoff from JSBSim to Panda3D HPR has one axis (roll)
where the convention is easy to get inverted. If you find that rolling
right in-sim visually banks left, flip the sign in
`main.py::_sync_plane_to_physics()` on `-roll_deg`. Same for pitch or
heading if either feels reversed. It's a one-character fix in one place.

## Extending this

Roughly in order of "biggest payoff for least work":

1. **Sound** — engine loop pitched by N1, wind by airspeed, gear
   thump. `pyOpenAL` or Panda3D's audio.
2. **Joystick support** — Panda3D exposes it via `base.devices`.
3. **Real A320 model** — buy or find CC-licensed .gltf, drop in.
4. **More scenery** — model the terminals as extruded footprints from
   OSM (`osmnx` in Python), place jetways at gate positions.
5. **Weather** — wind vector into JSBSim (`atmosphere/wind-*-fps`),
   fog density, clouds.
6. **Second runway** — 27R, 09L, 09R are all easy copies with different
   position/heading.
7. **Basic autopilot** — heading hold, altitude hold, VS mode.
   Actually not too bad as a first cut (PID controllers on JSBSim's
   inputs).
8. **Instrument panel** — 2D PFD/ND drawn with Panda3D's DirectGUI, or
   a rendered-to-texture approach on 3D cockpit panels.

## When something goes wrong

- **`Could not load A320`** — your JSBSim aircraft folder may spell it
  differently. Check `python -c "import jsbsim, os; print(os.path.join(os.path.dirname(jsbsim.__file__)))"`,
  look inside `aircraft/`, and adjust the name in `flight_dynamics.py`.
- **Aircraft falls through the ground** — bump `ic/h-agl-ft` up a
  little in `flight_dynamics.py`. The initial condition wants gear
  contact, not overlap.
- **Won't accelerate** — parking brake is on. Press `P`.
- **Flies backwards / camera confused** — heading sign convention;
  see "Sign conventions to verify" above.
- **Everything looks black** — lighting node isn't attached. Verify
  `add_lighting(self.render)` runs in `main.py`.
