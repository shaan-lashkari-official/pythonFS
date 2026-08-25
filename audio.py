"""Procedural simulator audio and locally generated spoken callouts.

The engine loop uses layered synthesis (filtered broadband noise for the
roar, low-harmonic rumble for weight, high FM-modulated tone for the
turbine whine, blade-pass tone, HF hiss, and slow amplitude modulation)
so it actually reads as a jet turbofan rather than stacked sine waves.

The Airbus-style two-tone chime is bell synthesis: bright attack,
exponential decay, inharmonic partials for a slightly metallic bell
character. It fires automatically as the aircraft passes 500 ft AGL on
descent, right before the "500" voice callout.

Cached WAVs are versioned in the filename (v4, v3, v1). Bumping the
version invalidates any old cache without deleting the folder by hand.
Real .wav files dropped into audio_assets/ with the same filename
always take precedence over the procedural cache.
"""

import math
import random
import subprocess
import wave
from pathlib import Path

from panda3d.core import Filename


SAMPLE_RATE = 22050


class AudioSystem:
    def __init__(self, loader):
        self.loader = loader
        self.root = Path(__file__).with_name('audio_cache')
        self.asset_root = Path(__file__).with_name('audio_assets')
        self.root.mkdir(exist_ok=True)

        self.engine = self._load_asset_or_generated(
            'engine_loop_v4.wav', self._write_engine)
        self.rumble = self._load_asset_or_generated(
            'touchdown_rumble_v2.wav', self._write_rumble)
        self.roll = self._load_asset_or_generated(
            'runway_roll_v2.wav', self._write_roll)
        self.gear_sound = self._load_asset_or_generated(
            'gear_transition_v2.wav', self._write_gear)
        self.stall = self._load_asset_or_generated(
            'stall_warning_v3.wav', self._write_stall)
        self.overspeed = self._load_asset_or_generated(
            'overspeed_warning_v3.wav', self._write_overspeed)
        self.chime_double = self._load_asset_or_generated(
            'chime_double_v1.wav', self._write_chime_double)
        self.chime_single = self._load_asset_or_generated(
            'chime_single_v1.wav', self._write_chime_single)

        self.callouts = {}
        self._spoken = set()
        self._stall_on = False
        self._overspeed_on = False
        self._roll_on = False
        self._gear_down = True
        self._chime_played_500 = False

        for text in (
            '3000', '2500', '2000', '1500', '1000', '500', '400', '300',
            'APPROACHING MINIMUMS', '200', '100', '80', '70', '60', '50',
            '40', '30', '20', 'RETARD', '10',
        ):
            self.callouts[text] = self._load_callout(text)
        self._callout_sequence = [
            (3000, '3000'), (2500, '2500'), (2000, '2000'),
            (1500, '1500'), (1000, '1000'), (500, '500'),
            (400, '400'), (300, '300'), (200, 'APPROACHING MINIMUMS'),
            (200, '200'), (100, '100'), (80, '80'), (70, '70'),
            (60, '60'), (50, '50'), (40, '40'), (30, '30'),
            (20, 'RETARD'), (10, 'RETARD'),
        ]
        self._callout_index = 0
        self._last_agl = None

        if self.engine is not None:
            self.engine.setLoop(True)
            self.engine.play()

    # -----------------------------------------------------------------
    # Loading helpers
    # -----------------------------------------------------------------
    def _load_asset_or_generated(self, filename, fallback_writer):
        """Prefer a real .wav in audio_assets/, else generate + cache."""
        asset = self.asset_root / filename
        if asset.exists():
            return self.loader.loadSfx(Filename.fromOsSpecific(str(asset)))
        cache = self.root / filename
        if not cache.exists():
            try:
                fallback_writer(cache)
            except Exception as e:
                print(f'[audio] failed to write {filename}: {e}')
                return None
        return (self.loader.loadSfx(Filename.fromOsSpecific(str(cache)))
                if cache.exists() else None)

    def _write_samples(self, path, duration, sample_func,
                       sample_rate=SAMPLE_RATE):
        samples = int(sample_rate * duration)
        with wave.open(str(path), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            for index in range(samples):
                value = sample_func(index / sample_rate, index, samples)
                value = max(-1.0, min(1.0, value))
                output.writeframesraw(
                    int(value * 32767).to_bytes(2, 'little', signed=True))

    @staticmethod
    def _low_pass(samples, alpha):
        """1-pole IIR low-pass. alpha ~0.02-0.3 (higher = higher cutoff)."""
        out = []
        state = 0.0
        for n in samples:
            state = state * (1.0 - alpha) + n * alpha
            out.append(state)
        return out

    @staticmethod
    def _high_pass(samples, coeff=0.95):
        """1-pole IIR high-pass. coeff closer to 1.0 = lower cutoff."""
        out = []
        prev_in = 0.0
        prev_out = 0.0
        for n in samples:
            hp = coeff * (prev_out + n - prev_in)
            prev_in = n
            prev_out = hp
            out.append(hp)
        return out

    @staticmethod
    def _normalize(samples, target=0.5):
        peak = max((abs(x) for x in samples), default=1.0) or 1.0
        return [x / peak * target for x in samples]

    # =================================================================
    # PROCEDURAL WAVEFORM GENERATORS
    # =================================================================
    def _write_engine(self, path):
        """
        Turbofan loop. Layered:
          - filtered broadband noise (the "roar" — the biggest missing
            component of pure-sine engine synthesis)
          - low harmonic rumble (weight / compressor)
          - turbine whine at ~2.8 kHz with slow FM wobble (jet character)
          - blade-pass tone (~720 Hz)
          - high-pass noise for shear hiss
          - slow amplitude modulation for "living" quality
        4-second seamless loop.
        """
        duration = 4.0
        samples = int(SAMPLE_RATE * duration)

        # Pre-generate noise beds (reproducible via seed)
        rng = random.Random(37)
        raw = [rng.uniform(-1.0, 1.0) for _ in range(samples)]

        # Low-passed noise → roar (removes brittle high hiss)
        roar_bed = self._normalize(self._low_pass(raw, 0.18), 0.55)

        # High-passed noise → turbine shear hiss
        hiss_bed = self._normalize(self._high_pass(raw, 0.95), 0.22)

        def sample(t, i, total):
            am = 0.88 + 0.12 * math.sin(2 * math.pi * 2.3 * t)

            # Low rumble — compressor + case resonance
            rumble = 0.20 * math.sin(2 * math.pi *  92 * t)
            rumble += 0.14 * math.sin(2 * math.pi * 184 * t)
            rumble += 0.08 * math.sin(2 * math.pi * 276 * t)

            # Combustion / airflow roar
            roar = roar_bed[i] * 0.85

            # Turbine whine — slight FM wobble makes it feel real
            whine_f = 2800 + 25 * math.sin(2 * math.pi * 1.1 * t)
            whine  = 0.14 * math.sin(2 * math.pi * whine_f * t)
            whine += 0.07 * math.sin(2 * math.pi * whine_f * 1.5 * t)

            # Blade-pass (fan chopping air)
            blade = 0.06 * math.sin(2 * math.pi * 720 * t)

            # HF shimmer
            shimmer = hiss_bed[i] * 0.45

            return (rumble + roar + whine + blade + shimmer) * am * 0.42

        self._write_samples(path, duration, sample)

    def _write_chime_double(self, path):
        """
        Airbus PA-style two-tone chime: high "bing" (~1050 Hz) then
        low "bong" (~700 Hz), each with bell-like inharmonic decay.
        Total duration ~1.6 s.
        """
        duration = 1.6

        def bell(t, freq, start, decay=0.85, amp=0.5):
            rt = t - start
            if rt < 0:
                return 0.0
            attack = min(1.0, rt / 0.005)          # 5 ms attack
            env = attack * math.exp(-rt / decay)
            if env < 0.001:
                return 0.0
            v  = 1.00 * math.sin(2 * math.pi * freq * rt)
            v += 0.45 * math.sin(2 * math.pi * freq * 2.01 * rt)
            v += 0.22 * math.sin(2 * math.pi * freq * 3.00 * rt)
            v += 0.12 * math.sin(2 * math.pi * freq * 4.02 * rt)
            v += 0.08 * math.sin(2 * math.pi * freq * 5.40 * rt)
            return v * env * amp

        def sample(t, i, total):
            return bell(t, 1050.0, 0.00) + bell(t, 700.0, 0.55)

        self._write_samples(path, duration, sample)

    def _write_chime_single(self, path):
        """Single "bong" — for future use (seat belt sign, PA, etc)."""
        duration = 1.2

        def bell(t, freq, start, decay=0.9, amp=0.55):
            rt = t - start
            if rt < 0:
                return 0.0
            attack = min(1.0, rt / 0.005)
            env = attack * math.exp(-rt / decay)
            if env < 0.001:
                return 0.0
            v  = 1.00 * math.sin(2 * math.pi * freq * rt)
            v += 0.40 * math.sin(2 * math.pi * freq * 2.01 * rt)
            v += 0.18 * math.sin(2 * math.pi * freq * 3.00 * rt)
            v += 0.10 * math.sin(2 * math.pi * freq * 5.4 * rt)
            return v * env * amp

        def sample(t, i, total):
            return bell(t, 880.0, 0.0)

        self._write_samples(path, duration, sample)

    def _write_stall(self, path):
        """
        Stall / low-speed cricket chirp: multi-harmonic tone modulated by
        a rapid squared-sine tremolo (~7 Hz on-off).
        """
        duration = 0.5    # short loop, plays continuously when active

        def sample(t, i, total):
            trem = (0.5 + 0.5 * math.sin(2 * math.pi * 7.0 * t)) ** 2
            v  = 0.60 * math.sin(2 * math.pi *  810 * t)
            v += 0.30 * math.sin(2 * math.pi * 1620 * t)
            v += 0.15 * math.sin(2 * math.pi * 2430 * t)
            fade  = min(1.0, i / (SAMPLE_RATE * 0.005))
            fade *= min(1.0, (total - i) / (SAMPLE_RATE * 0.005))
            return v * trem * fade * 0.50

        self._write_samples(path, duration, sample)

    def _write_overspeed(self, path):
        """Airbus-style clacker: rapid burst of a mid-frequency tone."""
        duration = 0.35

        def sample(t, i, total):
            phase = (t * 5.0) % 1.0
            trem = 1.0 if phase < 0.15 else 0.0
            v  = 0.70 * math.sin(2 * math.pi * 480 * t)
            v += 0.30 * math.sin(2 * math.pi * 960 * t)
            fade  = min(1.0, i / (SAMPLE_RATE * 0.005))
            fade *= min(1.0, (total - i) / (SAMPLE_RATE * 0.005))
            return v * trem * fade * 0.55

        self._write_samples(path, duration, sample)

    def _write_rumble(self, path):
        """Touchdown rumble: filtered noise burst with a low pulse."""
        rng = random.Random(41)
        noise = [rng.uniform(-1.0, 1.0) for _ in range(SAMPLE_RATE * 2)]

        def sample(t, i, total):
            envelope = min(1.0, t / 0.025) * max(0.0, 1.0 - t / 1.2)
            pulse = 0.55 * math.sin(2 * math.pi * 54 * t)
            return (pulse + noise[i] * 0.65) * envelope * 0.65

        self._write_samples(path, 1.2, sample)

    def _write_roll(self, path):
        """Tire-on-runway roll noise: low-frequency noise + weak tone."""
        rng = random.Random(52)
        noise = [rng.uniform(-1.0, 1.0) for _ in range(SAMPLE_RATE * 3)]

        def sample(t, i, total):
            return (0.55 * noise[i] + 0.25 * math.sin(2 * math.pi * 42 * t)) * 0.35

        self._write_samples(path, 3.0, sample)

    def _write_gear(self, path):
        """Gear extension/retraction: hydraulic motor + two clunks."""
        def sample(t, i, total):
            motor = math.sin(2 * math.pi * (90 + t * 35) * t) * 0.18
            clunk = 0.0
            for hit in (0.15, 1.55):
                delta = t - hit
                if 0 <= delta < 0.12:
                    clunk += (math.sin(2 * math.pi * 68 * delta)
                              * (1.0 - delta / 0.12) * 0.55)
            return motor + clunk

        self._write_samples(path, 1.8, sample)

    # -----------------------------------------------------------------
    # Callouts (Windows TTS with a tone fallback)
    # -----------------------------------------------------------------
    def _load_callout(self, text):
        safe_name = text.lower().replace(' ', '_') + '.wav'
        asset_path = self.asset_root / safe_name
        if asset_path.exists():
            return self.loader.loadSfx(Filename.fromOsSpecific(str(asset_path)))
        path = self.root / safe_name
        if not path.exists():
            self._speak_to_file(text, path)
        if not path.exists():
            self._write_tone_fallback(path, 660.0, 0.18)
        return (self.loader.loadSfx(Filename.fromOsSpecific(str(path)))
                if path.exists() else None)

    def _write_tone_fallback(self, path, frequency, duration):
        def sample(t, i, total):
            env  = min(1.0, i / (SAMPLE_RATE * 0.03))
            env *= min(1.0, (total - i) / (SAMPLE_RATE * 0.08))
            v  = 0.60 * math.sin(2 * math.pi * frequency * t)
            v += 0.30 * math.sin(2 * math.pi * frequency * 1.5 * t)
            return v * env * 0.5
        self._write_samples(path, duration, sample)

    def _speak_to_file(self, text, path):
        escaped_text = text.replace("'", "''")
        escaped_path = str(path).replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.Rate=-3; $s.Volume=100; "
            "$s.SetOutputToWaveFile('" + escaped_path + "'); "
            "$s.Speak('" + escaped_text + "'); $s.Dispose()"
        )
        try:
            subprocess.run(
                ['powershell', '-NoProfile', '-NonInteractive',
                 '-Command', script],
                check=False, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=8,
            )
        except (OSError, subprocess.TimeoutExpired):
            return

    # =================================================================
    # RUNTIME UPDATE
    # =================================================================
    def update(self, fd):
        n1 = max(0.0, min(100.0, fd.n1_percent()))
        if self.engine is not None:
            self.engine.setVolume(0.06 + n1 / 100.0 * 0.22)
            self.engine.setPlayRate(0.72 + n1 / 100.0 * 0.58)

        stall = fd.airspeed_kt() < 110.0 and fd.agl_ft() > 50.0
        overspeed = fd.airspeed_kt() > 320.0
        self._set_warning(self.stall, stall, '_stall_on')
        self._set_warning(self.overspeed, overspeed, '_overspeed_on')

        ground_speed = max(0.0, fd.ground_speed_kt())
        rolling = ((fd.on_ground() or getattr(fd, 'belly_contact', False))
                   and ground_speed > 3.0)
        if self.roll is not None and rolling:
            self.roll.setVolume(min(0.42, 0.035 + ground_speed / 260.0))
            self.roll.setPlayRate(min(1.8, 0.72 + ground_speed / 170.0))
        self._set_warning(self.roll, rolling, '_roll_on')

        if fd.gear_down != self._gear_down:
            if self.gear_sound is not None:
                self.gear_sound.setPlayRate(0.9 if fd.gear_down else 1.0)
                self.gear_sound.play()
            self._gear_down = fd.gear_down

        self._update_callouts(fd)

    def _update_callouts(self, fd):
        altitude = fd.agl_ft()
        if self._last_agl is None:
            while (self._callout_index < len(self._callout_sequence) and
                   altitude <= self._callout_sequence[self._callout_index][0]):
                self._callout_index += 1
            self._last_agl = altitude
            return

        descending = (altitude < self._last_agl
                      and fd.vertical_speed_fpm() < -50.0)

        if descending and self._callout_index < len(self._callout_sequence):
            threshold, text = self._callout_sequence[self._callout_index]
            if altitude <= threshold:
                # Airbus plays the double chime right before the 500 ft
                # voice callout during a stable descent.
                if text == '500' and not self._chime_played_500:
                    self.play_chime_double()
                    self._chime_played_500 = True
                self.play_callout(text)
                self._callout_index += 1
        self._last_agl = altitude

    def reset_callouts(self):
        self._callout_index = 0
        self._last_agl = None
        self._chime_played_500 = False

    def _set_warning(self, sound, active, state_name):
        previous = getattr(self, state_name)
        if sound is not None and active and not previous:
            sound.setLoop(True)
            sound.play()
        elif sound is not None and not active and previous:
            sound.stop()
        setattr(self, state_name, active)

    # -----------------------------------------------------------------
    # Public trigger helpers
    # -----------------------------------------------------------------
    def touchdown(self, impact):
        if self.rumble is not None and impact > 0.08:
            self.rumble.setVolume(min(1.0, 0.18 + impact * 0.55))
            self.rumble.setPlayRate(0.82 + min(0.35, impact * 0.18))
            self.rumble.play()

    def play_callout(self, text):
        sound = self.callouts.get(text)
        if sound is not None:
            sound.play()

    def play_chime_double(self):
        """Airbus two-tone bing-bong (auto-fires at 500 ft on descent)."""
        if self.chime_double is not None:
            self.chime_double.play()

    def play_chime_single(self):
        """Single bong — for seat belt / cabin-call use."""
        if self.chime_single is not None:
            self.chime_single.play()