# Sidewinder FF2 — Force Feedback on macOS

Python driver for the **Microsoft SideWinder Force Feedback 2** joystick on macOS.
Send force effects and read every control — stick, twist, thrust lever, hat and
buttons — from a script, a game loop, or a Jupyter notebook, without sudo.

---

## Hardware

**Microsoft SideWinder Force Feedback 2** — USB VID `0x045e` / PID `0x001b`.

Speaks **USB HID PID** (Physical Interface Device), the standard USB force
feedback spec. It is *not* an I-Force device — that protocol belongs to
Logitech/Thrustmaster.

> **Hold the stick.** The FF2 has a hand sensor in the grip and cuts all motor
> output the moment you let go. Effects will upload, report `effect_playing`, and
> produce no force at all if you are not holding it. This is the single most
> confusing thing about the device.

---

## Architecture

```
your code  →  sidewinder/ff2.py  →  hid (hidapi)  →  IOKit HID Manager  →  FF2
                                                            ↕
                                                     macOS joystick driver
                                                     (axes/buttons keep working)
```

The driver talks to the device through **hidapi**, which on macOS is backed by the
**IOKit HID Manager** — an API built for user-space HID access. It shares the
device with the OS driver rather than claiming it, so:

- **No sudo.** Nothing needs root.
- **No exclusive access.** The OS joystick driver keeps reading axes and buttons
  normally; force output reports flow alongside its input.

(A `pyusb`/`libusb` approach would instead claim the device exclusively and detach
the IOHIDFamily kernel driver — which is what requires root.)

## Setup

```bash
brew install hidapi      # native hidapi library (IOKit backend)
./setup.sh               # creates venv, installs Python deps
source venv/bin/activate

python3 demo.py          # runs the effect demo — hold the stick
python3 monitor.py       # live view of every control
jupyter lab notebook.ipynb   # interactive effect lab with live sliders
```

---

## Sending force effects

Every effect follows the same HID PID handshake: allocate a block, upload its
parameters, then play it. The factory methods below do all three and return an
already-playing `Effect`.

```python
from sidewinder.ff2 import FF2Device
import time

ff = FF2Device()          # opens device, resets, enables actuators, gain 255

e = ff.constant_force(angle_deg=270, magnitude=255)
time.sleep(2)
e.free()                  # stop and release the block

ff.close()
```

Effects are context managers, which is the easy way to not leak blocks:

```python
with FF2Device() as ff:
    with ff.sine(angle_deg=90, magnitude=200, period_ms=200):
        time.sleep(3)
```

### Direction angles

Measured on the device by pushing each angle and reading the axes back — the FF2
does not use the compass convention you might assume:

| Angle | Pushes the stick |
|---|---|
| `0°` | back (toward you) |
| `90°` | left |
| `180°` | forward (away) |
| `270°` | right |

Direction only applies when `direction_enable=True` (constant, ramp, periodic).
Condition effects (spring/damper/inertia/friction) set `direction_enable=False`
and drive each axis from its own condition block instead.

### What each call puts on the wire

Bytes below are exactly what the driver writes; the first byte is always the HID
report ID. `FEATURE SET` is a feature report, `OUT` is an interrupt-OUT report.

**`FF2Device()`** — reset, enable actuators, full gain, clear any stale effects:

```
OUT  0c 04        Device Control: Device Reset
OUT  0c 01        Device Control: Enable Actuators
OUT  0d ff        Device Gain: 255
OUT  0c 03        Device Control: Stop All Effects
```

**`ff.constant_force(angle_deg=270, magnitude=255)`** — steady push to the right:

```
FEATURE SET  01 01 00 00
             └ Create New Effect: type 1 (constant force)
OUT  01 01 01 ff 7f 00 00 00 00 ff ff 07 bf 00 00 00
     │  │  │  └duration 32767  │  │  │  │  └direction 0xbf = 270°
     │  │  └effect type 1      │  │  │  └axes X|Y + direction enable (0b111)
     │  └block 1               │  │  └trigger button: none
     └Set Effect               │  └gain 255
                               └trigger repeat + sample period
OUT  05 01 ff 00              Set Constant Force: block 1, magnitude 255 (int16)
OUT  0a 01 01 ff              Effect Operation: block 1, Start, loop 255
```

