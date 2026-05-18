# Sidewinder FF2 Force Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish USB communication with the Sidewinder FF2 and run a demo that cycles through constant force, sine wave, and spring effects to confirm the link works.

**Architecture:** Layered Python package — `device.py` owns USB lifecycle, `iforce.py` owns packet construction, `effects.py` composes those into named parameterised effects, `demo.py` orchestrates the sequence. Each layer is independently importable.

**Tech Stack:** Python 3, PyUSB (`usb.core`), libusb (Homebrew), pytest for unit tests.

---

## File Map

| File | Responsibility |
|------|----------------|
| `setup.sh` | Create venv, install pyusb |
| `requirements.txt` | `pyusb` |
| `sidewinder/__init__.py` | Package marker |
| `sidewinder/device.py` | Open USB device, detach/re-attach macOS HID driver, claim interface, expose `write()` |
| `sidewinder/iforce.py` | Build I-Force wire packets, `hifix80()` conversion, `send()` helper |
| `sidewinder/effects.py` | Named effect builders: `build_constant()`, `build_sine()`, `build_spring()`, `build_stop()` |
| `demo.py` | Demo sequence: enable → constant R → constant L → sine → spring → stop |
| `tests/__init__.py` | Package marker |
| `tests/test_iforce.py` | Unit tests for packet construction and `hifix80()` |
| `tests/test_effects.py` | Unit tests for effect builder output |

---

### Task 1: Project scaffold and venv

**Files:**
- Create: `setup.sh`
- Create: `requirements.txt`
- Create: `sidewinder/__init__.py`

- [ ] **Step 1: Create `requirements.txt`**

```
pyusb
```

- [ ] **Step 2: Create `setup.sh`**

```bash
#!/bin/bash
set -e
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
echo "Done. Run: source venv/bin/activate"
```

- [ ] **Step 3: Create package marker**

Create `sidewinder/__init__.py` as an empty file.

- [ ] **Step 4: Run setup**

```bash
cd /Users/shuber/Projects/sidewinder
chmod +x setup.sh && ./setup.sh
```

Expected: output ends with `Done. Run: source venv/bin/activate`

- [ ] **Step 5: Activate and verify**

```bash
source venv/bin/activate
python3 -c "import usb; print(usb.__version__)"
```

Expected: a version string like `1.2.1`

- [ ] **Step 6: Commit**

```bash
git init
git add setup.sh requirements.txt sidewinder/__init__.py
git commit -m "feat: project scaffold with venv setup"
```

---

### Task 2: `iforce.py` — packet construction

**Files:**
- Create: `sidewinder/iforce.py`
- Create: `tests/__init__.py`
- Create: `tests/test_iforce.py`

**Protocol summary:**
Every I-Force command sent to the device is `[cmd_id, payload_len, ...payload_bytes]`.

Command IDs and their fixed payload lengths (from Linux kernel `iforce.h`):

| Constant | Cmd ID | Payload len |
|----------|--------|-------------|
| `CMD_ENABLE` | `0x42` | 1 |
| `CMD_GAIN` | `0x43` | 1 |
| `CMD_EFFECT` | `0x01` | 14 |
| `CMD_MAGNITUDE` | `0x03` | 3 |
| `CMD_PERIOD` | `0x04` | 7 |
| `CMD_CONDITION` | `0x05` | 10 |
| `CMD_PLAY` | `0x41` | 3 |

`hifix80(val)` converts a signed 16-bit int to the I-Force level byte (the `HIFIX80` macro from the kernel):
```
if val < 0: val += 255
return (val >> 8) & 0xFF
```

- [ ] **Step 1: Write failing tests**

Create empty `tests/__init__.py`.

`tests/test_iforce.py`:
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sidewinder.iforce import build_packet, hifix80

def test_build_packet_prepends_cmd_and_len():
    pkt = build_packet(0x42, [0x01])
    assert pkt == bytes([0x42, 0x01, 0x01])

