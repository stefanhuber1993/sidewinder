#!/usr/bin/env python3
"""
Read and parse the HID report descriptor from the Sidewinder FF2.
Run with: sudo venv/bin/python3 discover.py

This tells us which report IDs map to which HID PID functions
(Device Control, Set Effect, Constant Force, Effect Operation, etc.)
so we can construct the right packets in demo.py.
"""
import usb.core
import usb.util

VID = 0x045e
PID = 0x001b
INTERFACE = 0

# HID usage page / usage names for force feedback
FF_USAGES = {
    (0x0F, 0x21): "Set Effect Report",
    (0x0F, 0x5A): "Set Envelope Report",
    (0x0F, 0x73): "Set Constant Force",
    (0x0F, 0x70): "Set Periodic Report",
    (0x0F, 0x57): "Set Condition Report",
    (0x0F, 0x77): "Effect Operation Report",
    (0x0F, 0x7E): "Device Gain Report",
    (0x0F, 0x95): "Device Control Report",
    (0x0F, 0x96): "PID State Report",
    (0x0F, 0xAB): "Create New Effect",
    (0x0F, 0x89): "Block Load Report",
    (0x0F, 0x7F): "Block Free Report",
}

def parse_descriptor(raw):
    """
    Minimal HID descriptor parser — extracts report IDs and their
    associated usage page / usage so we can identify FF report types.
    """
    i = 0
    current_usage_page = 0
    current_usage = 0
    current_report_id = None
    report_type = None  # 'input', 'output', 'feature'
    results = []

    while i < len(raw):
        b = raw[i]
        size = b & 0x03
        typ  = (b >> 2) & 0x03
        tag  = (b >> 4) & 0x0F

        if size == 0:
            val = 0
            i += 1
        elif size == 1:
            val = raw[i + 1]
            i += 2
        elif size == 2:
            val = raw[i + 1] | (raw[i + 2] << 8)
            i += 3
        else:
            val = int.from_bytes(raw[i+1:i+5], 'little')
            i += 5

        # Global: Usage Page
        if typ == 1 and tag == 0:
            current_usage_page = val
        # Local: Usage
        elif typ == 2 and tag == 0:
            current_usage = val
        # Global: Report ID
        elif typ == 1 and tag == 8:
            current_report_id = val
        # Main: Input / Output / Feature
        elif typ == 0 and tag in (8, 9, 11):
            kind = {8: 'INPUT', 9: 'OUTPUT', 11: 'FEATURE'}[tag]
            key = (current_usage_page, current_usage)
            label = FF_USAGES.get(key, f"usagePage=0x{current_usage_page:02X} usage=0x{current_usage:02X}")
            results.append((current_report_id, kind, label))

    return results


def main():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        print(f"Device not found (VID=0x{VID:04x} PID=0x{PID:04x}). Is it plugged in?")
        return

    print(f"Found: {dev.manufacturer} {dev.product}")

    reattach = False
    try:
        if dev.is_kernel_driver_active(INTERFACE):
            dev.detach_kernel_driver(INTERFACE)
            reattach = True

        dev.set_configuration()

        # Fetch HID report descriptor via GET_DESCRIPTOR control transfer
        # bmRequestType=0x81 (IN, Standard, Interface), bRequest=0x06 (GET_DESCRIPTOR)
        # wValue=0x2200 (HID Report Descriptor, type 0x22), wIndex=interface
        raw = dev.ctrl_transfer(0x81, 0x06, 0x2200, INTERFACE, 512)

        print(f"\nRaw descriptor ({len(raw)} bytes):")
        print(" ".join(f"{b:02x}" for b in raw))

        print("\nParsed reports:")
        print(f"  {'ID':>4}  {'TYPE':8}  FUNCTION")
        print(f"  {'--':>4}  {'----':8}  --------")
        seen = set()
        for report_id, kind, label in parse_descriptor(raw):
            key = (report_id, kind)
            if key not in seen:
                seen.add(key)
                print(f"  {report_id:>4}  {kind:8}  {label}")

    finally:
        if reattach:
            try:
                dev.attach_kernel_driver(INTERFACE)
            except Exception:
                pass
        usb.util.dispose_resources(dev)


if __name__ == "__main__":
    main()
