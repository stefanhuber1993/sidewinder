#!/usr/bin/env python3
"""
Dump and parse the HID report descriptor from the Sidewinder FF2.

Run: venv/bin/python3 discover.py

Prints every report ID with its field names, bit widths, and logical ranges —
the ground truth for the packet layouts encoded in sidewinder/ff2.py. Report IDs
are device-specific (declared in the descriptor, not fixed by the PID spec), so
this is the tool to check against if a report ever stops behaving.

Reads the descriptor through hidapi/IOKit — no sudo, no libusb.
"""
import hid

VID = 0x045e
PID = 0x001b

# Usage names: Generic Desktop (0x01), Button (0x09), Physical Interface (0x0F).
# PID names follow the USB Physical Interface Device spec 1.0 usage table.
USAGE_NAMES = {
    (0x01, 0x01): "Pointer",
    (0x01, 0x04): "Joystick",
    (0x01, 0x30): "X",
    (0x01, 0x31): "Y",
    (0x01, 0x32): "Z",
    (0x01, 0x35): "Rz",
    (0x01, 0x36): "Slider",
    (0x01, 0x39): "Hat Switch",
    (0x01, 0x3B): "Byte Count",
    (0x0A, 0x01): "Instance 1",
    (0x0A, 0x02): "Instance 2",
    (0x0F, 0x01): "Physical Interface Device",
    (0x0F, 0x21): "Set Effect Report",
    (0x0F, 0x22): "Effect Block Index",
    (0x0F, 0x23): "Parameter Block Offset",
    (0x0F, 0x24): "ROM Flag",
    (0x0F, 0x25): "Effect Type",
    (0x0F, 0x26): "ET Constant Force",
    (0x0F, 0x27): "ET Ramp",
    (0x0F, 0x28): "ET Custom Force Data",
    (0x0F, 0x30): "ET Square",
    (0x0F, 0x31): "ET Sine",
    (0x0F, 0x32): "ET Triangle",
    (0x0F, 0x33): "ET Sawtooth Up",
    (0x0F, 0x34): "ET Sawtooth Down",
    (0x0F, 0x40): "ET Spring",
    (0x0F, 0x41): "ET Damper",
    (0x0F, 0x42): "ET Inertia",
    (0x0F, 0x43): "ET Friction",
    (0x0F, 0x50): "Duration",
    (0x0F, 0x51): "Sample Period",
    (0x0F, 0x52): "Gain",
    (0x0F, 0x53): "Trigger Button",
    (0x0F, 0x54): "Trigger Repeat Interval",
    (0x0F, 0x55): "Axes Enable",
    (0x0F, 0x56): "Direction Enable",
    (0x0F, 0x57): "Direction",
    (0x0F, 0x58): "Type Specific Block Offset",
    (0x0F, 0x59): "Block Type",
    (0x0F, 0x5A): "Set Envelope Report",
    (0x0F, 0x5B): "Attack Level",
    (0x0F, 0x5C): "Attack Time",
    (0x0F, 0x5D): "Fade Level",
    (0x0F, 0x5E): "Fade Time",
    (0x0F, 0x5F): "Set Condition Report",
    (0x0F, 0x60): "CP Offset",
    (0x0F, 0x61): "Positive Coefficient",
    (0x0F, 0x62): "Negative Coefficient",
    (0x0F, 0x63): "Positive Saturation",
    (0x0F, 0x64): "Negative Saturation",
    (0x0F, 0x65): "Dead Band",
    (0x0F, 0x66): "Download Force Sample",
    (0x0F, 0x68): "Custom Force Data Report",
    (0x0F, 0x69): "Custom Force Data",
    (0x0F, 0x6B): "Set Custom Force Report",
    (0x0F, 0x6C): "Custom Force Data Offset",
    (0x0F, 0x6D): "Sample Count",
    (0x0F, 0x6E): "Set Periodic Report",
    (0x0F, 0x6F): "Offset",
    (0x0F, 0x70): "Magnitude",
    (0x0F, 0x71): "Phase",
    (0x0F, 0x72): "Period",
    (0x0F, 0x73): "Set Constant Force Report",
    (0x0F, 0x74): "Set Ramp Force Report",
    (0x0F, 0x75): "Ramp Start",
    (0x0F, 0x76): "Ramp End",
    (0x0F, 0x77): "Effect Operation Report",
    (0x0F, 0x78): "Effect Operation",
    (0x0F, 0x79): "Op Effect Start",
    (0x0F, 0x7A): "Op Effect Start Solo",
    (0x0F, 0x7B): "Op Effect Stop",
    (0x0F, 0x7C): "Loop Count",
    (0x0F, 0x7D): "Device Gain Report",
    (0x0F, 0x7E): "Device Gain",
    (0x0F, 0x7F): "PID Pool Report",
    (0x0F, 0x80): "RAM Pool Size",
    (0x0F, 0x83): "Simultaneous Effects Max",
    (0x0F, 0x89): "PID Block Load Report",
    (0x0F, 0x8B): "Block Load Status",
    (0x0F, 0x8C): "Block Load Success",
    (0x0F, 0x8D): "Block Load Full",
    (0x0F, 0x8E): "Block Load Error",
    (0x0F, 0x90): "PID Block Free Report",
    (0x0F, 0x92): "PID State Report",
    (0x0F, 0x94): "Effect Playing",
    (0x0F, 0x95): "PID Device Control Report",
    (0x0F, 0x96): "PID Device Control",
    (0x0F, 0x97): "DC Enable Actuators",
    (0x0F, 0x98): "DC Disable Actuators",
    (0x0F, 0x99): "DC Stop All Effects",
    (0x0F, 0x9A): "DC Device Reset",
    (0x0F, 0x9B): "DC Device Pause",
    (0x0F, 0x9C): "DC Device Continue",
    (0x0F, 0x9F): "Device Paused",
    (0x0F, 0xA0): "Actuators Enabled",
    (0x0F, 0xA4): "Safety Switch",
    (0x0F, 0xA5): "Actuator Override Switch",
    (0x0F, 0xA6): "Actuator Power",
    (0x0F, 0xA7): "Start Delay",
    (0x0F, 0xA9): "Device Managed Pool",
    (0x0F, 0xAA): "Shared Parameter Blocks",
    (0x0F, 0xAB): "Create New Effect Report",
    (0x0F, 0xAC): "RAM Pool Available",
}


