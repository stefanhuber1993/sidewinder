# Sidewinder FF2 — Force Feedback on macOS

Python tooling to drive force feedback on the **Microsoft SideWinder Force Feedback 2** joystick from macOS, with a long-term goal of a flight-sim bridge for X-Plane.

---

## Hardware

**Microsoft SideWinder Force Feedback 2**
- USB VID `0x045e` / PID `0x001b`
- Protocol: **USB HID PID** (Physical Interface Device) — the standardised USB HID force feedback spec
- NOT an I-Force device (that protocol is used by Logitech/Thrustmaster, not Microsoft)

---

## Current State

The driver (`sidewinder/ff2.py`) uses **python-hid (hidapi)** to send HID PID output reports via macOS's native **IOKit HID Manager**. This means:

- **No `sudo` required** — IOKit HID Manager is user-space accessible
- **No exclusive access** — the OS joystick driver keeps reading axes and buttons normally
- Force feedback output reports are sent in parallel with normal joystick input

### Why sudo is NOT needed (the fix)

The old approach used `pyusb` + `libusb`, which works by calling `IOUSBDevice::USBDeviceOpen` to claim **exclusive** USB access and then detach the IOHIDFamily kernel driver. Detaching kernel drivers requires root, hence `sudo`.

The fix: use **hidapi** via the `hid` Python package. On macOS, hidapi talks to the device through the **IOKit HID Manager API** (`IOHIDManager`, `IOHIDDevice`), which is designed for user-space HID access. It does not detach the kernel driver — it shares the device with it. Force feedback output reports go through the HID driver directly to the device; HID input (axes, buttons) continues to flow normally to the OS.

This is also the correct architecture for the eventual X-Plane bridge: the joystick stays fully functional in-game while the bridge sends FF output reports alongside.

### Setup

```bash
brew install hidapi      # native hidapi library (IOKit backend)
./setup.sh               # creates venv, installs Python deps
source venv/bin/activate
python3 notebook.ipynb   # or: jupyter notebook
```

No `sudo` needed at any step.

---

## Protocol: USB HID PID

The SideWinder FF2 implements the [USB HID PID specification](https://www.usb.org/sites/default/files/pid1_01.pdf). Effects are defined and controlled via structured **HID output reports** and **HID feature reports**:

| Report | ID | Direction | Purpose |
|---|---|---|---|
| Set Effect | 0x01 | OUT | Define effect type, duration, direction |
| Set Envelope | 0x02 | OUT | Attack/fade shaping |
| Set Condition | 0x03 | OUT | Spring/damper coefficients per axis |
| Set Periodic | 0x04 | OUT | Magnitude, period, phase |
| Set Constant Force | 0x05 | OUT | Magnitude for constant push |
| Effect Operation | 0x0a | OUT | Play / stop / solo |
| Device Control | 0x0c | OUT | Enable FF, reset, disable |
| Device Gain | 0x0d | OUT | Overall FF strength |
| Create New Effect | 0x01 | FEATURE SET | Allocate effect block |
| PID Block Load | 0x02 | FEATURE GET | Returns allocated block index |

---

## Long-term plan — X-Plane bridge

The goal is a background process that reads X-Plane flight data and translates it into live force feedback on the joystick.

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
  sidewinder/ff2.py     sends HID PID reports via IOKit HID Manager
        │ (non-exclusive — X-Plane joystick input still works)
        ▼
  Sidewinder FF2
```

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

- **HID PID report IDs are device-specific**: They are declared in the HID report descriptor, not fixed by the spec. Verify with `discover.py` if in doubt.
- **Sidewinder FF2 has known bugs in Linux's hid-pidff**: The initialisation sequence and effect-ID tracking had bugs (fixed in recent kernels). May need equivalent workarounds when talking to the device directly.
- **No macOS game support**: macOS's `ForceFeedback.framework` is deprecated and SDL2 never properly implemented it for this device. The bridge bypasses this entirely by computing forces from telemetry.
- **hidapi `write()` report format**: the first byte passed to `hid.write()` must be the HID output report ID. The FF2 uses numbered reports (0x01–0x0d), so no zero-prefix is needed.
- **Multiple HID collections**: if `hid.enumerate()` returns multiple entries for the same VID/PID, the driver picks `devs[0]`. Use `hid.enumerate(0x045e, 0x001b)` to inspect all entries and adjust the index if needed.
