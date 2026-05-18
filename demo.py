#!/usr/bin/env python3
"""
Sidewinder FF2 - Force feedback demo.
No mechanical spring — FF has full authority over stick position.
Run: sudo venv/bin/python3 demo.py
"""
import usb.core, usb.util, time, math

VID, PID, IFACE = 0x045e, 0x001b, 0

R_SET_EFFECT         = 0x01
R_SET_CONDITION      = 0x03
R_SET_CONSTANT_FORCE = 0x05
R_EFFECT_OPERATION   = 0x0a
R_DEVICE_CONTROL     = 0x0c
R_DEVICE_GAIN        = 0x0d
R_POSITION           = 0x08  # Report 8: direct X/Y position command (-127..127)


def find_ep_out(dev):
    cfg = dev.get_active_configuration()
    intf = cfg[(0, 0)]
    ep = usb.util.find_descriptor(intf,
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
    assert ep, "No interrupt OUT endpoint found"
    return ep.bEndpointAddress


def out(dev, ep, data):
    dev.write(ep, bytes(data), 1000)

def stop_effect(dev, ep, block):
    out(dev, ep, [R_EFFECT_OPERATION, block, 0x03, 0x00])

def play_effect(dev, ep, block):
    out(dev, ep, [R_EFFECT_OPERATION, block, 0x01, 0x01])


def push(dev, ep, block, angle_deg, magnitude=255):
    """
    Push stick in a direction and hold it there.
    angle_deg: 0=forward, 90=right, 180=back, 270=left
    magnitude: 0-255
    """
    direction_byte = int(angle_deg / 360.0 * 256) % 256
    stop_effect(dev, ep, block)
    out(dev, ep, [
        R_SET_EFFECT,
        block, 0x01,           # Constant Force
        0xff, 0x7f,            # Duration 32s
        0x00, 0x00,            # Trigger repeat
        0x00, 0x00,            # Sample period
        0xff,                  # Gain max
        0x00,                  # No trigger button
        0x07,                  # X+Y axes enabled, direction_enable=1
        direction_byte, 0x00,  # Direction
        0x00, 0x00,            # No delay
    ])
    out(dev, ep, [R_SET_CONSTANT_FORCE, block, magnitude & 0xFF, 0x00])
    play_effect(dev, ep, block)


def push_xy(dev, ep, block, x, y):
    """Push via X/Y components (-255..255 each). Converts to polar internally."""
    angle_rad = math.atan2(x, -y)          # 0=forward(−y), 90°=right(+x)
    angle_deg = math.degrees(angle_rad) % 360
    magnitude = min(255, int(math.sqrt(x*x + y*y)))
    push(dev, ep, block, angle_deg, magnitude)


def spring(dev, ep, block, x_center=0, y_center=0, stiffness=0xFF):
    """
    Spring effect that holds the stick at (x_center, y_center).
    x_center, y_center: -127 to 127 (full stick range).
    Without a mechanical spring, this actively positions the stick.
    """
    stop_effect(dev, ep, block)
    out(dev, ep, [
        R_SET_EFFECT,
        block, 0x08,           # Spring (condition effect)
        0xff, 0x7f,            # Duration 32s
        0x00, 0x00,
        0x00, 0x00,
        0xff,                  # Gain max
        0x00,
        0x03,                  # X+Y axes, no direction (condition handles it)
        0x00, 0x00,
        0x00, 0x00,
    ])
    # Set Condition for X axis (parameter block offset=0)
    xc = x_center & 0xFF
    out(dev, ep, [R_SET_CONDITION, block, 0x00, xc, stiffness, stiffness, 0xFF, 0xFF, 0x00])
    # Set Condition for Y axis (parameter block offset=1)
    yc = y_center & 0xFF
    out(dev, ep, [R_SET_CONDITION, block, 0x01, yc, stiffness, stiffness, 0xFF, 0xFF, 0x00])
    play_effect(dev, ep, block)


def main():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    assert dev, "Device not found"

    reattach = dev.is_kernel_driver_active(IFACE)
    if reattach:
        dev.detach_kernel_driver(IFACE)
    dev.set_configuration()
    usb.util.claim_interface(dev, IFACE)
    ep = find_ep_out(dev)

    try:
        out(dev, ep, [R_DEVICE_CONTROL, 0x01])
        time.sleep(0.1)
        out(dev, ep, [R_DEVICE_GAIN, 0xff])
        time.sleep(0.1)
        block = 1

        # ── Slam to each corner ──────────────────────────────────────────
        print("Corners: right → forward → left → back")
        for angle in [90, 0, 270, 180]:
            push(dev, ep, block, angle)
            time.sleep(1.0)
        stop_effect(dev, ep, block);  time.sleep(0.4)

        # ── Slow circular sweep ──────────────────────────────────────────
        print("Slow circle")
        angle = 0.0
        push(dev, ep, block, angle)
        t0 = time.time()
        while time.time() - t0 < 8:
            angle = ((time.time() - t0) / 5.0) * 360.0   # full circle in 5s
            direction_byte = int(angle / 360.0 * 256) % 256
            # Update direction in-flight (no stop/restart — smoother)
            out(dev, ep, [
                R_SET_EFFECT, block, 0x01, 0xff, 0x7f, 0x00, 0x00, 0x00, 0x00,
                0xff, 0x00, 0x07, direction_byte, 0x00, 0x00, 0x00,
            ])
            time.sleep(0.04)
        stop_effect(dev, ep, block);  time.sleep(0.4)

        # ── Direct position test (Report 8: X/Y position command) ───────
        print("Direct position: center")
        out(dev, ep, [R_POSITION, 0, 0])
        time.sleep(2.0)

        print("Direct position: top-right")
        out(dev, ep, [R_POSITION, 100, -100 & 0xFF])
        time.sleep(2.0)

        print("Direct position: bottom-left")
        out(dev, ep, [R_POSITION, -100 & 0xFF, 100])
        time.sleep(2.0)

        print("Direct position: back to center")
        out(dev, ep, [R_POSITION, 0, 0])
        time.sleep(2.0)

        # ── Accelerating left/right slams ────────────────────────────────
        print("Accelerating slams")
        delay = 0.55
        for _ in range(18):
            push(dev, ep, block, 90)
            time.sleep(delay)
            push(dev, ep, block, 270)
            time.sleep(delay)
            delay *= 0.82

        stop_effect(dev, ep, block)
        print("Done!")

    finally:
        usb.util.release_interface(dev, IFACE)
        if reattach:
            try:
                dev.attach_kernel_driver(IFACE)
            except Exception:
                pass
        usb.util.dispose_resources(dev)


if __name__ == "__main__":
    main()
