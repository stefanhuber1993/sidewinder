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
