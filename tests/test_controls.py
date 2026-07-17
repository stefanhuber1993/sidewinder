"""
Input-report decoding tests.

Packet layouts come from the device's HID report descriptor (`python3
discover.py`), and the button/hat/axis values were confirmed against the
hardware by exercising each control. No joystick needed to run these.
"""
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sidewinder.controls import (
    ButtonDown, ButtonUp, HatMoved, HAT_CENTERED, InputState,
    decode_input_report, diff_states,
)


def packet(x=0, y=0, twist=0, throttle=0, hat=HAT_CENTERED, buttons=0):
    """Build a report-1 packet the way the device lays it out."""
    return [
        1,
        x & 0xFF, (x >> 8) & 0x03,
        y & 0xFF, (y >> 8) & 0x03,
        twist & 0x3F,
        throttle & 0x7F,
        hat & 0x0F,
        buttons,
        0, 0, 0, 0,
    ]


# ── Axes ──────────────────────────────────────────────────────────────────────

def test_centered_stick_decodes_to_zero():
    s = decode_input_report(packet())
    assert (s.x, s.y) == (0.0, 0.0)
    assert s.twist == 0.0


def test_axes_reach_exactly_one_at_both_stops():
    # The logical range is asymmetric (-512..511). Both stops must still read
    # exactly +-1.0: dividing both sides by 512 would top out at +0.998.
    assert decode_input_report(packet(x=511)).x == 1.0    # full right
    assert decode_input_report(packet(x=512)).x == -1.0   # raw -512, full left
    assert decode_input_report(packet(y=511)).y == 1.0    # full back
    assert decode_input_report(packet(y=512)).y == -1.0   # full forward


def test_twist_reaches_exactly_one_at_both_stops():
    assert decode_input_report(packet(twist=31)).twist == 1.0    # raw 31
    assert decode_input_report(packet(twist=32)).twist == -1.0   # raw -32


def test_axes_stay_centered_at_zero():
    # Scaling each side separately must not shift the centre off zero.
    s = decode_input_report(packet(x=0, y=0, twist=0))
    assert (s.x, s.y, s.twist) == (0.0, 0.0, 0.0)


def test_axes_are_monotonic_across_the_full_range():
    xs = [decode_input_report(packet(x=raw & 0x3FF)).x
          for raw in list(range(-512, 512))]
    assert xs == sorted(xs)
    assert min(xs) == -1.0 and max(xs) == 1.0


def test_real_baseline_packet_from_hardware():
    # Captured from the live device: stick near centre, hat centred, nothing
    # pressed, and the thrust lever parked fully forward (raw 0 -> 1.0).
    s = decode_input_report([1, 7, 0, 153, 0, 0, 0, 8, 0, 0, 0, 0, 0])
    assert s.hat == (0, 0)
    assert s.pressed == ()
    assert s.throttle == 1.0
    assert abs(s.x) < 0.05          # near centre


def test_twist_decodes_6_bit_signed():
    # Raw 63 is -1 in 6-bit two's complement, not a large positive number.
    assert decode_input_report(packet(twist=63)).twist == pytest.approx(-1 / 32)
    assert decode_input_report(packet(twist=16)).twist == pytest.approx(16 / 31)


def test_twist_ignores_the_two_padding_bits():
    # Bits 6-7 of the byte are padding and must not leak into the value.
    assert decode_input_report(packet(twist=0xC0 | 10)).twist == pytest.approx(10 / 31)


# ── Thrust lever ──────────────────────────────────────────────────────────────

def test_throttle_is_inverted_so_idle_reads_zero():
    # Confirmed on hardware: the lever sends 127 sitting at idle and 0 pushed
    # fully forward, which is backwards from how anyone wants to use it.
    assert decode_input_report(packet(throttle=127)).throttle == 0.0
    assert decode_input_report(packet(throttle=0)).throttle == 1.0
    assert decode_input_report(packet(throttle=64)).throttle == pytest.approx(
        1.0 - 64 / 127)


def test_throttle_ignores_its_padding_bit():
    assert decode_input_report(packet(throttle=0x80 | 127)).throttle == 0.0


# ── Hat ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, vector, name", [
    (0, (0, 1),    "forward"),
    (1, (1, 1),    "forward-right"),
    (2, (1, 0),    "right"),
    (3, (1, -1),   "back-right"),
    (4, (0, -1),   "back"),
    (5, (-1, -1),  "back-left"),
    (6, (-1, 0),   "left"),
    (7, (-1, 1),   "forward-left"),
])
def test_hat_ordinals_map_to_directions(raw, vector, name):
    s = decode_input_report(packet(hat=raw))
    assert s.hat == vector
    assert s.hat_name == name


def test_hat_null_state_is_centered():
    # The device reports 8 when the hat is released; the descriptor declares
    # anything outside 0..7 as the null state.
    for raw in (8, 9, 15):
        assert decode_input_report(packet(hat=raw)).hat == (0, 0)
    assert decode_input_report(packet(hat=8)).hat_name == "centered"


def test_hat_degrees_are_clockwise_from_forward():
    assert decode_input_report(packet(hat=0)).hat_degrees == 0.0
    assert decode_input_report(packet(hat=2)).hat_degrees == 90.0
    assert decode_input_report(packet(hat=4)).hat_degrees == 180.0
    assert decode_input_report(packet(hat=6)).hat_degrees == 270.0
    assert decode_input_report(packet(hat=HAT_CENTERED)).hat_degrees is None


# ── Buttons ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("n", range(1, 9))
def test_button_n_maps_to_bit_n_minus_1(n):
    # Confirmed on hardware: pressing the button marked n sets bit n-1.
    s = decode_input_report(packet(buttons=1 << (n - 1)))
    assert s.button(n) is True
    assert s.pressed == (n,)
    assert sum(s.buttons) == 1


def test_multiple_buttons_held_together():
    s = decode_input_report(packet(buttons=0b10000101))
    assert s.pressed == (1, 3, 8)


def test_button_rejects_out_of_range_numbers():
    s = decode_input_report(packet())
    for n in (0, 9, -1):
        with pytest.raises(ValueError):
            s.button(n)


# ── Events ────────────────────────────────────────────────────────────────────

def state(buttons=0, hat=HAT_CENTERED):
    return decode_input_report(packet(buttons=buttons, hat=hat))


def test_first_diff_establishes_baseline_without_events():
    assert diff_states(None, state(buttons=0b1)) == []


def test_button_press_and_release_events():
    assert diff_states(state(0), state(0b1)) == [ButtonDown(1)]
    assert diff_states(state(0b1), state(0)) == [ButtonUp(1)]


def test_held_button_generates_no_repeat_events():
    assert diff_states(state(0b1), state(0b1)) == []


def test_simultaneous_press_and_release_both_reported():
    events = diff_states(state(0b0001), state(0b0010))
    assert ButtonDown(2) in events
    assert ButtonUp(1) in events


def test_hat_move_event_carries_direction():
    events = diff_states(state(hat=HAT_CENTERED), state(hat=2))
    assert events == [HatMoved((1, 0))]
    assert events[0].hat_name == "right"


def test_hat_release_reports_centered():
    assert diff_states(state(hat=2), state(hat=HAT_CENTERED)) == [HatMoved((0, 0))]


def test_axis_movement_alone_produces_no_events():
    old = decode_input_report(packet(x=0))
    new = decode_input_report(packet(x=400))
    assert diff_states(old, new) == []


def test_input_state_is_immutable():
    s = state()
    with pytest.raises(Exception):
        s.x = 1.0
