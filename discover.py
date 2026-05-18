#!/usr/bin/env python3
"""
Read and parse the HID report descriptor from the Sidewinder FF2.
Run with: sudo venv/bin/python3 discover.py

Prints report IDs, field names, bit sizes, and logical ranges so we can
construct correctly-encoded packets in demo.py.
"""
import usb.core
import usb.util

VID = 0x045e
PID = 0x001b
INTERFACE = 0

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

USAGE_NAMES = {
    # Generic Desktop
    (0x01, 0x30): "X",
    (0x01, 0x31): "Y",
    # PID
    (0x0F, 0x21): "Set Effect",
    (0x0F, 0x22): "Effect Block Index",
    (0x0F, 0x25): "Duration",
    (0x0F, 0x26): "Sample Period",
    (0x0F, 0x27): "Gain",
    (0x0F, 0x28): "Trigger Button",
    (0x0F, 0x29): "Trigger Repeat Interval",
    (0x0F, 0x2A): "Axes Enable",
    (0x0F, 0x2B): "Direction Enable",
    (0x0F, 0x2C): "Direction",
    (0x0F, 0x2D): "Type Specific Block Offset",
    (0x0F, 0x2E): "Block Type",
    (0x0F, 0x2F): "Set Envelope",
    (0x0F, 0x30): "Attack Level",
    (0x0F, 0x31): "Attack Time",
    (0x0F, 0x32): "Fade Level",
    (0x0F, 0x33): "Fade Time",
    (0x0F, 0x40): "Magnitude",
    (0x0F, 0x41): "Phase",
    (0x0F, 0x42): "Period",
    (0x0F, 0x50): "CP Offset",
    (0x0F, 0x51): "Positive Coefficient",
    (0x0F, 0x52): "Negative Coefficient",
    (0x0F, 0x53): "Positive Saturation",
    (0x0F, 0x54): "Negative Saturation",
    (0x0F, 0x55): "Dead Band",
    (0x0F, 0x57): "Set Condition",
    (0x0F, 0x58): "Type Specific Block Handle",
    (0x0F, 0x70): "Set Periodic",
    (0x0F, 0x73): "Set Constant Force",
    (0x0F, 0x77): "Effect Operation",
    (0x0F, 0x78): "Op Effect Start",
    (0x0F, 0x79): "Op Effect Start Solo",
    (0x0F, 0x7A): "Op Effect Stop",
    (0x0F, 0x7B): "Loop Count",
    (0x0F, 0x7E): "Device Gain",
    (0x0F, 0x7F): "Device Gain Report",
    (0x0F, 0x89): "Block Load Report",
    (0x0F, 0x8B): "Block Load Status",
    (0x0F, 0x8C): "Block Load Full",
    (0x0F, 0x8D): "Block Load Error",
    (0x0F, 0x8E): "Block Handle",
    (0x0F, 0x8F): "Block Free Report",
    (0x0F, 0x90): "Type Specific Block Handle",
    (0x0F, 0x95): "Device Control",
    (0x0F, 0x96): "Device Control Report",
    (0x0F, 0x97): "DC Enable Actuators",
    (0x0F, 0x98): "DC Disable Actuators",
    (0x0F, 0x99): "DC Stop All Effects",
    (0x0F, 0x9A): "DC Device Reset",
    (0x0F, 0x9B): "DC Device Pause",
    (0x0F, 0x9C): "DC Device Continue",
    (0x0F, 0xA7): "Actuator Power",
    (0x0F, 0xAB): "Create New Effect",
    (0x0F, 0xAC): "RAM Pool Available",
    (0x0F, 0xC0): "CP Offset",
    (0x0F, 0xC1): "Positive Coefficient",
    (0x0F, 0xC2): "Negative Coefficient",
    (0x0F, 0xC3): "Positive Saturation",
    (0x0F, 0xC4): "Negative Saturation",
    (0x0F, 0xC5): "Dead Band",
}