**`ff.sine(angle_deg=90, magnitude=200, period_ms=200)`** — 5 Hz rumble to the left:

```
FEATURE SET  01 04 00 00      Create New Effect: type 4 (sine)
OUT  01 01 04 ff 7f 00 00 00 00 ff ff 07 40 00 00 00     Set Effect (dir 0x40 = 90°)
OUT  04 01 c8 00 00 c8 00     Set Periodic: magnitude 200, offset 0, phase 0, period 200
OUT  0a 01 01 ff              Effect Operation: Start
```

**`ff.spring(stiffness=127, cp_offset_x=100)`** — spring pulling toward x=+100:

```
FEATURE SET  01 08 00 00      Create New Effect: type 8 (spring)
OUT  01 01 08 ff 7f 00 00 00 00 ff ff 03 00 00 00 00     Set Effect (axes 0b011, no direction)
OUT  03 01 00 64 7f 7f ff ff 00
     │  │  │  │  │  │  │  │  └dead band 0
     │  │  │  │  │  │  └──┴positive/negative saturation 255
     │  │  │  │  └──┴positive/negative coefficient 127 (stiffness)
     │  │  │  └centre point offset 100
     │  │  └axis 0 (X)
     │  └block 1
     └Set Condition
OUT  03 01 01 00 7f 7f ff ff 00     Set Condition: axis 1 (Y), centre 0
OUT  0a 01 01 ff                    Effect Operation: Start
```

**`ff.damper(coefficient=80)`** — resists movement on both axes:

```
FEATURE SET  01 09 00 00      Create New Effect: type 9 (damper)
OUT  01 01 09 ff 7f 00 00 00 00 ff ff 03 00 00 00 00
OUT  03 01 00 00 50 50 ff ff 00     Set Condition: axis 0, coefficient 80
OUT  03 01 01 00 50 50 ff ff 00     Set Condition: axis 1, coefficient 80
OUT  0a 01 01 ff
```

**Housekeeping:**

```python
ff.set_gain(200)   # OUT  0d c8      scales all force output
e.stop()           # OUT  0a 03 03 00    Effect Operation: block 3, Stop
e.free()           # OUT  0a 03 03 00 + OUT 0b 03    stop, then PID Block Free
ff.stop_all()      # OUT  0c 03
ff.pause()         # OUT  0c 05  /  ff.resume() → 0c 06
```

### Updating an effect while it plays

Re-uploading a parameter report changes a playing effect in place — no need to
stop, free, and reallocate. This is how `demo.py` sweeps a force in a circle:

```python
e = ff.constant_force(angle_deg=0, magnitude=255)
for angle in range(0, 360, 5):
    e.set_base(direction_deg=angle, direction_enable=True, axis_x=True, axis_y=True)
    time.sleep(0.04)
```

### Available effects

`constant_force`, `ramp_force`, `sine`, `square`, `triangle`, `sawtooth_up`,
`sawtooth_down`, `spring`, `damper`, `inertia`, `friction`. Periodic effects
accept `attack_ms`/`fade_ms` envelopes; `periodic()` and `condition()` are the
generic forms.

---

## Reading the controls

The joystick sends every control in one input report, so a single
`read_input()` gives you the whole stick. Reading needs no force feedback and no
grip on the stick, and doesn't disturb the OS joystick driver.

```python
s = ff.read_input()

s.x, s.y          # stick   — note: y is NEGATIVE forward, see below
s.twist           # rudder twist
s.throttle        # thrust lever
s.hat             # (dx, dy)
s.button(1)       # True while the button marked 1 is held
s.pressed         # (1, 4) — every button currently held
```

