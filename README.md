# Sidewinder FF2 — Force Feedback on macOS

Python tooling to drive force feedback on the **Microsoft SideWinder Force Feedback 2** joystick from macOS, with a long-term goal of a flight-sim bridge for X-Plane.

---

## Hardware

**Microsoft SideWinder Force Feedback 2**
- USB VID `0x045e` / PID `0x001b`
- Protocol: **USB HID PID** (Physical Interface Device) — the standardised USB HID force feedback spec
- NOT an I-Force device (that protocol is used by Logitech/Thrustmaster, not Microsoft)

---

## Current State — PyUSB demo

The current code uses **PyUSB + libusb** to claim the device directly and send raw **HID PID output reports**, bypassing macOS's HID kernel driver.

This is good for:
- Exploring which HID PID reports the device responds to
- Quickly iterating on force values and effect types without a compile step
- Proving communication works before committing to a heavier architecture

Limitation: `libusb` requires **exclusive USB access** — while the demo runs, macOS loses joystick axis/button input. Fine for a standalone test, not suitable for running alongside a simulator.

### Setup

```bash
brew install libusb      # if not already installed
./setup.sh               # creates venv, installs pyusb
source venv/bin/activate
sudo venv/bin/python3 demo.py
```

`sudo` is required so libusb can detach the macOS HID kernel driver.

### Architecture

```
demo.py          orchestrates the demo sequence
sidewinder/
  device.py      USB open/close, kernel driver detach/reattach
  hidpid.py      HID PID report construction and send
  effects.py     named effect builders (constant, sine, spring)
tests/           unit tests for report construction and effect builders
```

---

## Protocol: USB HID PID

The SideWinder FF2 implements the [USB HID PID specification](https://www.usb.org/sites/default/files/pid1_01.pdf). Effects are defined and controlled via structured **HID output reports**, whose IDs are declared in the device's HID report descriptor.

Key report types (IDs discovered at runtime from the descriptor):
- **Set Effect** — define effect type, duration, direction
- **Set Constant Force** — magnitude for constant push/pull
- **Set Periodic** — magnitude, period, phase for sine/square/triangle
- **Set Condition** — coefficients for spring/damper
- **Set Envelope** — attack/fade shaping for any effect
- **Effect Operation** — play, stop, solo
- **Device Control** — enable FF, reset, disable
- **Device Gain** — overall FF strength

---

## Long-term plan — X-Plane bridge

The goal is a background process that reads X-Plane flight data and translates it into live force feedback on the joystick, similar to what [ffb-bridge](https://ffb-bridge.com/) does on Windows/Linux.

### Why pyusb won't work for the bridge

`libusb` steals the device from the OS entirely. If it's claimed by the bridge, X-Plane cannot read joystick axes or buttons. Not viable for a co-running process.

### The right transport: IOHIDDevice output reports

macOS's **IOHIDDevice API** (part of IOKit) allows sending HID output reports without claiming exclusive USB access. The HID kernel driver keeps the device open for input (X-Plane reads axes normally), and the bridge sends FF output reports in parallel through the same driver.

Python reaches IOHIDDevice via `ctypes` calling into the IOKit framework.

### Bridge architecture (planned)

```
X-Plane (UDP telemetry)
        │
        ▼
  bridge/xplane.py      reads UDP dataref stream (RREF protocol)
        │ flight model values (AoA, G-load, airspeed, etc.)
        ▼
  bridge/forces.py      maps flight model → force effect parameters
        │ effect type + magnitude
        ▼
  bridge/iohid.py       sends HID PID output reports via IOHIDDevice
        │ (non-exclusive — X-Plane input still works)
        ▼
  Sidewinder FF2
```

`effects.py` stays identical — only the transport layer (`hidpid.py` → `iohid.py`) changes when migrating from pyusb to IOHIDDevice.

### Migration path

1. **Now:** pyusb demo — prove HID PID packets work, explore effect parameters
2. **Next:** port transport to IOHIDDevice (ctypes) so bridge and X-Plane coexist
3. **Then:** add X-Plane UDP reader and force mapping

### X-Plane data sources

X-Plane exposes flight model data over UDP via the RREF (dataref request) protocol on `localhost:49000`. Useful datarefs for force feedback:

| Dataref | Use |
|---|---|
| `sim/flightmodel/forces/g_nrml` | normal G-load → stick heaviness |
| `sim/flightmodel2/wing/alpha` | angle of attack → buffet onset |
| `sim/cockpit2/controls/yoke_pitch_ratio` | control input position |
| `sim/cockpit2/controls/yoke_roll_ratio` | control input position |
| `sim/flightmodel/failures/onground_any` | gear impact → rumble |

---

## Known issues / gotchas

- **macOS HID driver detach**: `libusb` calls `IOUSBDevice::USBDeviceOpen` exclusively. Always runs in a `try/finally` to guarantee reattach on crash.
- **HID PID report IDs are device-specific**: They are declared in the HID report descriptor, not fixed by the spec. The demo reads the descriptor first to discover them rather than hardcoding.
- **Sidewinder FF2 has known bugs in Linux's hid-pidff**: The initialisation sequence and effect-ID tracking had bugs (fixed in recent kernels). May need equivalent workarounds when talking to the device directly.
- **No macOS game support**: macOS's `ForceFeedback.framework` is deprecated and SDL2 never properly implemented it, so no existing game drives FF on macOS. The bridge approach bypasses this entirely by computing forces from telemetry rather than relying on the game to output them.
