# Batch A: Core Feel Improvements

## Overview
Four high-impact changes that address the most noticeable gaps: broken taxi steering, static sun position, limited camera views, and bare-bones HUD.

---

## 1. Fix Taxi Ground Handling

### Problem
The JSBSim A320.xml has `max_steer` set to **5 degrees** (real A320 tiller: **75 degrees**). The friction values are also backwards: `static_friction=0.5` and `dynamic_friction=0.8` (static should be higher than dynamic). The Python layer compensates with gains up to 2.5x, but you still can't make tight taxi turns.

### Changes

**New file: `aircraft/A320/A320.xml`** (copied from venv, modified)
- `NOSE_LG max_steer`: 5 -> **75** degrees
- `NOSE_LG static_friction`: 0.5 -> **0.8** (realistic dry concrete)
- `NOSE_LG dynamic_friction`: 0.8 -> **0.5** (must be lower than static)
- `LEFT_MLG` and `RIGHT_MLG` same friction fix: static 0.8, dynamic 0.5
- `rolling_friction`: 0.02 -> **0.025** (all gear)

**Modify: `flight_dynamics.py`**
- Point FDM to local `aircraft/` directory via `set_aircraft_path()`
- Recalibrate steering gain schedule for the new 75-degree range:
  - Below 5 kt: gain = 1.0 (full 75-degree tiller authority for tight turns)
  - 5-15 kt: gain = 0.5 (~38 degrees, comfortable taxi)
  - 15-30 kt: taper to 0.15 (~11 degrees)
  - 30-60 kt: taper to 0.08 (~6 degrees, pedal-only regime)
  - Above 60 kt: gain = 0.04 (~3 degrees, aerodynamic rudder dominates)
- Remove the `steer_gain = 2.5` hack (was compensating for 5-degree limit)
- Reduce the fake lateral friction brake pulse since real friction values are now correct

---

## 2. Dynamic Sun Position + Golden Hour

### Problem
The sun's HPR is hardcoded to `(-40, -50, 0)` in `add_lighting()` and never changes. `_apply_time_of_day()` only adjusts light **colors**, not the sun's **direction**. There's no low-angle sun, no long shadows, no golden hour feel.

### Changes

**Modify: `scenery.py` `add_lighting()`**
- Remove the fixed `sun_np.setHpr(-40, -50, 0)` — let main.py control it

**Modify: `main.py` `_apply_time_of_day()`**
- Compute sun elevation and azimuth from the hour using a simple solar model:
  - **Elevation**: peaks at ~65 degrees at noon (London latitude), 0 at sunrise/sunset
  - **Azimuth**: sweeps from ~90 degrees (east, sunrise) through ~180 degrees (south, noon) to ~270 degrees (west, sunset)
  - Sunrise ~6:00, sunset ~18:00 (simplified equinox model)
- Set `sun_np.setHpr(azimuth, -elevation, 0)` so shadows move realistically
- Enhanced color ramp based on sun elevation:
  - **0-5 degrees** (golden hour): deep warm orange-red `(1.0, 0.55, 0.20)`
  - **5-15 degrees**: warm gold `(1.0, 0.78, 0.50)`
  - **15-30 degrees**: yellow-white `(0.98, 0.92, 0.78)`
  - **30+ degrees**: neutral `(0.95, 0.88, 0.75)`
- Sky color also shifts with elevation: orange-pink at low sun, blue at high sun
- Ambient light gets a warm tint during golden hour to fill shadows with warmth

---

## 3. Multiple Camera Views

### Problem
Only 2 views exist (chase + cockpit). Competing sims offer passenger windows, gear cams, tower views, etc.

### Changes

**Modify: `main.py`**
- Replace the `camera_mode` string with a camera view list. Cycle through with **C** key, direct-select with **1-7** number keys.
- Each view defines: name, position (relative to aircraft or world), look-at target, and smoothing params.

**Views to add (all positions in plane model coords: +Y forward, +X right, +Z up):**