> ### ⚠️ Pushing the stick forward gives you **negative** `y`
>
> ```
>            y = -1.0        push forward, away from you
>                 ↑
>   x = -1.0  ←   0   →  x = +1.0
>                 ↓
>            y = +1.0        pull back, toward you
> ```
>
> This trips everyone up. If your ship flies backwards, this is why — use
> `-s.y` when you want "forward is positive":
>
> ```python
> pitch_up = -s.y          # +1.0 when the stick is pushed forward
> ship.y   += s.y * speed  # screen coords: +y is down, so this already matches
> ```
>
> It follows the hardware, which reports `-512` at the forward stop, and matches
> both pygame's axis convention and screen coordinates (where `+y` is down).
> **The hat is the opposite:** its `dy = +1` *is* forward. That inconsistency is
> pygame's, and this library reproduces it so both drop into an engine unchanged.

### Control map

Verified against the hardware by exercising each control and watching the report:

| Control | Field | Range |
|---|---|---|
| Stick left/right | `x` | `-1.0` left … `+1.0` right |
| **Stick forward/back** | **`y`** | **`-1.0` forward (away) … `+1.0` back (toward you)** |
| Twist / rudder | `twist` | `-1.0` left … `+1.0` right |
| Thrust lever | `throttle` | `0.0` idle … `1.0` full forward |
| 8-way hat | `hat` | `(dx, dy)`, each `-1/0/+1`; `(0, 0)` centred — `dy = +1` is forward |
| Buttons 1–8 | `button(n)`, `buttons`, `pressed` | `bool` |

**Buttons** are numbered as printed on the stick: button *n* is `buttons[n-1]`,
and `button(n)` takes the number directly. All 8 are independent bits, so any
combination can be held at once.

**The hat** reads `(0, 0)` when centred and one of eight directions otherwise.
`hat_name` gives the direction as a word (`'forward-right'`), `hat_degrees`
gives a bearing (`0°` forward, clockwise, `None` when centred):

```python
if s.hat == (1, 0):
    print("hat pushed right")
print(s.hat_name)       # e.g. 'forward-left', or 'centered'
```

### Events

`get_events()` edge-detects button and hat changes between calls, which is the
shape an engine's frame loop wants:

```python
from sidewinder.controls import ButtonDown, ButtonUp, HatMoved

for event in ff.get_events():
    if isinstance(event, ButtonDown) and event.button == 1:
        fire()
    elif isinstance(event, HatMoved):
        print("hat ->", event.hat_name)
```

The first call establishes a baseline and returns `[]`, so buttons already held
at startup aren't reported as fresh presses. Events are detected *between* calls,
so a button tapped and released entirely between two calls is missed — poll once
per frame and that never happens.

### Using it with pygame

pygame owns the window and the clock; the FF2 supplies input and force. Both
`read_input()` and `get_events()` are non-blocking, so they drop straight into a
frame loop:

```python
ff = FF2Device()
ff.get_events()                      # baseline

while running:
    for event in pygame.event.get():  # keyboard, window
        ...
    s = ff.read_input()               # joystick state, this frame
    for e in ff.get_events():         # joystick edges
        if isinstance(e, ButtonDown) and e.button == 1:
            fire()

    ship.x += s.x * s.throttle * speed * dt
    rumble.set_periodic(magnitude=int(s.throttle * 90), period_ms=60)
    clock.tick(60)
```

`examples/pygame_demo.py` is a complete, runnable version: fly a ship with the
stick, throttle with the lever, fire on button 1 (which kicks the stick), hold
button 2 for an airbrake damper, and trim with the hat.

```bash
pip install pygame
venv/bin/python3 examples/pygame_demo.py
```

> **Don't reach for `pygame.joystick` for this device.** On macOS, SDL doesn't
> enumerate the FF2 here at all (`get_count()` returns 0) and has no force
> feedback for it either way. Read input through this library and you get the
> controls and the forces from one handle.

### Stick position only

`read_position()` is shorthand for the two axes:

```python
x, y = ff.read_position()      # same as read_input().x, .y
```

Both it and `read_input()` drain everything queued since the last call and return
the newest sample, so a slow polling loop gets the current position rather than
replaying a backlog. They return `None` only if no report has arrived since the
device was opened.