def test_build_packet_rejects_wrong_payload_length():
    try:
        build_packet(0x42, [0x01, 0x02])  # CMD_ENABLE expects 1 byte
        assert False, "expected ValueError"
    except ValueError:
        pass

def test_hifix80_positive():
    assert hifix80(0x7FFF) == 0x7F
    assert hifix80(0x4000) == 0x40
    assert hifix80(0x0000) == 0x00

def test_hifix80_negative():
    # -0x4000 = -16384 → (-16384 + 255) >> 8 = -16129 >> 8 = -64 → & 0xFF = 0xC0
    assert hifix80(-0x4000) == 0xC0
    # -0x7FFF = -32767 → (-32767 + 255) >> 8 = -32512 >> 8 = -127 → & 0xFF = 0x81
    assert hifix80(-0x7FFF) == 0x81
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source venv/bin/activate
python3 -m pytest tests/test_iforce.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` — `sidewinder.iforce` doesn't exist yet.

- [ ] **Step 3: Implement `sidewinder/iforce.py`**

```python
"""I-Force USB protocol — packet construction and transmission."""

# Command IDs (high byte of iforce.h FF_CMD_* constants)
CMD_ENABLE    = 0x42  # payload len 1
CMD_GAIN      = 0x43  # payload len 1
CMD_EFFECT    = 0x01  # payload len 14
CMD_MAGNITUDE = 0x03  # payload len 3
CMD_PERIOD    = 0x04  # payload len 7
CMD_CONDITION = 0x05  # payload len 10
CMD_PLAY      = 0x41  # payload len 3

_PAYLOAD_LENGTHS = {
    CMD_ENABLE:    1,
    CMD_GAIN:      1,
    CMD_EFFECT:    14,
    CMD_MAGNITUDE: 3,
    CMD_PERIOD:    7,
    CMD_CONDITION: 10,
    CMD_PLAY:      3,
}


def hifix80(val: int) -> int:
    """Convert signed 16-bit int to I-Force level byte (HIFIX80 macro from kernel)."""
    if val < 0:
        val += 255
    return (val >> 8) & 0xFF


def build_packet(cmd_id: int, payload: list[int]) -> bytes:
    """Build an I-Force wire packet: [cmd_id, payload_len, ...payload]."""
    expected = _PAYLOAD_LENGTHS.get(cmd_id)
    if expected is not None and len(payload) != expected:
        raise ValueError(
            f"cmd 0x{cmd_id:02x} expects {expected} payload bytes, got {len(payload)}"
        )
    return bytes([cmd_id, len(payload)] + payload)


def send(device, cmd_id: int, payload: list[int]) -> None:
    """Build and write one I-Force packet to the device."""
    device.write(build_packet(cmd_id, payload))
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 -m pytest tests/test_iforce.py -v
```

Expected:
```
PASSED tests/test_iforce.py::test_build_packet_prepends_cmd_and_len
PASSED tests/test_iforce.py::test_build_packet_rejects_wrong_payload_length
PASSED tests/test_iforce.py::test_hifix80_positive
PASSED tests/test_iforce.py::test_hifix80_negative
```

- [ ] **Step 5: Commit**

```bash
git add sidewinder/iforce.py tests/__init__.py tests/test_iforce.py
git commit -m "feat: iforce packet construction with hifix80 and build_packet"
```

---

### Task 3: `device.py` — USB open/close/detach

**Files:**
- Create: `sidewinder/device.py`

No unit tests for this task — it requires real hardware. Verified in Task 5.

VID=`0x045e`, PID=`0x001b` (Microsoft Sidewinder Force Feedback 2).

The device has two interrupt endpoints on interface 0:
- EP IN: incoming joystick data and FF status (not used in demo)
- EP OUT: outgoing FF command packets

- [ ] **Step 1: Implement `sidewinder/device.py`**

```python
"""USB device lifecycle for Microsoft Sidewinder Force Feedback 2."""
import usb.core
import usb.util

VID = 0x045e
PID = 0x001b
INTERFACE = 0