| Key | Name | Position | Look-at | Notes |
|-----|------|----------|---------|-------|
| 1 | Chase | Behind+above | Aircraft | Existing, smoothed |
| 2 | Cockpit | (0, 16.5, 2.5) relative | Forward along heading | Existing |
| 3 | Passenger Wing | (3.5, -1, 1.2) relative | Right+down over wing | Looks out right window over wing, slight head tilt |
| 4 | Gear Cam | (0, -4, -2.5) relative | Forward under belly | Low angle behind main gear, sees runway rushing past |
| 5 | Tail Cam | (0, -17, 7) relative | Forward along fuselage | From vertical stabilizer top, dramatic view of aircraft |
| 6 | Tower | Fixed world pos near threshold (0, 200, 45) | Tracks aircraft | ATC tower perspective, doesn't follow aircraft position |
| 7 | Top-down | (0, 0, +120) above aircraft | Straight down at aircraft | Overhead tactical view |

- The HUD shows the active view name briefly when switching
- Tower view uses world-fixed position; all others are aircraft-relative
- Chase camera keeps its existing pan/smoothing; other views use fixed offsets with g-force shake

---

## 4. HUD Improvements

### Problem
Current HUD is plain green text in corners. No visual instruments, no color coding, no approach-critical displays.

### Changes

**Rewrite: `hud.py`**

New layout with semi-transparent panel backgrounds and color-coded indicators:

**Left Panel - Primary Flight Data:**
- `IAS` with large font speed value
- `GS` ground speed
- `MACH` number (when above 0.4M)
- `VS` vertical speed with up/down arrow indicator
- `AGL` radio altitude (shown below 2500 ft, large amber text below 500 ft)

**Right Panel - Altitude & Navigation:**
- `ALT` altitude with large font
- `HDG` heading with degree symbol

**Top-Center - Flight Mode Annunciator:**
- Shows current phase: `TAXI`, `TAKEOFF`, `CLIMB`, `CRUISE`, `DESCENT`, `APPROACH`, `LANDING`
- Based on: gear state, altitude, speed, VS, AGL

**Right-Side Panel - Engine & Config:**
- `N1` with a simple text progress bar `[=========>  ]`
- `THR` throttle percentage
- `FLAP` with color: green=matched to speed, amber=overspeed
- `GEAR` with color: green=down-locked, amber=in transit
- `BRK` brake status
- `SPBRK` speedbrake
- `REV` reverse thrust indicator (when active, red text)

**Bottom-Center - Control Position:**
- Keep the existing elevator/aileron/rudder bars but improve formatting

**Color scheme:**
- Primary: bright green `(0.2, 1.0, 0.4)` (unchanged, aviation standard)
- Caution: amber `(1.0, 0.75, 0.1)`
- Warning: red `(1.0, 0.2, 0.1)`
- Info: cyan `(0.4, 0.85, 1.0)`
- Inactive: dim gray `(0.5, 0.5, 0.5)`

**Bottom-Left - Camera View Name:**
- Shows active camera name when switching (fades after 3 sec)

**Remove:** The long help text line at bottom (move to setup screen or make togglable with H key)

---

## Files Modified

| File | Changes |
|------|---------|
| `aircraft/A320/A320.xml` | **NEW** - local copy with fixed steering + friction |
| `flight_dynamics.py` | Load from local aircraft dir, recalibrate steering gains |
| `main.py` | Sun position math, camera view system, input bindings |
| `scenery.py` | Remove hardcoded sun HPR from `add_lighting()` |
| `hud.py` | Complete rewrite with panels, colors, instruments |

## Files NOT Modified
- `minimap.py`, `plane_model.py`, `night_lighting.py`, `shadow.py`, `audio.py` - untouched

---

## Testing
1. **Taxi test**: Spawn on runway, release parking brake, advance throttle to ~10%, verify 90-degree turns are possible at walking speed with full rudder
2. **Golden hour test**: Set time to 6.5h (dawn) and 17.5h (dusk), verify warm orange light with long shadows
3. **Camera test**: Press 1-7 and C to cycle all views, verify each provides a useful perspective
4. **HUD test**: Verify all readouts update, color coding works, radio altitude appears on approach
