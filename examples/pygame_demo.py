#!/usr/bin/env python3
"""
Sidewinder FF2 + pygame — a small flight demo with force feedback.

pygame is not in requirements.txt (the library does not need it, only this
example does), so install it first::

    venv/bin/pip install pygame
    venv/bin/python3 examples/pygame_demo.py

Controls::

    stick        steer the ship
    thrust lever throttle (drives engine rumble)
    button 1     fire (kicks the stick)
    button 2     hold for airbrake (heavy damper)
    hat          nudge trim; the spring re-centres around the trim point
    ESC / close  quit

Shows the integration pattern: pygame owns the window, the clock and rendering,
while the FF2 supplies input and force feedback. Read state once per frame with
read_input(), and take edge-triggered events from get_events() the same way you
would from pygame.event.get(). Both are non-blocking, so neither stalls the loop.

The FF2's grip sensor gates all force output — hold the stick or you will feel
nothing.
"""
import sys
import os

try:
    import pygame
except ImportError:
    sys.exit(
        "This demo needs pygame, which the library itself does not.\n"
        "Install it with:\n\n"
        "    venv/bin/pip install pygame\n"
    )

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sidewinder.ff2 import FF2Device
from sidewinder.controls import ButtonDown, ButtonUp, HatMoved

W, H = 900, 620
TRIM_STEP = 12          # device cp_offset units per hat nudge


def main():
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Sidewinder FF2 — pygame demo")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("menlo,monospace", 15)
    big = pygame.font.SysFont("menlo,monospace", 22, bold=True)

    ff = FF2Device()
    ff.get_events()  # baseline, so buttons already held don't fire on frame 1

    # Centring spring — its centre point doubles as pitch/roll trim.
    spring = ff.spring(stiffness=70, saturation=200)
    trim_x = trim_y = 0

    def apply_trim():
        for axis, cp in ((0, trim_x), (1, trim_y)):
            spring.set_condition(axis=axis, cp_offset=cp,
                                 pos_coeff=70, neg_coeff=70,
                                 pos_sat=200, neg_sat=200)

    # Engine rumble — magnitude follows the thrust lever each frame.
    rumble = ff.sine(angle_deg=90, magnitude=0, period_ms=60)
    fire_kick = None
    airbrake = None

    ship = pygame.Vector2(W / 2, H / 2)
    shots = []
    stars = [(i * 137 % W, i * 271 % H, (i % 3) + 1) for i in range(120)]
    running = True

    while running:
        dt = clock.tick(60) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        s = ff.read_input()
        if s is None:
            continue

        # ── Joystick events, alongside pygame's own ──────────────────────────
        for e in ff.get_events():
            if isinstance(e, ButtonDown):
                if e.button == 1:
                    shots.append([pygame.Vector2(ship), 0.0])
                    if fire_kick is None:
                        # Brief kick backwards, fading out.
                        fire_kick = ff.constant_force(
                            angle_deg=0, magnitude=200,
                            duration_ms=120, fade_ms=120)
                elif e.button == 2 and airbrake is None:
                    airbrake = ff.damper(coefficient=110, saturation=255)
            elif isinstance(e, ButtonUp):
                if e.button == 2 and airbrake is not None:
                    airbrake.free()
                    airbrake = None
            elif isinstance(e, HatMoved):
                dx, dy = e.hat
                if (dx, dy) != (0, 0):
                    trim_x = max(-127, min(127, trim_x + dx * TRIM_STEP))
                    # hat dy is +1 forward; cp_offset y is +1 back, so negate
                    trim_y = max(-127, min(127, trim_y - dy * TRIM_STEP))
                    apply_trim()

        if fire_kick is not None and not shots:
            fire_kick.free()
            fire_kick = None

        # ── Flight model ─────────────────────────────────────────────────────
        speed = 40 + s.throttle * 460
        ship.x += s.x * speed * dt
        ship.y += s.y * speed * dt
        ship.x = max(20, min(W - 20, ship.x))
        ship.y = max(20, min(H - 20, ship.y))
        heading = s.twist * 45.0

        # Engine rumble tracks the lever; updating a playing effect in place.
        rumble.set_periodic(magnitude=int(s.throttle * 90), period_ms=60)

        for shot in shots:
            shot[0].y -= 600 * dt
            shot[1] += dt
        shots = [sh for sh in shots if sh[0].y > -10 and sh[1] < 3]

        # ── Render ───────────────────────────────────────────────────────────
        screen.fill((8, 8, 18))
        for x, y, r in stars:
            pygame.draw.circle(screen, (60, 60, 90), (x, y), r)

        for shot, _ in shots:
            pygame.draw.line(screen, (255, 220, 120),
                             shot, shot + pygame.Vector2(0, 12), 3)

        pts = [pygame.Vector2(0, -18), pygame.Vector2(13, 14), pygame.Vector2(-13, 14)]
        rot = [p.rotate(heading) + ship for p in pts]
        pygame.draw.polygon(screen, (90, 200, 255), rot)
        pygame.draw.polygon(screen, (200, 240, 255), rot, 2)

        # Thrust bar
        pygame.draw.rect(screen, (40, 40, 60), (24, 90, 22, 300))
        h = int(s.throttle * 300)
        pygame.draw.rect(screen, (255, 140, 60), (24, 90 + 300 - h, 22, h))
        screen.blit(font.render("THR", True, (160, 160, 180)), (22, 396))

        held = " ".join(str(n) for n in s.pressed) or "-"
        rows = [
            f"x {s.x:+.2f}   y {s.y:+.2f}   twist {s.twist:+.2f}",
            f"thrust {s.throttle:.2f}   hat {s.hat_name}",
            f"buttons held: {held}",
            f"trim ({trim_x:+d}, {trim_y:+d})   [hat to trim]",
            f"airbrake: {'ON' if airbrake else 'off'}   [hold button 2]",
        ]
        for i, r in enumerate(rows):
            screen.blit(font.render(r, True, (170, 180, 200)), (80, 24 + i * 19))
        screen.blit(big.render("button 1 = fire", True, (255, 220, 120)), (W - 220, 24))
        screen.blit(font.render("hold the grip or you feel nothing",
                                True, (120, 120, 140)), (W - 300, 54))

        pygame.display.flip()

    # ── Cleanup: free every effect, then the device ──────────────────────────
    for e in (fire_kick, airbrake, rumble, spring):
        if e is not None:
            e.free()
    ff.close()
    pygame.quit()


if __name__ == "__main__":
    main()
