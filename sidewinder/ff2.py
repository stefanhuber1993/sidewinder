"""
sidewinder/ff2.py — Microsoft Sidewinder Force Feedback 2 driver.

Uses python-hid (hidapi), which shares the device with the OS driver rather than
claiming it, so no sudo is needed (on Linux, a udev rule — see the README).

Requires the native hidapi library plus `pip install hid`:
    macOS   brew install hidapi
    Linux   apt install libhidapi-hidraw0   (or your distro's package)
    Windows hidapi.dll on PATH

Written and verified on macOS; nothing here is platform-specific.

Full HID PID protocol implementation for all effect types.
Designed for interactive use in Jupyter notebooks.

Quick start::

    from sidewinder.ff2 import FF2Device
    ff = FF2Device()

    e = ff.constant_force(angle_deg=90, magnitude=200)
    import time; time.sleep(2)
    e.free()

    ff.close()
"""
import time
import hid

from sidewinder.controls import (
    ButtonDown, ButtonUp, HatMoved, InputState,
    decode_input_report, diff_states,
)

VID = 0x045e
PID = 0x001b

# ── Output report IDs ─────────────────────────────────────────────────────────
R_SET_EFFECT         = 0x01
R_SET_ENVELOPE       = 0x02
R_SET_CONDITION      = 0x03
R_SET_PERIODIC       = 0x04
R_SET_CONSTANT_FORCE = 0x05
R_SET_RAMP_FORCE     = 0x06
R_DOWNLOAD_FORCE     = 0x08  # X/Y force sample, -127..127 per axis
R_EFFECT_OPERATION   = 0x0a
R_PID_BLOCK_FREE     = 0x0b
R_DEVICE_CONTROL     = 0x0c
R_DEVICE_GAIN        = 0x0d

# ── Input report IDs ──────────────────────────────────────────────────────────
R_INPUT_JOYSTICK  = 0x01  # axes, hat, buttons — sent continuously
R_INPUT_PID_STATE = 0x02  # PID state — sent only when FF state changes

# ── Feature report IDs ────────────────────────────────────────────────────────
FR_CREATE_NEW_EFFECT = 0x01   # SET feature: allocate a new effect block
FR_PID_BLOCK_LOAD    = 0x02   # GET feature: returned block index + status
FR_PID_POOL          = 0x03   # GET feature: pool size + simultaneous effect max

# How many times alloc() re-reads a short/garbled PID Block Load reply.
_BLOCK_LOAD_READ_ATTEMPTS = 5

# ── Effect type ordinals (HID PID array field, Logical Min 1) ─────────────────
ET_CONSTANT_FORCE = 1
ET_RAMP           = 2
ET_SQUARE         = 3
ET_SINE           = 4
ET_TRIANGLE       = 5
ET_SAWTOOTH_UP    = 6
ET_SAWTOOTH_DOWN  = 7
ET_SPRING         = 8
ET_DAMPER         = 9
ET_INERTIA        = 10
ET_FRICTION       = 11
ET_CUSTOM         = 12

ET_NAMES = {
    ET_CONSTANT_FORCE: "Constant Force",
    ET_RAMP:           "Ramp",
    ET_SQUARE:         "Square",
    ET_SINE:           "Sine",
    ET_TRIANGLE:       "Triangle",
    ET_SAWTOOTH_UP:    "Sawtooth Up",
    ET_SAWTOOTH_DOWN:  "Sawtooth Down",
    ET_SPRING:         "Spring",
    ET_DAMPER:         "Damper",
    ET_INERTIA:        "Inertia",
    ET_FRICTION:       "Friction",
    ET_CUSTOM:         "Custom",
}

PERIODIC_TYPES  = {ET_SQUARE, ET_SINE, ET_TRIANGLE, ET_SAWTOOTH_UP, ET_SAWTOOTH_DOWN}
CONDITION_TYPES = {ET_SPRING, ET_DAMPER, ET_INERTIA, ET_FRICTION}