class SidewinderDevice:
    """Open/close USB connection, detach macOS HID driver, expose write()."""

    def __init__(self):
        self._dev = None
        self._ep_out = None
        self._kernel_driver_reattach = False

    def open(self):
        self._dev = usb.core.find(idVendor=VID, idProduct=PID)
        if self._dev is None:
            raise RuntimeError(
                "Sidewinder FF2 not found. Is the joystick plugged in? "
                f"Expected VID=0x{VID:04x} PID=0x{PID:04x}"
            )

        # Detach macOS IOHIDFamily driver if active so libusb can claim the device
        if self._dev.is_kernel_driver_active(INTERFACE):
            self._dev.detach_kernel_driver(INTERFACE)
            self._kernel_driver_reattach = True

        self._dev.set_configuration()
        usb.util.claim_interface(self._dev, INTERFACE)

        # Find the interrupt OUT endpoint
        cfg = self._dev.get_active_configuration()
        intf = cfg[(0, 0)]
        self._ep_out = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: (
                usb.util.endpoint_direction(e.bEndpointAddress)
                == usb.util.ENDPOINT_OUT
            ),
        )
        if self._ep_out is None:
            raise RuntimeError("Could not find interrupt OUT endpoint on interface 0")

    def write(self, data: bytes) -> None:
        self._dev.write(self._ep_out.bEndpointAddress, data)

    def close(self):
        if self._dev is None:
            return
        try:
            usb.util.release_interface(self._dev, INTERFACE)
        except Exception:
            pass
        if self._kernel_driver_reattach:
            try:
                self._dev.attach_kernel_driver(INTERFACE)
            except Exception:
                pass
        usb.util.dispose_resources(self._dev)
        self._dev = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_):
        self.close()
