#!/usr/bin/env python3
"""
Sidewinder FF2 — force feedback demo.

Run: venv/bin/python3 demo.py     (no sudo — see README)

The stick has no mechanical centring spring, so force feedback has full
authority over where it sits. Hold the grip throughout: the FF2 has a hand
sensor and cuts all motor output the moment you let go.

Direction angles (measured on the device, not assumed from the spec):
    0° = back (toward you)   90° = left   180° = forward (away)   270° = right
"""
import time

from sidewinder.ff2 import FF2Device, ET_CONSTANT_FORCE

# angle -> label, as measured by pushing each direction and reading the axes back
CARDINALS = [(270, "right"), (180, "forward"), (90, "left"), (0, "back")]


def corners(ff, effect):
    """Slam to each cardinal direction in turn."""
    print("Corners: " + " → ".join(name for _, name in CARDINALS))
    for angle, name in CARDINALS:
        effect.stop()
        effect.set_base(direction_deg=angle, direction_enable=True,
                        axis_x=True, axis_y=True)
        effect.set_constant_force(255)
        effect.play()
        time.sleep(1.0)
        pos = ff.read_position(timeout_ms=100)
        if pos:
            print(f"  {name:>7} ({angle:>3}°) → x={pos[0]:+.2f} y={pos[1]:+.2f}")
    effect.stop()
    time.sleep(0.4)


def circle(effect):
    """Sweep the force direction through a full circle, updating in-flight."""
    print("Slow circle")
    effect.set_constant_force(255)
    effect.play()
    t0 = time.time()
    while time.time() - t0 < 8:
        angle = ((time.time() - t0) / 5.0) * 360.0   # full circle every 5 s
        effect.set_base(direction_deg=angle, direction_enable=True,
                        axis_x=True, axis_y=True)
        time.sleep(0.04)
    effect.stop()
    time.sleep(0.4)


def spring_positions(ff):
    """
    Walk a spring's centre point around the stick plane.

    A spring pulls the stick toward its centre point, so moving the centre
    drags the stick with it — the stick is parked at each position rather than
    shoved at it, and it resists you pushing it away.
    """
    print("Spring: parking the stick at a sequence of centre points")
    positions = [
        (0, 0, "centre"),
        (100, 0, "right"),
        (0, -100, "forward"),
        (-100, 0, "left"),
        (0, 100, "back"),
        (90, -90, "forward-right"),
        (-90, -90, "forward-left"),
        (-90, 90, "back-left"),
        (90, 90, "back-right"),
        (0, 0, "centre"),
    ]
    # direction_enable=False so each axis is driven by its own condition block
    with ff.spring(stiffness=127, saturation=255) as e:
        for cx, cy, name in positions:
            e.set_condition(axis=0, cp_offset=cx, pos_coeff=127, neg_coeff=127,
                            pos_sat=255, neg_sat=255)
            e.set_condition(axis=1, cp_offset=cy, pos_coeff=127, neg_coeff=127,
                            pos_sat=255, neg_sat=255)
            time.sleep(1.2)
            pos = ff.read_position(timeout_ms=100)
            shown = f"x={pos[0]:+.2f} y={pos[1]:+.2f}" if pos else "(no report)"
            print(f"  {name:>13}: cp=({cx:>4},{cy:>4}) → {shown}")


def spring_stiffness_sweep(ff):
    """Same centre, rising stiffness — the stick gets progressively harder to move."""
    print("Spring: stiffness sweep at centre (try pushing the stick)")
    with ff.spring(stiffness=0, saturation=255) as e:
        for stiffness in (0, 32, 64, 96, 127):
            for axis in (0, 1):
                e.set_condition(axis=axis, cp_offset=0,
                                pos_coeff=stiffness, neg_coeff=stiffness,
                                pos_sat=255, neg_sat=255)
            print(f"  stiffness {stiffness:>3}")
            time.sleep(1.5)


def sine_vibration(ff):
    """Sine rumble: slow/heavy, then fast/buzzy, then a fading pulse."""
    print("Sine vibration")
    for period_ms, magnitude, label in [
        (500, 255, "slow heavy shake  (2 Hz)"),
        (200, 200, "medium rumble     (5 Hz)"),
        (60,  160, "fast buzz        (16 Hz)"),
        (20,  120, "high buzz        (50 Hz)"),
    ]:
        print(f"  {label}")
        with ff.sine(angle_deg=90, magnitude=magnitude, period_ms=period_ms) as e:
            time.sleep(2.0)
        time.sleep(0.2)

    # Envelope: full-strength buzz that fades out over 1.5 s
    print("  fading pulse (envelope)")
    with ff.sine(angle_deg=90, magnitude=255, period_ms=40,
                 duration_ms=1500, fade_ms=1500, fade_lvl=0):
        time.sleep(1.8)


def accelerating_slams(effect):
    """Left/right slams that speed up until they blur into a buzz."""
    print("Accelerating slams")
    delay = 0.55
    for _ in range(18):
        for angle in (90, 270):
            effect.stop()
            effect.set_base(direction_deg=angle, direction_enable=True,
                            axis_x=True, axis_y=True)
            effect.set_constant_force(255)
            effect.play()
            time.sleep(delay)
        delay *= 0.82
    effect.stop()


def main():
    with FF2Device() as ff:
        print(f"Connected: {ff}")
        print(f"Pool: {ff.pool_info()}")
        print("\n*** Hold the stick — the hand sensor gates all force output ***")
        for i in range(5, 0, -1):
            print(f"    starting in {i}...", flush=True)
            time.sleep(1)
        print()

        effect = ff.alloc(ET_CONSTANT_FORCE)
        effect.set_base(direction_deg=0, direction_enable=True,
                        axis_x=True, axis_y=True)

        corners(ff, effect)
        circle(effect)
        accelerating_slams(effect)
        effect.free()

        spring_positions(ff)
        spring_stiffness_sweep(ff)
        sine_vibration(ff)

        print("\nDone!")


if __name__ == "__main__":
    main()
