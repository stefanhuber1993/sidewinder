# Sidewinder FF2 — HID PID Demo Plan

**Goal:** Get a force effect physically playing on the joystick.

**Protocol:** USB HID PID — report IDs are device-specific, discovered from the HID report descriptor at runtime.

**Stack:** Python 3, PyUSB, libusb (already installed).

---

### Task 1: `discover.py` — read HID report descriptor

Run this first. It opens the device and prints the raw report descriptor so we can identify which report IDs map to which HID PID functions (Set Effect, Constant Force, Effect Operation, Device Control).

- [ ] Write and run `discover.py`

### Task 2: `demo.py` — constant force effect

Using the report IDs found in Task 1, send the minimal HID PID sequence to play a constant force effect:
1. Device Control — enable actuators
2. Set Effect — define constant force, infinite duration
3. Set Constant Force — magnitude
4. Effect Operation — play
5. sleep(3), then stop

- [ ] Write and run `demo.py`