# ── Device control ordinals ───────────────────────────────────────────────────
DC_ENABLE_ACTUATORS  = 1
DC_DISABLE_ACTUATORS = 2
DC_STOP_ALL_EFFECTS  = 3
DC_DEVICE_RESET      = 4
DC_DEVICE_PAUSE      = 5
DC_DEVICE_CONTINUE   = 6

# ── Effect operation ordinals ─────────────────────────────────────────────────
OP_START      = 1  # start alongside other effects
OP_START_SOLO = 2  # stop all others, then start
OP_STOP       = 3


# ── Wire helpers ──────────────────────────────────────────────────────────────

def _le16(v: int) -> list:
    """Little-endian 16-bit, handles signed values via two's-complement mask."""
    v = int(v) & 0xFFFF
    return [v & 0xFF, (v >> 8) & 0xFF]


def _s8(v: int) -> int:
    """Clamp to -128..127 and return as unsigned byte."""
    return max(-128, min(127, int(v))) & 0xFF


def _angle_byte(deg: float) -> int:
    """Map 0-360 degrees to logical 0-255 (Physical Max 36000 × 0.01° = 360°)."""
    return round(float(deg) % 360.0 / 360.0 * 255) & 0xFF


# ── Effect ────────────────────────────────────────────────────────────────────

class Effect:
    """
    A single allocated HID PID effect block.

    Create via FF2Device factory methods (constant_force, periodic, …).
    Returned effects are already playing. Call .free() when done, or use as
    a context manager::

        with ff.spring(stiffness=100) as e:
            time.sleep(5)
    """

    def __init__(self, device: "FF2Device", block: int, effect_type: int):
        self._dev        = device
        self.block       = block
        self.effect_type = effect_type
        self._playing    = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def play(self, loop_count: int = 0xFF) -> "Effect":
        """Start the effect. loop_count: 1-255 repetitions, 0xFF ≈ indefinite."""
        self._dev._effect_op(self.block, OP_START, loop_count)
        self._playing = True
        return self

    def play_solo(self, loop_count: int = 0xFF) -> "Effect":
        """Stop all other effects, then start this one."""
        self._dev._effect_op(self.block, OP_START_SOLO, loop_count)
        self._playing = True
        return self

    def stop(self) -> "Effect":
        self._dev._effect_op(self.block, OP_STOP, 0)
        self._playing = False
        return self

    def free(self) -> None:
        """Stop and release this effect block back to the device pool."""
        try:
            self.stop()
        except Exception:
            pass
        try:
            self._dev._free_block(self.block)
        except Exception:
            pass

    def __enter__(self) -> "Effect":
        return self

    def __exit__(self, *_) -> None:
        self.free()

    # ── Report uploads (can be called while playing to update in-flight) ───────

    def set_base(
        self,
        duration_ms:       int   = 32767,
        gain:              int   = 255,
        direction_deg:     float = 0.0,
        axis_x:            bool  = True,
        axis_y:            bool  = True,
        direction_enable:  bool  = True,
        trigger_button:    int   = 0xFF,  # 0xFF = no button trigger
        trigger_repeat_ms: int   = 0,
        sample_period_ms:  int   = 0,
        start_delay_ms:    int   = 0,
    ) -> "Effect":
        """
        Upload Set Effect Report (report 1).
        Safe to call while effect is playing to update direction or gain.
        """
        axes_byte = int(axis_x) | (int(axis_y) << 1) | (int(direction_enable) << 2)
        self._dev._out([
            R_SET_EFFECT,
            self.block, self.effect_type,
            *_le16(duration_ms),
            *_le16(trigger_repeat_ms),
            *_le16(sample_period_ms),
            gain & 0xFF,
            trigger_button & 0xFF,
            axes_byte,
            _angle_byte(direction_deg), 0x00,  # direction instance 1, instance 2
            *_le16(start_delay_ms),
        ])
        return self

    def set_envelope(
        self,
        attack_level: int = 0,
        attack_ms:    int = 0,
        fade_level:   int = 0,
        fade_ms:      int = 0,
    ) -> "Effect":
        self._dev._out([
            R_SET_ENVELOPE,
            self.block,
            attack_level & 0xFF,
            fade_level & 0xFF,
            *_le16(attack_ms),
            *_le16(fade_ms),
        ])
        return self

    def set_constant_force(self, magnitude: int) -> "Effect":
        """
        magnitude: -255..255 (signed). Safe to call while playing.
        """
        self._dev._out([R_SET_CONSTANT_FORCE, self.block, *_le16(int(magnitude))])
        return self

    def set_ramp_force(self, start: int, end: int) -> "Effect":
        self._dev._out([R_SET_RAMP_FORCE, self.block, _s8(start), _s8(end)])
        return self

    def set_periodic(
        self,
        magnitude:  int   = 255,
        offset:     int   = 0,
        phase_deg:  float = 0.0,
        period_ms:  int   = 500,
    ) -> "Effect":
        """
        magnitude:  0-255  — peak amplitude
        offset:    -128..127 — DC offset added to the waveform
        phase_deg:  0-360  — starting phase angle
        period_ms:  0-32767 — cycle length in milliseconds
        """
        phase = _angle_byte(phase_deg)
        self._dev._out([
            R_SET_PERIODIC,
            self.block,
            magnitude & 0xFF,
            _s8(offset),
            phase,
            *_le16(period_ms),
        ])
        return self

    def set_condition(
        self,
        axis:       int = 0,    # 0=X, 1=Y
        cp_offset:  int = 0,    # center point: -128..127
        pos_coeff:  int = 127,  # positive-side coefficient: -128..127
        neg_coeff:  int = 127,  # negative-side coefficient: -128..127
        pos_sat:    int = 255,  # positive saturation: 0-255
        neg_sat:    int = 255,  # negative saturation: 0-255
        dead_band:  int = 0,    # dead zone: 0-255
    ) -> "Effect":
        """
        Upload Set Condition Report (report 3) for one axis.
        Safe to call while playing.
        """
        self._dev._out([
            R_SET_CONDITION,
            self.block,
            int(axis) & 0x0F,
            _s8(cp_offset),
            _s8(pos_coeff),
            _s8(neg_coeff),
            pos_sat  & 0xFF,
            neg_sat  & 0xFF,
            dead_band & 0xFF,
        ])
        return self

    def __repr__(self) -> str:
        state = "playing" if self._playing else "stopped"
        return f"<Effect block={self.block} type={ET_NAMES.get(self.effect_type, '?')} {state}>"