def parse_descriptor_fields(raw):
    """
    Walk the descriptor and emit one entry per data field, carrying the global
    state (logical range, bit width) that applies to it.

    Usages are consumed in order by each Main item. Collection items consume one
    usage too — skipping that would shift every field name in the report by one.
    """
    usage_page = 0
    logical_min = logical_max = 0
    report_size = report_count = 0
    report_id = None
    usages = []
    usage_min = usage_max = None
    collection_usage = []  # stack; an Array field is named by its collection

    results = []

    def sign_extend(val, bits):
        return val - (1 << bits) if val >= (1 << (bits - 1)) else val

    i = 0
    while i < len(raw):
        b = raw[i]
        size = b & 0x03
        typ = (b >> 2) & 0x03
        tag = (b >> 4) & 0x0F

        if size == 0:
            val = 0; i += 1
        elif size == 1:
            val = raw[i + 1]; i += 2
        elif size == 2:
            val = raw[i + 1] | (raw[i + 2] << 8); i += 3
        else:
            val = int.from_bytes(raw[i + 1:i + 5], "little"); i += 5

        if typ == 1:  # Global
            if tag == 0:   usage_page = val
            elif tag == 1: logical_min = sign_extend(val, size * 8) if size else 0
            elif tag == 2: logical_max = sign_extend(val, size * 8) if size else 0
            elif tag == 7: report_size = val
            elif tag == 8: report_id = val
            elif tag == 9: report_count = val

        elif typ == 2:  # Local
            # A 4-byte usage is fully qualified: high half is the page.
            def qualify(v):
                return (v >> 16, v & 0xFFFF) if size == 3 else (usage_page, v)
            if tag == 0:   usages.append(qualify(val))
            elif tag == 1: usage_min = qualify(val)
            elif tag == 2: usage_max = qualify(val)

        elif typ == 0:  # Main
            if tag == 10:  # Collection — consumes the usage naming it
                collection_usage.append(usages.pop(0) if usages else None)
                usage_min = usage_max = None
            elif tag == 12:  # End Collection
                if collection_usage:
                    collection_usage.pop()
                usages = []
            elif tag in (8, 9, 11):  # Input / Output / Feature
                kind = {8: "INPUT", 9: "OUTPUT", 11: "FEATURE"}[tag]
                if usage_min is not None and usage_max is not None:
                    usages += [(usage_min[0], u)
                               for u in range(usage_min[1], usage_max[1] + 1)]
                    usage_min = usage_max = None
                constant = bool(val & 0x01)  # Main item bit 0 = Constant (padding)
                array = not (val & 0x02)     # bit 1 = Variable; clear means Array
                for idx in range(report_count):
                    # An Array field carries a selector out of its usage list, so
                    # it is named by the enclosing collection, not by usages[idx].
                    if array and not constant and collection_usage:
                        u = collection_usage[-1]
                    else:
                        u = usages[idx] if idx < len(usages) else None
                    if constant or u is None:
                        name = "(padding)"
                    else:
                        name = USAGE_NAMES.get(u, f"0x{u[0]:02X}/0x{u[1]:02X}")
                    results.append({
                        "report_id": report_id,
                        "kind": kind,
                        "name": name,
                        "bits": report_size,
                        "logical_min": logical_min,
                        "logical_max": logical_max,
                    })
                usages = []

    return results


def open_joystick():
    devs = hid.enumerate(VID, PID)
    if not devs:
        raise SystemExit(f"Device not found (VID=0x{VID:04x} PID=0x{PID:04x}). Plugged in?")
    # The Joystick collection (usage page 1, usage 4) carries axes + PID reports.
    joystick = [d for d in devs if d.get("usage_page") == 1 and d.get("usage") == 4]
    return hid.Device(path=(joystick or devs)[0]["path"])


def main():
    h = open_joystick()
    print(f"Found: {h.manufacturer} {h.product}\n")

    raw = h.get_report_descriptor()
    print(f"Raw descriptor ({len(raw)} bytes):")
    print(" ".join(f"{b:02x}" for b in raw))

    from collections import defaultdict
    by_report = defaultdict(list)
    for f in parse_descriptor_fields(raw):
        by_report[(f["kind"], f["report_id"])].append(f)

    print("\n\nField layout per report:")
    for kind in ("INPUT", "OUTPUT", "FEATURE"):
        for (k, rid), fields in sorted(by_report.items(), key=lambda kv: (kv[0][1] or 0)):
            if k != kind:
                continue
            print(f"\n  Report 0x{rid:02x}  [{kind}]")
            print(f"    {'byte':>6}  {'bits':>4}  {'logical range':>16}  field")
            byte_off, bit_off = 1, 0
            for f in fields:
                pos = f"[{byte_off}.{bit_off}]" if bit_off else f"[{byte_off}]"
                rng = f"{f['logical_min']}..{f['logical_max']}"
                print(f"    {pos:>6}  {f['bits']:>4}  {rng:>16}  {f['name']}")
                bit_off += f["bits"]
                byte_off += bit_off // 8
                bit_off %= 8

    h.close()


if __name__ == "__main__":
    main()
