# Sidewinder FF2 — USB Force Feedback Foundation

**Date:** 2026-05-18  
**Goal:** Establish USB communication with the Microsoft Sidewinder FF2 joystick and run a demo that cycles through several force effect types, confirming the link works and providing a modular base to build hackable force feedback on top of.

---

## Architecture

Modular layout — each layer has one job and is independently usable:

```
sidewinder/
├── setup.sh              # creates venv, pip-installs pyusb
├── requirements.txt      # pyusb
├── sidewinder/
│   ├── device.py         # USB open/close, kernel driver detach/re-attach
│   ├── iforce.py         # I-Force packet construction and send
│   └── effects.py        # named effect builders (constant, spring, sine, etc.)
└── demo.py               # runs a sequence of effects to show communication works
```

- `device.py` knows about USB, nothing else.
- `iforce.py` knows about the I-Force wire protocol, nothing else.
- `effects.py` composes `iforce.py` primitives into named, parameterised effects.
- `demo.py` imports from `effects.py` and orchestrates the demo sequence.

Adding a new effect type means adding a function to `effects.py` — no other file changes needed.

---

## USB Device

- **Vendor ID:** `0x045e` (Microsoft)
- **Product ID:** `0x001b` (Sidewinder Force Feedback 2)
- Located via `usb.core.find(idVendor=0x045e, idProduct=0x001b)`

---

## macOS Driver Detachment

macOS IOHIDFamily claims the device at boot. `device.py` calls `device.detach_kernel_driver(0)` before claiming the interface, and re-attaches via `device.attach_kernel_driver(0)` in a finally block so the joystick works normally after the demo.

---

## I-Force Packet Format

Every command is a byte array: `[command_id, payload_len, ...payload_bytes]`

Sent via `device.write(endpoint_out, packet)` on the interrupt OUT endpoint (endpoint index 1).

| Purpose              | Cmd ID | Payload len | Notes                           |
|----------------------|--------|-------------|---------------------------------|
| Enable FF            | `0x42` | 1           | `[0x01]` to enable              |
| Set gain             | `0x43` | 1           | `[0xff]` = max gain             |
| Upload effect        | `0x01` | 14          | Type, duration, slot, direction |
| Upload magnitude     | `0x03` | 3           | Slot, force lo, force hi        |
| Upload period        | `0x04` | 7           | For sine/square/triangle        |
| Upload condition     | `0x05` | 10          | For spring/damper               |
| Play / stop effect   | `0x41` | 3           | Slot, start/stop flag, repeats  |

Exact payload byte layouts are derived from Linux kernel `drivers/input/joystick/iforce/iforce-ff.c` during implementation.

---

## Demo Sequence

`demo.py` runs effects one at a time with a pause between each so you can feel the difference:

```
1. Enable FF, set gain to max
2. Constant force (resist right)   — 2s
3. Constant force (resist left)    — 2s
4. Spring (centre-return)          — 3s
5. Sine wave (rumble)              — 3s
6. Stop all, re-attach driver
```

Each step prints what it's doing so you can correlate what you feel with what was sent.

---

## Error Handling

- Device not found: print "Is the joystick plugged in?" and exit.
- Detach fails: catch `usb.core.USBError` and continue — driver may not be loaded.
- All USB writes in try/finally to guarantee re-attach on any failure.

---

## Success Criteria

Running `python3 demo.py` produces clearly distinct physical sensations for each effect type, confirming bidirectional I-Force communication is working.
