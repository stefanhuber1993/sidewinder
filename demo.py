#!/usr/bin/env python3
"""
Sidewinder FF2 - Force feedback patterns demo.
Run: sudo venv/bin/python3 demo.py
"""
import usb.core, usb.util, time, math

VID, PID, IFACE = 0x045e, 0x001b, 0

R_SET_EFFECT         = 0x01
R_SET_CONSTANT_FORCE = 0x05
R_EFFECT_OPERATION   = 0x0a
R_DEVICE_CONTROL     = 0x0c
R_DEVICE_GAIN        = 0x0d


def find_ep_out(dev):
    cfg = dev.get_active_configuration()
    intf = cfg[(0, 0)]
    ep = usb.util.find_descriptor(intf,
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
    assert ep, "No interrupt OUT endpoint found"
    return ep.bEndpointAddress


def out(dev, ep, data):
    dev.write(ep, bytes(data), 1000)


def magnitude(dev, ep, block, val):
    """Send constant force magnitude and restart effect so device picks it up. val: -255 to +255."""
    val = max(-255, min(255, int(val)))
    raw = val if val >= 0 else val + 65536   # two's complement uint16
    out(dev, ep, [R_EFFECT_OPERATION, block, 0x03, 0x00])   # stop
    out(dev, ep, [R_SET_CONSTANT_FORCE, block, raw & 0xFF, (raw >> 8) & 0xFF])
    out(dev, ep, [R_EFFECT_OPERATION, block, 0x01, 0x01])   # restart


def set_effect(dev, ep, block, axes=0x01, dir0=0x00, dir1=0x00):
    """Upload constant force effect descriptor. axes byte: bit0=X, bit1=Y, bit2=dir_enable."""
    out(dev, ep, [
        R_SET_EFFECT,
        block, 0x01,          # block index, effect type = Constant Force
        0xff, 0x7f,            # duration = 32767 ms
        0x00, 0x00,            # trigger repeat = 0
        0x00, 0x00,            # sample period = 0
        0xff,                  # gain = max
        0x00,                  # trigger button = none
        axes,                  # axes / direction enable
        dir0, dir1,            # direction bytes
        0x00, 0x00,            # start delay = 0
    ])


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
        out(dev, ep, [R_DEVICE_CONTROL, 0x01])   # Enable actuators
        time.sleep(0.1)
        out(dev, ep, [R_DEVICE_GAIN, 0xff])       # Max gain
        time.sleep(0.1)

        block = 1
        set_effect(dev, ep, block)
        magnitude(dev, ep, block, 0)
        out(dev, ep, [R_EFFECT_OPERATION, block, 0x01, 0x01])  # Start
        time.sleep(0.1)

        # ── Pattern 1: Slam left, hold, slam right, hold ─────────────────
        print("Left / right slams")
        for _ in range(4):
            magnitude(dev, ep, block,  255);  time.sleep(0.8)
            magnitude(dev, ep, block, -255);  time.sleep(0.8)
        magnitude(dev, ep, block, 0);  time.sleep(0.4)

        # ── Pattern 2: Slow sine sweep — full travel ─────────────────────
        print("Slow sine sweep")
        t0 = time.time()
        while time.time() - t0 < 8:
            t = time.time() - t0
            magnitude(dev, ep, block, 255 * math.sin(2 * math.pi * t / 2.5))
            time.sleep(0.06)
        magnitude(dev, ep, block, 0);  time.sleep(0.4)

        # ── Pattern 3: Ramp → full tension → snap release ────────────────
        print("Tension and snap")
        for i in range(30):
            magnitude(dev, ep, block, i * 8)   # ramp 0 → 232 over 1.5 s
            time.sleep(0.05)
        magnitude(dev, ep, block, 255);  time.sleep(0.8)   # hold full tension
        magnitude(dev, ep, block,   0);  time.sleep(0.05)  # snap release
        magnitude(dev, ep, block, -255); time.sleep(0.3)   # rebound
        magnitude(dev, ep, block,   0);  time.sleep(0.5)

        # ── Pattern 4: Heartbeat — big thumps ────────────────────────────
        print("Heartbeat")
        for _ in range(5):
            magnitude(dev, ep, block,  255);  time.sleep(0.12)
            magnitude(dev, ep, block,    0);  time.sleep(0.10)
            magnitude(dev, ep, block,  180);  time.sleep(0.12)
            magnitude(dev, ep, block,    0);  time.sleep(0.55)

        # ── Pattern 5: Alternating slams, accelerating ───────────────────
        print("Accelerating slams")
        delay = 0.5
        for _ in range(16):
            magnitude(dev, ep, block,  255);  time.sleep(delay)
            magnitude(dev, ep, block, -255);  time.sleep(delay)
            delay *= 0.82   # speed up each cycle

        # ── Done ─────────────────────────────────────────────────────────
        magnitude(dev, ep, block, 0)
        out(dev, ep, [R_EFFECT_OPERATION, block, 0x03, 0x00])
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
