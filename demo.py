#!/usr/bin/env python3
"""
Sidewinder FF2 - HID PID constant force demo.
Run: sudo venv/bin/python3 demo.py
"""
import usb.core, usb.util, time

VID, PID, IFACE = 0x045e, 0x001b, 0

# Report IDs discovered from HID report descriptor
R_SET_EFFECT         = 0x01  # OUTPUT
R_SET_CONSTANT_FORCE = 0x05  # OUTPUT
R_EFFECT_OPERATION   = 0x0a  # OUTPUT
R_DEVICE_CONTROL     = 0x0c  # OUTPUT
R_DEVICE_GAIN        = 0x0d  # OUTPUT
R_CREATE_NEW_EFFECT  = 0x01  # FEATURE
R_BLOCK_LOAD         = 0x02  # FEATURE


def out(dev, data):
    """Send HID output report (report ID is data[0])."""
    dev.ctrl_transfer(0x21, 0x09, 0x0200 | data[0], IFACE, bytes(data), 1000)


def set_feat(dev, data):
    """Send HID feature report (report ID is data[0])."""
    dev.ctrl_transfer(0x21, 0x09, 0x0300 | data[0], IFACE, bytes(data), 1000)


def get_feat(dev, report_id, length):
    """Read HID feature report."""
    return dev.ctrl_transfer(0xa1, 0x01, 0x0300 | report_id, IFACE, length, 1000)


def main():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    assert dev, f"Device not found (VID=0x{VID:04x} PID=0x{PID:04x})"

    reattach = dev.is_kernel_driver_active(IFACE)
    if reattach:
        dev.detach_kernel_driver(IFACE)
    dev.set_configuration()

    try:
        # --- Enable force feedback ---
        out(dev, [R_DEVICE_CONTROL, 0x01])   # 0x01 = Enable Actuators
        time.sleep(0.1)
        out(dev, [R_DEVICE_GAIN, 0xff])       # gain = 255 (max)
        time.sleep(0.1)
        print("FF enabled, gain at max.")

        # --- Allocate an effect block ---
        # Create New Effect: effect type=1 (Constant Force), byte_count=0
        set_feat(dev, [R_CREATE_NEW_EFFECT, 0x01, 0x00, 0x00])
        time.sleep(0.05)

        resp = get_feat(dev, R_BLOCK_LOAD, 5)
        print(f"Block load response: {[hex(b) for b in resp]}")
        # resp[0]=report_id, resp[1]=block_index, resp[2]=status (1=OK, 2=Full, 3=Error)
        block = resp[1] if len(resp) > 1 else 1
        status = resp[2] if len(resp) > 2 else 1
        print(f"Effect block index: {block}, status: {status} (1=OK, 2=Full, 3=Error)")

        if status == 2:
            print("Memory full — stopping all effects and retrying with block 1")
            out(dev, [R_DEVICE_CONTROL, 0x03])  # Stop All Effects
            time.sleep(0.1)
            out(dev, [R_DEVICE_CONTROL, 0x01])  # Re-enable
            time.sleep(0.1)
            block = 1

        # --- Define the effect ---
        # Set Effect: constant force, 32 seconds, X axis, no trigger
        out(dev, [
            R_SET_EFFECT,
            block,          # Effect Block Index
            0x01,           # Effect Type: 1 = Constant Force
            0xff, 0x7f,     # Duration: 32767 ms (~32s)
            0x00, 0x00,     # Trigger Repeat Interval: 0
            0x00, 0x00,     # Sample Period: 0
            0xff,           # Gain: max
            0x00,           # Trigger Button: none
            0x01,           # Axes Enable: X=1, Y=0 | Direction Enable=0 | 5-bit pad
            0x00, 0x00,     # Direction: unused (direction enable = 0)
            0x00, 0x00,     # Start Delay: 0
        ])
        time.sleep(0.05)

        # Set Constant Force magnitude: int16 LE, range -255..+255
        # +127 = moderate rightward push (~50%)
        out(dev, [R_SET_CONSTANT_FORCE, block, 0x7f, 0x00])
        time.sleep(0.05)

        # --- Play ---
        print("Playing constant force for 3 seconds... grab the stick!")
        out(dev, [R_EFFECT_OPERATION, block, 0x01, 0x01])  # Start, loop=1
        time.sleep(3)

        # --- Stop ---
        out(dev, [R_EFFECT_OPERATION, block, 0x03, 0x00])  # Stop
        print("Done.")

    finally:
        if reattach:
            try:
                dev.attach_kernel_driver(IFACE)
            except Exception:
                pass
        usb.util.dispose_resources(dev)


if __name__ == "__main__":
    main()
