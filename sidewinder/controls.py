"""
sidewinder/controls.py — decoding the FF2's input report.

The joystick reports every control in one 13-byte HID input report (report 1).
Field offsets and ranges below come from the device's own HID report descriptor;
run `python3 discover.py` to print it.

Watch the Y sign: pushing the stick FORWARD reports NEGATIVE values (-512 at the
forward stop), so InputState.y is -1.0 forward and +1.0 back. The hat switch is
the opposite, with dy = +1 forward. See InputState for the full story.

    byte  1-2   X            10 bits signed   -512..511
    byte  3-4   Y            10 bits signed   -512..511
    byte  5     Rz (twist)    6 bits signed    -32..31
    byte  6     Slider        7 bits unsigned    0..127   (thrust lever;
                                                 127 = idle, 0 = full forward)
    byte  7     Hat switch    4 bits             0..7, 8+ = centered
    byte  8     Buttons 1-8   1 bit each
    byte  9-12  declared constant padding, but carries vendor data — ignored

This module only decodes bytes; FF2Device owns the device handle and reads them.
"""
import math
from dataclasses import dataclass
from typing import Optional, Tuple

# Hat switch: logical 0..7 over physical 0..315 degrees, i.e. 45 degrees per
# step, 0 = away from you. Anything outside 0..7 is the null (centred) state.
HAT_CENTERED = 8

# (dx, dy) per hat ordinal, pygame convention: dy = +1 is away from you.
_HAT_VECTORS = {
    0: (0, 1),    # forward
    1: (1, 1),    # forward-right
    2: (1, 0),    # right
    3: (1, -1),   # back-right
    4: (0, -1),   # back
    5: (-1, -1),  # back-left
    6: (-1, 0),   # left
    7: (-1, 1),   # forward-left
}

_HAT_NAMES = {
    (0, 0):   "centered",
    (0, 1):   "forward",
    (1, 1):   "forward-right",
    (1, 0):   "right",
    (1, -1):  "back-right",
    (0, -1):  "back",
    (-1, -1): "back-left",
    (-1, 0):  "left",
    (-1, 1):  "forward-left",
}

NUM_BUTTONS = 8


def _signed(value: int, bits: int) -> int:
    """Interpret an unsigned field as two's-complement of the given width."""
    half = 1 << (bits - 1)
    return value - (1 << bits) if value >= half else value


@dataclass(frozen=True)
class InputState:
    """
    A snapshot of every control on the joystick.

    *** PUSHING THE STICK FORWARD GIVES NEGATIVE y. ***

                    y = -1.0   forward, away from you
                         ^
        x = -1.0   <--   0   -->   x = +1.0
                         v
                    y = +1.0   back, toward you

    Forward is -1.0 because the hardware reports -512 at the forward stop. It
    matches pygame's axis convention and screen coordinates (+y is down). Use
    -state.y if you want forward to be positive.

    Beware: hat dy has the OPPOSITE sign, where +1 is forward. That mismatch is
    pygame's own (its axis and hat conventions disagree), and it is reproduced
    here so both drop into an engine unchanged.

    Axes are normalized floats; buttons are a tuple of 8 bools where index 0 is
    the button marked "1" on the stick. Use .button(n) for 1-based access.

        x         -1.0 left        .. +1.0 right
        y         -1.0 FORWARD     .. +1.0 back      (see above)
        twist     -1.0 left        .. +1.0 right
        throttle   0.0 idle        .. 1.0 full forward
        hat       (dx, dy), dy = +1 forward — opposite sign to y
        buttons   (b1, b2, ... b8)
    """

    x: float
    y: float
    twist: float
    throttle: float
    hat: Tuple[int, int]
    buttons: Tuple[bool, ...]

    def button(self, n: int) -> bool:
        """State of the button numbered n on the stick (1-8)."""
        if not 1 <= n <= NUM_BUTTONS:
            raise ValueError(f"button must be 1..{NUM_BUTTONS}, got {n}")
        return self.buttons[n - 1]

    @property
    def pressed(self) -> Tuple[int, ...]:
        """Numbers of every currently-held button, e.g. (1, 4)."""
        return tuple(i + 1 for i, b in enumerate(self.buttons) if b)

    @property
    def hat_name(self) -> str:
        """Hat direction as a word, e.g. 'forward-right' or 'centered'."""
        return _HAT_NAMES[self.hat]

    @property
    def hat_degrees(self) -> Optional[float]:
        """Hat bearing in degrees (0 = forward, clockwise), None if centred."""
        dx, dy = self.hat
        if (dx, dy) == (0, 0):
            return None
        return math.degrees(math.atan2(dx, dy)) % 360.0


def decode_input_report(data) -> InputState:
    """Decode one report-1 packet into an InputState."""
    x_raw = _signed(data[1] | ((data[2] & 0x03) << 8), 10)
    y_raw = _signed(data[3] | ((data[4] & 0x03) << 8), 10)
    twist_raw = _signed(data[5] & 0x3F, 6)
    throttle_raw = data[6] & 0x7F
    hat_raw = data[7] & 0x0F
    buttons_raw = data[8]

    return InputState(
        x=x_raw / 512.0,
        y=y_raw / 512.0,
        twist=twist_raw / 32.0,
        # The lever reports 127 at idle and 0 at full forward, so invert it to
        # get the conventional 0 = idle .. 1 = full thrust.
        throttle=1.0 - (throttle_raw / 127.0),
        hat=_HAT_VECTORS.get(hat_raw, (0, 0)),
        buttons=tuple(bool(buttons_raw & (1 << i)) for i in range(NUM_BUTTONS)),
    )


# ── Events ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ButtonDown:
    """A button went from released to held."""
    button: int


@dataclass(frozen=True)
class ButtonUp:
    """A button went from held to released."""
    button: int


@dataclass(frozen=True)
class HatMoved:
    """The hat switch changed direction. `hat` is the new (dx, dy)."""
    hat: Tuple[int, int]

    @property
    def hat_name(self) -> str:
        return _HAT_NAMES[self.hat]


def diff_states(old: Optional[InputState], new: InputState) -> list:
    """
    Edge-detect between two snapshots and return the events between them.

    Returns [] when old is None: the first observation establishes a baseline
    rather than reporting every held button as freshly pressed.
    """
    if old is None:
        return []

    events = []
    for i in range(NUM_BUTTONS):
        if new.buttons[i] and not old.buttons[i]:
            events.append(ButtonDown(i + 1))
        elif old.buttons[i] and not new.buttons[i]:
            events.append(ButtonUp(i + 1))
    if new.hat != old.hat:
        events.append(HatMoved(new.hat))
    return events