```

- [ ] **Step 2: Commit**

```bash
git add sidewinder/device.py
git commit -m "feat: USB device open/close with macOS HID driver detach/reattach"
```

---

### Task 4: `effects.py` — effect builders

**Files:**
- Create: `sidewinder/effects.py`
- Create: `tests/test_effects.py`

**Packet structure reference (from kernel `iforce-ff.c`):**

`FF_CMD_EFFECT` core — 14-byte payload (kernel's `make_core`):
```
[0]  slot id (LO)
[1]  effect type: 0x00=constant, 0x22=sine, 0x40=spring
[2]  axes: 0x20=X axis, 0xC0=both axes
[3]  duration lo
[4]  duration hi
[5]  direction hi byte (0x00=up, 0x40=right, 0x80=down, 0xC0=left)
[6]  trigger interval lo (0x00 = no trigger)
[7]  trigger interval hi
[8]  mod1 address lo
[9]  mod1 address hi
[10] mod2 address lo
[11] mod2 address hi
[12] delay lo
[13] delay hi
```

`FF_CMD_MAGNITUDE` — 3-byte payload:
```
[0] addr lo,  [1] addr hi,  [2] hifix80(level)
```

`FF_CMD_PERIOD` — 7-byte payload:
```
[0] addr lo, [1] addr hi, [2] hifix80(magnitude),
[3] hifix80(offset), [4] phase hi, [5] period lo, [6] period hi
```

`FF_CMD_CONDITION` — 10-byte payload (kernel's `make_condition_modifier`):
```
[0] addr lo, [1] addr hi,
[2] (100 * rk) >> 15,     right coeff scaled
[3] (100 * lk) >> 15,     left coeff scaled
[4] center lo,  [5] center hi  (center = (500 * center_raw) >> 15)
[6] db lo,      [7] db hi      (db = (1000 * db_raw) >> 16)
[8] (100 * rsat) >> 16,   right saturation scaled
[9] (100 * lsat) >> 16,   left saturation scaled
```

`FF_CMD_PLAY` — 3-byte payload (kernel's `iforce_control_playback`):
```
[0] slot, [1] 0x41 (loop), [2] 0xFF (repeat count ≈ indefinite)
stop: [0] slot, [1] 0x00, [2] 0x00
```

Fixed memory addresses used for parameter blocks (device RAM slots):
- `MOD_ADDR_A = 0x0000` — first parameter (magnitude, period, or condition X)
- `MOD_ADDR_B = 0x0010` — second parameter (envelope or condition Y)

- [ ] **Step 1: Write failing tests**

`tests/test_effects.py`:
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sidewinder.effects import build_constant, build_sine, build_spring, build_stop
from sidewinder.iforce import CMD_MAGNITUDE, CMD_PERIOD, CMD_CONDITION, CMD_EFFECT, CMD_PLAY

def test_build_constant_packet_order():
    packets = build_constant(level=0x4000, direction=0x4000, duration=0x7FFF)
    assert [p[0] for p in packets] == [CMD_MAGNITUDE, CMD_EFFECT, CMD_PLAY]

def test_build_constant_magnitude_bytes():
    packets = build_constant(level=0x4000, direction=0x4000, duration=0x7FFF)
    # [CMD_MAGNITUDE, len=3, addr_lo=0, addr_hi=0, hifix80(0x4000)=0x40]
    assert packets[0] == bytes([CMD_MAGNITUDE, 3, 0x00, 0x00, 0x40])

def test_build_constant_effect_type():
    packets = build_constant(level=0x4000, direction=0x4000, duration=0x7FFF)
    eff = packets[1]
    # packet layout: [CMD_EFFECT, 14, slot, effect_type, ...]
    assert eff[2] == 0x00  # slot 0
    assert eff[3] == 0x00  # type = constant

def test_build_sine_packet_order():
    packets = build_sine(magnitude=0x4000, period_ms=100, duration=0x7FFF)
    assert [p[0] for p in packets] == [CMD_PERIOD, CMD_EFFECT, CMD_PLAY]

def test_build_sine_effect_type():
    packets = build_sine(magnitude=0x4000, period_ms=100, duration=0x7FFF)
    eff = packets[1]
    assert eff[3] == 0x22  # type = sine

def test_build_spring_packet_order():
    packets = build_spring(coeff=0x2000, saturation=0xFFFF, duration=0x7FFF)
    assert [p[0] for p in packets] == [CMD_CONDITION, CMD_CONDITION, CMD_EFFECT, CMD_PLAY]

def test_build_spring_effect_type():
    packets = build_spring(coeff=0x2000, saturation=0xFFFF, duration=0x7FFF)
    eff = packets[2]  # index 2: cond_x, cond_y, core, play
    assert eff[3] == 0x40  # type = spring

def test_build_stop():
    assert build_stop() == bytes([CMD_PLAY, 3, 0x00, 0x00, 0x00])
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_effects.py -v
```

Expected: `ImportError` — `sidewinder.effects` doesn't exist yet.

- [ ] **Step 3: Implement `sidewinder/effects.py`**

