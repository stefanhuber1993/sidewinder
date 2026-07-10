#!/usr/bin/env python3
"""
Sidewinder FF2 - Force feedback demo.
No mechanical spring — FF has full authority over stick position.
Run: sudo venv/bin/python3 demo.py
"""
import time
from sidewinder.ff2 import FF2Device, ET_CONSTANT_FORCE


def main():
    with FF2Device() as ff:
        effect = ff.alloc(ET_CONSTANT_FORCE)

        def push(angle_deg, magnitude=255):
            effect.stop()
            effect.set_base(direction_deg=angle_deg, direction_enable=True,
                            axis_x=True, axis_y=True)
            effect.set_constant_force(magnitude)
            effect.play()

        # ── Slam to each corner ──────────────────────────────────────────
        print("Corners: right → forward → left → back")
        for angle in [90, 0, 270, 180]:
            push(angle)
            time.sleep(1.0)
        effect.stop();  time.sleep(0.4)

        # ── Slow circular sweep (update direction in-flight) ─────────────
        print("Slow circle")
        push(0)
        t0 = time.time()
        while time.time() - t0 < 8:
            angle = ((time.time() - t0) / 5.0) * 360.0   # full circle in 5 s
            effect.set_base(direction_deg=angle, direction_enable=True,
                            axis_x=True, axis_y=True)
            time.sleep(0.04)
        effect.stop();  time.sleep(0.4)

        # ── Accelerating left/right slams ────────────────────────────────
        print("Accelerating slams")
        delay = 0.55
        for _ in range(18):
            push(90);  time.sleep(delay)
            push(270); time.sleep(delay)
            delay *= 0.82

        effect.free()
        print("Done!")


if __name__ == "__main__":
    main()
