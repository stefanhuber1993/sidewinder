#!/usr/bin/env python3
"""
Live view of every control on the Sidewinder FF2.

Run: venv/bin/python3 monitor.py     (Ctrl-C to quit)

Prints a continuously refreshing dashboard of the stick axes, twist, thrust
lever, hat and buttons, plus an event log. Use it to check the control mapping
against the physical hardware, or as a worked example of the input API.

No force feedback is sent, so you do not need to hold the grip.
"""
import sys
import time

from sidewinder.ff2 import FF2Device
from sidewinder.controls import ButtonDown, ButtonUp, HatMoved, NUM_BUTTONS


def bar(value, width=21, lo=-1.0, hi=1.0):
    """Render value onto a [lo, hi] scale as an ASCII slider."""
    frac = (value - lo) / (hi - lo)
    pos = int(round(max(0.0, min(1.0, frac)) * (width - 1)))
    cells = ["-"] * width
    if lo < 0:
        cells[(width - 1) // 2] = "|"     # centre tick
    cells[pos] = "O"
    return "".join(cells)


def main():
    with FF2Device(auto_init=False) as ff:
        print(f"Connected: {ff}   —  Ctrl-C to quit\n")
        log = []
        # Establish the event baseline so held buttons aren't reported as new.
        ff.get_events()

        while True:
            s = ff.read_input(timeout_ms=50)
            if s is None:
                time.sleep(0.02)
                continue

            for e in ff.get_events():
                if isinstance(e, ButtonDown):
                    log.append(f"button {e.button} down")
                elif isinstance(e, ButtonUp):
                    log.append(f"button {e.button} up")
                elif isinstance(e, HatMoved):
                    log.append(f"hat -> {e.hat_name}")
            log = log[-6:]

            held = "".join(
                f" {n} " if s.button(n) else " . "
                for n in range(1, NUM_BUTTONS + 1)
            )

            y_dir = "forward" if s.y < -0.1 else "back" if s.y > 0.1 else "centre"
            lines = [
                f"  X  {s.x:+.3f}  [{bar(s.x)}]  left(-) / right(+)",
                f"  Y  {s.y:+.3f}  [{bar(s.y)}]  FORWARD(-) / back(+)  <- {y_dir}",
                f"  twist {s.twist:+.3f} [{bar(s.twist)}]  left(-) / right(+)",
                f"  thrust {s.throttle:.3f} [{bar(s.throttle, lo=0.0, hi=1.0)}]  idle(0) / full(1)",
                "",
                f"  hat      {s.hat} {s.hat_name}   (dy=+1 is forward — opposite to Y)",
                f"  buttons  [{held}]   held: {s.pressed or '-'}",
                "",
                "  events:",
            ]
            lines += [f"    {m}" for m in log] or ["    -"]
            lines += [""] * (16 - len(lines))

            sys.stdout.write("\033[H\033[J" + "\n".join(lines) + "\n")
            sys.stdout.flush()
            time.sleep(0.03)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")