```python
"""Named I-Force effect builders. Each function returns a list[bytes] of packets to send."""
from sidewinder.iforce import (
    build_packet, hifix80,
    CMD_EFFECT, CMD_MAGNITUDE, CMD_PERIOD, CMD_CONDITION, CMD_PLAY,
)

MOD_ADDR_A = 0x0000  # first parameter block in device RAM
MOD_ADDR_B = 0x0010  # second parameter block in device RAM
SLOT = 0x00          # effect slot used for all effects


def _lo(val: int) -> int:
    return val & 0xFF


def _hi(val: int) -> int:
    return (val >> 8) & 0xFF


def _core(effect_type: int, axes: int, mod1: int, mod2: int,
          direction: int, duration: int) -> bytes:
    """Build the FF_CMD_EFFECT 14-byte core packet (kernel make_core)."""
    return build_packet(CMD_EFFECT, [
        SLOT,
        effect_type,
        axes,
        _lo(duration), _hi(duration),  # bytes 3-4: duration
        _hi(direction),                 # byte 5: direction high byte only
        0x00, 0x00,                     # bytes 6-7: trigger interval (none)
        _lo(mod1), _hi(mod1),           # bytes 8-9: mod1 address
        _lo(mod2), _hi(mod2),           # bytes 10-11: mod2 address
        0x00, 0x00,                     # bytes 12-13: delay
    ])


def _play_loop() -> bytes:
    """Play effect on slot 0 in loop mode (indefinite)."""
    return build_packet(CMD_PLAY, [SLOT, 0x41, 0xFF])


def build_constant(level: int, direction: int = 0x4000,
                   duration: int = 0x7FFF) -> list[bytes]:
    """
    Constant force effect.
    level:     signed 16-bit force magnitude (positive = right)
    direction: 0x0000=up, 0x4000=right, 0x8000=down, 0xC000=left
    duration:  milliseconds (0x7FFF ≈ 32s)
    """
    mag = build_packet(CMD_MAGNITUDE, [
        _lo(MOD_ADDR_A), _hi(MOD_ADDR_A),
        hifix80(level),
    ])
    core = _core(
        effect_type=0x00, axes=0x20,
        mod1=MOD_ADDR_A, mod2=0x0000,
        direction=direction, duration=duration,
    )
    return [mag, core, _play_loop()]


def build_sine(magnitude: int, period_ms: int = 100,
               duration: int = 0x7FFF) -> list[bytes]:
    """
    Sine wave (rumble) effect.
    magnitude: signed 16-bit amplitude
    period_ms: oscillation period in milliseconds
    """
    period = build_packet(CMD_PERIOD, [
        _lo(MOD_ADDR_A), _hi(MOD_ADDR_A),
        hifix80(magnitude),
        hifix80(0),               # offset = 0
        0x00,                     # phase high byte = 0
        _lo(period_ms), _hi(period_ms),
    ])
    core = _core(
        effect_type=0x22, axes=0x20,
        mod1=MOD_ADDR_A, mod2=0x0000,
        direction=0x4000, duration=duration,
    )
    return [period, core, _play_loop()]


def _condition_packet(addr: int, coeff: int, saturation: int) -> bytes:
    """Build FF_CMD_CONDITION for one axis (kernel make_condition_modifier)."""
    rk = (100 * coeff) >> 15
    lk = (100 * coeff) >> 15
    rsat = (100 * saturation) >> 16
    lsat = (100 * saturation) >> 16
    return build_packet(CMD_CONDITION, [
        _lo(addr), _hi(addr),
        rk & 0xFF,
        lk & 0xFF,
        0x00, 0x00,   # center = 0
        0x00, 0x00,   # deadband = 0
        rsat & 0xFF,
        lsat & 0xFF,
    ])


def build_spring(coeff: int = 0x2000, saturation: int = 0xFFFF,
                 duration: int = 0x7FFF) -> list[bytes]:
    """
    Spring (centre-return) effect on both axes.
    coeff:      signed 16-bit spring stiffness (higher = stiffer)
    saturation: unsigned 16-bit max force saturation
    """
    cond_x = _condition_packet(MOD_ADDR_A, coeff, saturation)
    cond_y = _condition_packet(MOD_ADDR_B, coeff, saturation)
    core = _core(
        effect_type=0x40, axes=0xC0,   # spring, both axes
        mod1=MOD_ADDR_A, mod2=MOD_ADDR_B,
        direction=0x0000, duration=duration,
    )
    return [cond_x, cond_y, core, _play_loop()]


def build_stop() -> bytes:
    """Stop the effect in slot 0."""
    return build_packet(CMD_PLAY, [SLOT, 0x00, 0x00])
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 -m pytest tests/test_effects.py -v
```

Expected:
```
PASSED tests/test_effects.py::test_build_constant_packet_order
PASSED tests/test_effects.py::test_build_constant_magnitude_bytes
PASSED tests/test_effects.py::test_build_constant_effect_type
PASSED tests/test_effects.py::test_build_sine_packet_order
PASSED tests/test_effects.py::test_build_sine_effect_type
PASSED tests/test_effects.py::test_build_spring_packet_order
PASSED tests/test_effects.py::test_build_spring_effect_type
PASSED tests/test_effects.py::test_build_stop
```

- [ ] **Step 5: Commit**