### Seeing it live

`monitor.py` prints a live dashboard of every control plus an event log — the
quickest way to check the mapping against your own hardware:

```bash
venv/bin/python3 monitor.py
```

### Force feedback status

`read_state()` decodes input report 2, the **PID State Report**:

```python
ff.read_state()
# {'device_paused': False, 'actuators_enabled': True, 'safety_switch': False,
#  'actuator_override_switch': False, 'actuator_power': True,
#  'effect_playing': True, 'block': 2}
```

The device sends this report **only when the force state changes** — an effect
starting or stopping, actuators being enabled/disabled, the device pausing — and
macOS blocks `GET_REPORT` on input reports, so it cannot be asked for on demand.
The driver caches the last one it saw and returns that.

**Poll it often.** Position reports share the same queue at ~125 Hz, so a state
report that isn't drained promptly is evicted before you see it and the cached
value silently goes stale. Drained in a tight loop it tracks every transition:

```python
e = ff.sine(period_ms=200)          # → effect_playing True,  block 2
e.stop()                            # → effect_playing False, block 2
```

Poll it once a second, though, and you will simply miss both.

> The **grip sensor is not visible here**. `safety_switch` does not track it —
> gripping and releasing the stick produces no state report at all. Nothing in
> this report tells you whether force output is currently gated by the hand
> sensor; the only way to know is that the stick doesn't move.

### Device limits

```python
ff.pool_info()      # {'ram_pool_size': 1350, 'simultaneous_effects_max': 15,
                    #  'device_managed_pool': True, 'shared_parameter_blocks': False}
ff.ram_available()  # bytes free in the effect pool, e.g. 1303
```

---

## Protocol reference

Report IDs as declared by this device's HID report descriptor. Run
`python3 discover.py` to print the full field layout, bit widths, and logical
ranges straight from the hardware.

| Report | ID | Direction | Purpose |
|---|---|---|---|
| Joystick input | 0x01 | IN | Axes, twist, thrust, hat, buttons — continuous |
| PID State | 0x02 | IN | FF status — sent only on state change |
| Set Effect | 0x01 | OUT | Effect type, duration, direction, gain |
| Set Envelope | 0x02 | OUT | Attack/fade shaping |
| Set Condition | 0x03 | OUT | Spring/damper coefficients, per axis |
| Set Periodic | 0x04 | OUT | Magnitude, offset, phase, period |
| Set Constant Force | 0x05 | OUT | Magnitude for constant push |
| Set Ramp Force | 0x06 | OUT | Ramp start/end |
| Download Force Sample | 0x08 | OUT | Direct X/Y force sample |
| Effect Operation | 0x0a | OUT | Start / start solo / stop |
| PID Block Free | 0x0b | OUT | Release an effect block |
| Device Control | 0x0c | OUT | Reset, enable/disable, stop all, pause |
| Device Gain | 0x0d | OUT | Overall FF strength |
| Create New Effect | 0x01 | FEATURE SET | Allocate an effect block |
| PID Block Load | 0x02 | FEATURE GET | Block index, status, RAM available |
| PID Pool | 0x03 | FEATURE GET | Pool size, simultaneous effect limit |

Input report 1 is 13 bytes and packs the controls at bit-level offsets:

| Byte | Field | Bits | Logical range |
|---|---|---|---|
| 1–2 | X | 10 | `-512..511` |
| 3–4 | Y | 10 | `-512..511` |
| 5 | Rz (twist) | 6 | `-32..31` |
| 6 | Slider (thrust) | 7 | `0..127` — **127 = idle, 0 = full** |
| 7 | Hat switch | 4 | `0..7`, `8` = centred (null state) |
| 8 | Buttons 1–8 | 1 each | bit *n−1* = button *n* |
| 9–12 | declared constant | 8 each | see note below |

---

## Known issues / gotchas

- **No force unless you hold the grip.** The hand sensor gates all motor output.
  Everything else — allocation, `effect_playing`, position reads — behaves
  normally while producing zero force, which makes this look like a driver bug.