def parse_descriptor_fields(raw):
    """
    Full HID descriptor parser that tracks logical min/max, report size/count,
    and emits one entry per field with its bit width and logical range.
    """
    i = 0
    # Global state
    usage_page = 0
    logical_min = 0
    logical_max = 0
    report_size = 0   # bits per field
    report_count = 0  # number of fields
    report_id = None
    # Local state
    usages = []
    usage_min = None
    usage_max = None

    results = []  # list of dicts

    def sign_extend(val, bits):
        if val >= (1 << (bits - 1)):
            val -= (1 << bits)
        return val

    while i < len(raw):
        b = raw[i]
        size = b & 0x03
        typ  = (b >> 2) & 0x03
        tag  = (b >> 4) & 0x0F

        if size == 0:
            val = 0; i += 1
        elif size == 1:
            val = raw[i + 1]; i += 2
        elif size == 2:
            val = raw[i + 1] | (raw[i + 2] << 8); i += 3
        else:
            val = int.from_bytes(raw[i+1:i+5], 'little'); i += 5

        # --- Global items ---
        if typ == 1:
            if tag == 0:   usage_page   = val
            elif tag == 1: logical_min  = sign_extend(val, size * 8) if size else 0
            elif tag == 2: logical_max  = sign_extend(val, size * 8) if size else 0
            elif tag == 7: report_size  = val
            elif tag == 8: report_id    = val
            elif tag == 9: report_count = val

        # --- Local items ---
        elif typ == 2:
            if tag == 0:   usages.append((usage_page, val))
            elif tag == 1: usage_min = (usage_page, val)
            elif tag == 2: usage_max = (usage_page, val)

        # --- Main items ---
        elif typ == 0:
            if tag in (8, 9, 11):  # Input / Output / Feature
                kind = {8: 'INPUT', 9: 'OUTPUT', 11: 'FEATURE'}[tag]

                # Expand usage min/max range if set
                if usage_min is not None and usage_max is not None:
                    for u in range(usage_min[1], usage_max[1] + 1):
                        usages.append((usage_min[0], u))
                    usage_min = usage_max = None

                for idx in range(report_count):
                    u = usages[idx] if idx < len(usages) else (usage_page, 0)
                    name = USAGE_NAMES.get(u, f"0x{u[0]:02X}/0x{u[1]:02X}")
                    results.append({
                        'report_id': report_id,
                        'kind': kind,
                        'usage': u,
                        'name': name,
                        'bits': report_size,
                        'logical_min': logical_min,
                        'logical_max': logical_max,
                    })

                # Reset local state
                usages = []

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

        raw = dev.ctrl_transfer(0x81, 0x06, 0x2200, INTERFACE, 4096)
        print(f"\nRaw descriptor ({len(raw)} bytes):")
        print(" ".join(f"{b:02x}" for b in raw))

        fields = parse_descriptor_fields(raw)

        # Group by report_id + kind
        from collections import defaultdict
        by_report = defaultdict(list)
        for f in fields:
            by_report[(f['report_id'], f['kind'])].append(f)

        print("\n\nDetailed field layout per report:")
        for (rid, kind), flist in sorted(by_report.items()):
            byte_offset = 1  # after report ID byte
            bit_offset = 0
            print(f"\n  Report ID {rid}  [{kind}]")
            print(f"    {'byte':>5}  {'bits':>4}  {'logical range':>20}  field")
            for f in flist:
                bstr = f"[{byte_offset}.{bit_offset}]" if bit_offset else f"[{byte_offset}]"
                rng = f"{f['logical_min']}..{f['logical_max']}"
                print(f"    {bstr:>5}  {f['bits']:>4}  {rng:>20}  {f['name']}")
                bit_offset += f['bits']
                byte_offset += bit_offset // 8
                bit_offset %= 8

    finally:
        if reattach:
            try:
                dev.attach_kernel_driver(INTERFACE)
            except Exception:
                pass
        usb.util.dispose_resources(dev)


if __name__ == "__main__":
    main()