```bash
git add sidewinder/effects.py tests/test_effects.py
git commit -m "feat: effect builders for constant force, sine wave, and spring"
```

---

### Task 5: `demo.py` — demo sequence

**Files:**
- Create: `demo.py`

Requires the joystick plugged in. Must run with `sudo` so libusb can detach the macOS HID driver.

- [ ] **Step 1: Implement `demo.py`**

```python
#!/usr/bin/env python3
"""
Sidewinder FF2 force feedback demo.
Cycles: constant force right → constant force left → sine rumble → spring.
Run with: sudo venv/bin/python3 demo.py
"""
import time
from sidewinder.device import SidewinderDevice
from sidewinder.iforce import build_packet, CMD_ENABLE, CMD_GAIN
from sidewinder.effects import build_constant, build_sine, build_spring, build_stop

HOLD = 2.5   # seconds to hold each effect
GAP  = 0.5   # seconds between effects


def send_all(dev, packets):
    """Send a list of packets with a small inter-packet gap."""
    for pkt in packets:
        dev.write(pkt)
        time.sleep(0.02)


def main():
    with SidewinderDevice() as dev:
        print("Device opened.")

        dev.write(build_packet(CMD_ENABLE, [0x01]))
        dev.write(build_packet(CMD_GAIN,   [0xFF]))
        print("FF enabled, gain at max.")
        time.sleep(0.1)

        print("Constant force RIGHT...", end=" ", flush=True)
        send_all(dev, build_constant(level=0x4000, direction=0x4000))
        time.sleep(HOLD)
        dev.write(build_stop())
        print("stopped.")
        time.sleep(GAP)

        print("Constant force LEFT...", end=" ", flush=True)
        send_all(dev, build_constant(level=-0x4000, direction=0xC000))
        time.sleep(HOLD)
        dev.write(build_stop())
        print("stopped.")
        time.sleep(GAP)

        print("Sine wave rumble...", end=" ", flush=True)
        send_all(dev, build_sine(magnitude=0x6000, period_ms=80))
        time.sleep(HOLD)
        dev.write(build_stop())
        print("stopped.")
        time.sleep(GAP)

        print("Spring (centre-return)...", end=" ", flush=True)
        send_all(dev, build_spring(coeff=0x2000, saturation=0xFFFF))
        time.sleep(HOLD)
        dev.write(build_stop())
        print("stopped.")

        print("Demo complete.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the full test suite to confirm nothing broke**

```bash
python3 -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 3: Run the demo (joystick must be plugged in)**

```bash
sudo venv/bin/python3 demo.py
```

Expected console output:
```
Device opened.
FF enabled, gain at max.
Constant force RIGHT... stopped.
Constant force LEFT... stopped.
Sine wave rumble... stopped.
Spring (centre-return)... stopped.
Demo complete.
```

Expected physical behaviour: distinct sensation for each effect for ~2.5 seconds each.

- [ ] **Step 4: Troubleshooting — device not found**

If `RuntimeError: Sidewinder FF2 not found`:

```bash
sudo venv/bin/python3 -c "
import usb.core
for dev in usb.core.find(find_all=True):
    print(f'VID=0x{dev.idVendor:04x} PID=0x{dev.idProduct:04x}')
"
```

Find the Sidewinder in the list and update `VID`/`PID` in `sidewinder/device.py`.

- [ ] **Step 5: Troubleshooting — device opens but no physical response**

The device may need an initialization query before accepting FF commands. Add this immediately after `dev.open()` in `demo.py` to inspect the device's response:

```python
resp = dev._dev.ctrl_transfer(
    0xC1,   # USB_TYPE_VENDOR | USB_DIR_IN | USB_RECIP_INTERFACE
    0xFF,   # FF_CMD_QUERY
    0, 0, 16
)
print("Device query:", [hex(b) for b in resp])
```

Paste the response back to iterate on the initialisation sequence.

- [ ] **Step 6: Commit**

```bash
git add demo.py
git commit -m "feat: force feedback demo cycling constant, sine, and spring effects"
```