- **Direction angles are not the compass convention.** `0°` is back and `90°` is
  left, measured on the device. Don't assume; read the position back.
- **Forward on the stick is negative `y`.** Push away from you and `y` goes to
  `-1.0`, not `+1.0`. The hardware reports `-512` at the forward stop and the
  driver passes that through, matching pygame and screen coordinates. Use `-s.y`
  if you want forward to be positive. Confusingly, the **hat is the opposite** —
  its `dy = +1` is forward, because that is pygame's hat convention.
- **The thrust lever reports backwards.** It sends `127` at idle and `0` pushed
  fully forward. `read_input()` inverts it so `throttle` is the conventional
  `0.0` idle … `1.0` full; the raw byte is the other way round.
- **The hat has a null state, not a ninth value.** Released, it reports `8` —
  outside the declared `0..7` logical range, exactly as the descriptor's Null
  State flag says. Treat anything outside `0..7` as centred rather than
  expecting a specific number.
- **SDL/pygame can't see this joystick on macOS.** `pygame.joystick.get_count()`
  returns 0 here, and SDL has no force feedback for the FF2 anyway. Use
  `read_input()` for the controls and let pygame keep the window.
- **Input report bytes 9–12 are declared constant but aren't.** The descriptor
  marks them as padding, yet they carry live signed values that track stick
  motion — undocumented vendor data. The driver ignores them; don't rely on them.
- **PID state can't be polled.** macOS rejects `GET_REPORT` on input reports
  (`IOHIDDeviceGetReport` fails), so `read_state()` depends on the device pushing
  report 2 when the state changes rather than asking for it.
- **State reports get evicted if you read slowly.** Report 2 shares the input
  queue with report 1 at ~125 Hz, and the queue is finite. Poll once a second and
  the flood of position data drops the state change before you drain it — the
  cached state then goes stale without any error. Drain in a tight loop to track
  it.
- **Input reports are queued, so reads can be stale.** hidapi buffers reports
  while you aren't reading, and a plain read returns the *oldest* one — poll
  slowly and you get position data seconds behind reality. `read_position()`
  drains to the newest sample for you.
- **Effect blocks are a finite pool** — 1350 bytes, 15 simultaneous effects.
  Always `free()` effects (or use the context manager); allocation raises
  `RuntimeError: ... Full` once the pool is exhausted.
- **Report IDs are device-specific.** HID PID declares them in the report
  descriptor, not the spec. Verify with `discover.py` before trusting any layout.
- **Multiple HID collections.** `hid.enumerate()` returns two entries for this
  VID/PID (usage 1 and usage 4). The driver picks the Joystick collection
  (usage page 1, usage 4) — the one carrying both axes and the PID reports.
- **hidapi `write()` takes the report ID as byte 0.** The FF2 uses numbered
  reports (0x01–0x0d), so no zero-prefix padding is needed.
- **No macOS game support.** macOS's `ForceFeedback.framework` is deprecated and
  SDL2 never properly implemented it for this device, so effects have to be driven
  directly as here.

---

## Repo layout

| Path | What it is |
|---|---|
| `sidewinder/ff2.py` | The driver — HID PID protocol, effects, device handle |
| `sidewinder/controls.py` | Input decoding — `InputState`, hat/button maps, events |
| `demo.py` | Effect demo: slams, circle sweep, spring positions, sine vibration |
| `monitor.py` | Live dashboard of every control + event log |
| `discover.py` | Dumps and parses the HID report descriptor from the hardware |
| `examples/pygame_demo.py` | Playable pygame integration with force feedback |
| `notebook.ipynb` | Interactive effect lab with live sliders |
| `theremin.ipynb` | Haptic theremin — springs as note frets |
| `tests/` | Wire-encoding and input-decoding tests (no hardware needed) |

## Tests

```bash
venv/bin/python -m pytest tests/ -q
```

The suite fakes the `hid` module and asserts the exact bytes the driver puts on
the wire against the layouts in the device's own report descriptor, so it runs
without the joystick plugged in.