# ── FF2Device ─────────────────────────────────────────────────────────────────

class FF2Device:
    """
    Microsoft SideWinder Force Feedback 2 — HID PID driver.

    Uses python-hid (hidapi) — no sudo required (Linux needs a udev rule).

    Use as a context manager or call .close() explicitly::

        ff = FF2Device()
        try:
            e = ff.sine(period_ms=200, magnitude=180)
            time.sleep(3)
            e.free()
        finally:
            ff.close()
    """

    def __init__(self, auto_init: bool = True):
        devs = hid.enumerate(VID, PID)
        if not devs:
            raise RuntimeError(
                "Sidewinder FF2 not found (VID=0x045e PID=0x001b)\n"
                "Check: is the joystick plugged in?\n"
                "Setup: run ./setup.sh, or install hidapi + `pip install hid`.\n"
                "On Linux, /dev/hidraw* needs a udev rule — see the README."
            )
        # Prefer the Joystick collection (Generic Desktop / Joystick, usage 0x04)
        # which holds both axis input and HID PID force-feedback output reports.
        joystick = [d for d in devs if d.get('usage_page') == 1 and d.get('usage') == 4]
        target = joystick[0] if joystick else devs[0]
        try:
            self._h = hid.Device(path=target['path'])
        except Exception as exc:
            # hidapi opens exclusively on macOS, so a second client is refused.
            if "already open" in str(exc) or "exclusive" in str(exc):
                raise RuntimeError(
                    "Sidewinder FF2 is already open in another program.\n"
                    "Only one process can hold the joystick — quit the other one "
                    "(monitor.py, a notebook kernel, a game) and retry."
                ) from exc
            raise
        # Keep in default (nonblocking) mode; read() with timeout_ms handles blocking.
        # Newest input report of each kind, refreshed by _pump().
        self._last_position = None
        self._last_state = None
        self._prev_input = None  # baseline for get_events() edge detection

        if auto_init:
            self.reset()
            self.enable()
            self.set_gain(255)
            self.stop_all()

    def __enter__(self) -> "FF2Device":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        """Stop all effects and close the HID handle."""
        try:
            self.stop_all()
        except Exception:
            pass
        try:
            self._h.close()
        except Exception:
            pass

    # ── Device control ────────────────────────────────────────────────────────

    def reset(self) -> "FF2Device":
        """Send DC Device Reset, then wait 500 ms for the device to stabilise."""
        self._out([R_DEVICE_CONTROL, DC_DEVICE_RESET])
        time.sleep(0.5)
        return self

    def enable(self) -> "FF2Device":
        """Enable force feedback actuators."""
        self._out([R_DEVICE_CONTROL, DC_ENABLE_ACTUATORS])
        time.sleep(0.1)
        return self

    def disable(self) -> "FF2Device":
        self._out([R_DEVICE_CONTROL, DC_DISABLE_ACTUATORS])
        return self

    def stop_all(self) -> "FF2Device":
        self._out([R_DEVICE_CONTROL, DC_STOP_ALL_EFFECTS])
        return self

    def pause(self) -> "FF2Device":
        self._out([R_DEVICE_CONTROL, DC_DEVICE_PAUSE])
        return self

    def resume(self) -> "FF2Device":
        self._out([R_DEVICE_CONTROL, DC_DEVICE_CONTINUE])
        return self

    def set_gain(self, gain: int) -> "FF2Device":
        """Global device gain, 0-255 (scales all force output)."""
        self._out([R_DEVICE_GAIN, gain & 0xFF])
        return self

    # ── Effect allocation ─────────────────────────────────────────────────────

    def alloc(self, effect_type: int) -> Effect:
        """
        Allocate an effect block via the HID PID Create New Effect handshake:
        sends Feature Report 0x01 (Create New Effect), reads Feature Report 0x02
        (PID Block Load) to get the block index.
        """
        # Create New Effect — SET feature report
        self._h.send_feature_report(bytes([FR_CREATE_NEW_EFFECT, effect_type, 0x00, 0x00]))
        # PID Block Load — GET feature report (returns report_id + block + status + ram_lo + ram_hi).
        # On macOS the reply sometimes comes back one byte short, with the block
        # index missing: [2, status, ram_lo, ram_hi]. Parsing that as-is reads
        # ram_lo as the status. The device keeps answering with the same Block
        # Load result until the next Create New Effect, so re-read until it is whole.
        resp = b""
        for _ in range(_BLOCK_LOAD_READ_ATTEMPTS):
            resp = self._h.get_feature_report(FR_PID_BLOCK_LOAD, 6)
            if len(resp) >= 5 and resp[0] == FR_PID_BLOCK_LOAD and resp[2] in (1, 2, 3):
                break
            time.sleep(0.002)
        else:
            raise RuntimeError(
                "Effect block allocation failed: malformed PID Block Load reply "
                f"{list(resp)} (expected [2, block, status, ram_lo, ram_hi])"
            )
        block, status = resp[1], resp[2]
        if status != 1:
            raise RuntimeError(
                f"Effect block allocation failed: status={status} "
                f"({'Full' if status == 2 else 'Error'})"
            )
        return Effect(self, block, effect_type)

    # ── High-level factory methods ────────────────────────────────────────────

    def constant_force(
        self,
        angle_deg:   float = 0.0,
        magnitude:   int   = 255,
        duration_ms: int   = 32767,
        gain:        int   = 255,
        attack_ms:   int   = 0,
        attack_lvl:  int   = 0,
        fade_ms:     int   = 0,
        fade_lvl:    int   = 0,
    ) -> Effect:
        e = self.alloc(ET_CONSTANT_FORCE)
        e.set_base(duration_ms=duration_ms, gain=gain, direction_deg=angle_deg,
                   direction_enable=True, axis_x=True, axis_y=True)
        if attack_ms or fade_ms:
            e.set_envelope(attack_level=attack_lvl, attack_ms=attack_ms,
                           fade_level=fade_lvl, fade_ms=fade_ms)
        e.set_constant_force(magnitude)
        e.play()
        return e

    def ramp_force(
        self,
        angle_deg:   float = 0.0,
        start:       int   = -127,
        end:         int   = 127,
        duration_ms: int   = 2000,
        gain:        int   = 255,
    ) -> Effect:
        e = self.alloc(ET_RAMP)
        e.set_base(duration_ms=duration_ms, gain=gain, direction_deg=angle_deg,
                   direction_enable=True, axis_x=True, axis_y=True)
        e.set_ramp_force(start, end)
        e.play()
        return e

    def periodic(
        self,
        effect_type: int   = ET_SINE,
        angle_deg:   float = 0.0,
        magnitude:   int   = 255,
        offset:      int   = 0,
        phase_deg:   float = 0.0,
        period_ms:   int   = 500,
        duration_ms: int   = 32767,
        gain:        int   = 255,
        attack_ms:   int   = 0,
        attack_lvl:  int   = 0,
        fade_ms:     int   = 0,
        fade_lvl:    int   = 0,
    ) -> Effect:
        if effect_type not in PERIODIC_TYPES:
            raise ValueError(f"effect_type must be a periodic type: {PERIODIC_TYPES}")
        e = self.alloc(effect_type)
        e.set_base(duration_ms=duration_ms, gain=gain, direction_deg=angle_deg,
                   direction_enable=True, axis_x=True, axis_y=True)
        if attack_ms or fade_ms:
            e.set_envelope(attack_level=attack_lvl, attack_ms=attack_ms,
                           fade_level=fade_lvl, fade_ms=fade_ms)
        e.set_periodic(magnitude=magnitude, offset=offset,
                       phase_deg=phase_deg, period_ms=period_ms)
        e.play()
        return e

    def sine(self, angle_deg: float = 0.0, magnitude: int = 255,
             period_ms: int = 500, **kw) -> Effect:
        return self.periodic(ET_SINE, angle_deg=angle_deg, magnitude=magnitude,
                             period_ms=period_ms, **kw)

    def square(self, angle_deg: float = 0.0, magnitude: int = 255,
               period_ms: int = 500, **kw) -> Effect:
        return self.periodic(ET_SQUARE, angle_deg=angle_deg, magnitude=magnitude,
                             period_ms=period_ms, **kw)

    def triangle(self, angle_deg: float = 0.0, magnitude: int = 255,
                 period_ms: int = 500, **kw) -> Effect:
        return self.periodic(ET_TRIANGLE, angle_deg=angle_deg, magnitude=magnitude,
                             period_ms=period_ms, **kw)

    def sawtooth_up(self, angle_deg: float = 0.0, magnitude: int = 255,
                    period_ms: int = 500, **kw) -> Effect:
        return self.periodic(ET_SAWTOOTH_UP, angle_deg=angle_deg, magnitude=magnitude,
                             period_ms=period_ms, **kw)

    def sawtooth_down(self, angle_deg: float = 0.0, magnitude: int = 255,
                      period_ms: int = 500, **kw) -> Effect:
        return self.periodic(ET_SAWTOOTH_DOWN, angle_deg=angle_deg, magnitude=magnitude,
                             period_ms=period_ms, **kw)

    def condition(
        self,
        effect_type: int   = ET_SPRING,
        stiffness:   int   = 127,
        cp_offset_x: int   = 0,
        cp_offset_y: int   = 0,
        saturation:  int   = 255,
        dead_band:   int   = 0,
        duration_ms: int   = 32767,
        gain:        int   = 255,
    ) -> Effect:
        if effect_type not in CONDITION_TYPES:
            raise ValueError(f"effect_type must be a condition type: {CONDITION_TYPES}")
        e = self.alloc(effect_type)
        e.set_base(duration_ms=duration_ms, gain=gain,
                   axis_x=True, axis_y=True, direction_enable=False)
        for axis, cp in ((0, cp_offset_x), (1, cp_offset_y)):
            e.set_condition(axis=axis, cp_offset=cp,
                            pos_coeff=stiffness, neg_coeff=stiffness,
                            pos_sat=saturation, neg_sat=saturation,
                            dead_band=dead_band)
        e.play()
        return e

    def spring(self, stiffness: int = 127, cp_offset_x: int = 0,
               cp_offset_y: int = 0, saturation: int = 255,
               duration_ms: int = 32767) -> Effect:
        return self.condition(ET_SPRING, stiffness=stiffness,
                              cp_offset_x=cp_offset_x, cp_offset_y=cp_offset_y,
                              saturation=saturation, duration_ms=duration_ms)

    def damper(self, coefficient: int = 127, saturation: int = 255,
               duration_ms: int = 32767) -> Effect:
        return self.condition(ET_DAMPER, stiffness=coefficient,
                              saturation=saturation, duration_ms=duration_ms)

    def inertia(self, coefficient: int = 127, saturation: int = 255,
                duration_ms: int = 32767) -> Effect:
        return self.condition(ET_INERTIA, stiffness=coefficient,
                              saturation=saturation, duration_ms=duration_ms)

    def friction(self, level: int = 127, dead_band: int = 0,
                 duration_ms: int = 32767) -> Effect:
        return self.condition(ET_FRICTION, stiffness=level,
                              dead_band=dead_band, duration_ms=duration_ms)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _out(self, data: list) -> None:
        # data[0] is the HID output report ID; hid.write sends an interrupt-OUT report
        self._h.write(bytes(data))

    def _effect_op(self, block: int, operation: int, loop_count: int) -> None:
        self._out([R_EFFECT_OPERATION, block, operation, loop_count & 0xFF])

    def _free_block(self, block: int) -> None:
        self._out([R_PID_BLOCK_FREE, block])

    # ── Reading from the device ───────────────────────────────────────────────

    def _pump(self, timeout_ms: int) -> None:
        """
        Drain every queued input report, caching the newest of each kind.

        The device pushes position (report 1) continuously at ~125 Hz and PID
        state (report 2) only when the force state changes, both into one queue
        that hidapi buffers. Reading a single report would return the *oldest*
        packet, so a caller polling slowly gets position data seconds stale —
        drain to the end and keep the last of each.

        Waits up to timeout_ms for a first report if the queue is empty.
        """
        deadline = time.monotonic() + timeout_ms / 1000.0
        first = True
        while True:
            if first:
                wait_ms = max(1, int((deadline - time.monotonic()) * 1000))
                first = False
            else:
                wait_ms = 1  # queue already drained to here; don't block
            data = self._h.read(32, wait_ms)
            if not data:
                return
            if data[0] == R_INPUT_JOYSTICK:
                self._last_position = data
            elif data[0] == R_INPUT_PID_STATE:
                self._last_state = data

    def read_input(self, timeout_ms: int = 20) -> InputState:
        """
        Read every control at once: axes, twist, thrust lever, hat, buttons.

        Returns the newest InputState, or None if no input report has arrived
        since the device was opened. See sidewinder.controls.InputState.

            s = ff.read_input()
            if s is not None and s.button(1):
                fire()

        Expect None on the first reads. The device only sends an input report
        when something *changes*, so a perfectly still joystick sends nothing at
        all and there is nothing to report yet — and macOS refuses GET_REPORT on
        input reports, so the state cannot be fetched on demand either. Nudge the
        stick, or just tolerate None until the first report lands. After that a
        cached value is always available, and it stays correct: no report means
        nothing changed.

        Careful: pushing the stick FORWARD gives NEGATIVE s.y (-1.0 forward,
        +1.0 back toward you). Use -s.y if you want forward to be positive.
        The hat is the other way round: its dy = +1 is forward.
        """
        self._pump(timeout_ms)
        if not self._last_position:
            return None
        return decode_input_report(self._last_position)

    def read_position(self, timeout_ms: int = 20) -> tuple:
        """
        Read the current joystick X/Y position from input report 1.

        Returns (x, y) normalized to -1.0..1.0, center = 0.0:
            x = -1.0 left    / +1.0 right
            y = -1.0 FORWARD / +1.0 back (toward you)

        Note the y sign: pushing the stick away from you gives NEGATIVE y,
        following the hardware and pygame. Use -y if you want forward positive.

        Returns None if no position report has ever arrived. Shorthand for
        read_input().x / .y — see read_input() for the rest of the controls.
        """
        state = self.read_input(timeout_ms)
        return None if state is None else (state.x, state.y)

    def get_events(self, timeout_ms: int = 0) -> list:
        """
        Return button and hat events since the last call, oldest first.

        Edge-detected against the previous snapshot, so it fits an engine's
        frame loop the way pygame.event.get() does:

            for event in ff.get_events():
                if isinstance(event, ButtonDown) and event.button == 1:
                    fire()

        The first call establishes a baseline and returns [] rather than
        reporting already-held buttons as new presses. Events are only detected
        between successive calls, so a button tapped and released entirely
        between two calls is missed — poll once per frame.
        """
        state = self.read_input(timeout_ms)
        if state is None:
            return []
        events = diff_states(self._prev_input, state)
        self._prev_input = state
        return events

    def read_state(self, timeout_ms: int = 20) -> dict:
        """
        Read force-feedback status from input report 2 (PID State Report).

        The device sends this report only when the force state changes — an
        effect starting or stopping, actuators enabled/disabled, device paused —
        and macOS blocks GET_REPORT on input reports, so it cannot be polled on
        demand. The latest report seen is cached and returned here.

        Call this often. Position reports flood the same queue at ~125 Hz, so a
        state report that is not drained promptly is evicted before it is seen,
        and the cached value silently goes stale. Poll in a loop (or read right
        after changing state) to track it reliably.

        Note the grip sensor is not reported here: safety_switch does not track
        it, so there is no way to tell from this report whether force output is
        currently gated by the hand sensor.

        Returns None if no state report has arrived since the device was opened.
        Keys: device_paused, actuators_enabled, safety_switch,
        actuator_override_switch, actuator_power, effect_playing, block.
        """
        self._pump(timeout_ms)
        data = self._last_state
        if not data:
            return None
        flags, playing = data[1], data[2]
        return {
            "device_paused":            bool(flags & 0x01),
            "actuators_enabled":        bool(flags & 0x02),
            "safety_switch":            bool(flags & 0x04),
            "actuator_override_switch": bool(flags & 0x08),
            "actuator_power":           bool(flags & 0x10),
            "effect_playing":           bool(playing & 0x01),
            "block":                    playing >> 1,
        }

    def pool_info(self) -> dict:
        """
        Read the PID Pool Report (feature report 3) — static device limits.

        On the FF2: ram_pool_size=1350 bytes, simultaneous_effects_max=15.
        """
        r = self._h.get_feature_report(FR_PID_POOL, 5)
        return {
            "ram_pool_size":           r[1] | (r[2] << 8),
            "simultaneous_effects_max": r[3],
            "device_managed_pool":     bool(r[4] & 0x01),
            "shared_parameter_blocks": bool(r[4] & 0x02),
        }

    def ram_available(self) -> int:
        """Bytes free in the device effect RAM pool (from the Block Load report)."""
        r = self._h.get_feature_report(FR_PID_BLOCK_LOAD, 5)
        return r[3] | (r[4] << 8)

    def __repr__(self) -> str:
        return f"<FF2Device VID=0x{VID:04x} PID=0x{PID:04x}>"
