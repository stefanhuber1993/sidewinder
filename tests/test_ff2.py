"""
Wire-encoding tests for sidewinder/ff2.py.

Every expected byte layout here is taken from the FF2's own HID report
descriptor — run `python3 discover.py` to print it. No hardware needed: the hid
module is replaced with a fake that records what would have been sent.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import sidewinder.ff2 as ff2mod
from sidewinder.ff2 import FF2Device, Effect, _le16, _s8, _angle_byte


class FakeHID:
    """Stands in for hid.Device; records writes, replays canned reads."""

    def __init__(self):
        self.writes = []
        self.features = []
        self.reads = []            # queued input reports for read()
        self.feature_responses = {}  # report_id -> bytes returned by get_feature_report
        self.closed = False

    def write(self, data):
        self.writes.append(list(data))
        return len(data)

    def send_feature_report(self, data):
        self.features.append(list(data))
        return len(data)

    def get_feature_report(self, report_id, size):
        return self.feature_responses[report_id]

    def read(self, size, timeout_ms):
        return self.reads.pop(0) if self.reads else []

    def close(self):
        self.closed = True


@pytest.fixture
def dev(monkeypatch):
    """An FF2Device wired to a FakeHID, with init traffic cleared."""
    fake = FakeHID()
    # Block Load: report id, block 1, status 1 (success), RAM available 1303
    fake.feature_responses[ff2mod.FR_PID_BLOCK_LOAD] = bytes([2, 1, 1, 0x17, 0x05])
    # PID Pool: RAM pool size 1350, 15 simultaneous effects, device-managed
    fake.feature_responses[ff2mod.FR_PID_POOL] = bytes([3, 0x46, 0x05, 15, 0x01])

    class FakeHidModule:
        Device = staticmethod(lambda path=None: fake)
        enumerate = staticmethod(
            lambda vid=None, pid=None: [
                {"path": b"fake", "usage_page": 1, "usage": 4},
            ]
        )

    monkeypatch.setattr(ff2mod, "hid", FakeHidModule)
    monkeypatch.setattr(ff2mod.time, "sleep", lambda _s: None)
    d = FF2Device()
    fake.writes.clear()
    d.fake = fake
    return d


# ── Encoding helpers ──────────────────────────────────────────────────────────

def test_le16_is_little_endian():
    assert _le16(0) == [0x00, 0x00]
    assert _le16(1) == [0x01, 0x00]
    assert _le16(32767) == [0xFF, 0x7F]
    assert _le16(0x1234) == [0x34, 0x12]


def test_le16_encodes_negatives_as_twos_complement():
    assert _le16(-1) == [0xFF, 0xFF]
    assert _le16(-255) == [0x01, 0xFF]


def test_s8_clamps_to_signed_byte_range():
    assert _s8(0) == 0x00
    assert _s8(127) == 0x7F
    assert _s8(-128) == 0x80
    assert _s8(-1) == 0xFF
    assert _s8(9999) == 0x7F    # clamped, not wrapped
    assert _s8(-9999) == 0x80


def test_angle_byte_maps_degrees_onto_0_255():
    assert _angle_byte(0) == 0
    assert _angle_byte(90) == 64
    assert _angle_byte(180) == 128
    assert _angle_byte(270) == 191
    assert _angle_byte(360) == 0     # wraps to zero
    assert _angle_byte(450) == 64    # 450 % 360 == 90


# ── Device control (report 0x0c) ──────────────────────────────────────────────

def test_device_control_and_gain_reports(dev):
    dev.enable()
    dev.disable()
    dev.stop_all()
    dev.pause()
    dev.resume()
    dev.set_gain(200)
    assert dev.fake.writes == [
        [0x0C, ff2mod.DC_ENABLE_ACTUATORS],
        [0x0C, ff2mod.DC_DISABLE_ACTUATORS],
        [0x0C, ff2mod.DC_STOP_ALL_EFFECTS],
        [0x0C, ff2mod.DC_DEVICE_PAUSE],
        [0x0C, ff2mod.DC_DEVICE_CONTINUE],
        [0x0D, 200],
    ]


def test_init_sequence_resets_enables_and_zeroes_state(dev, monkeypatch):
    # dev fixture clears writes, so rebuild one to observe construction traffic.
    fake = dev.fake
    fake.writes.clear()
    FF2Device()
    assert fake.writes == [
        [0x0C, ff2mod.DC_DEVICE_RESET],
        [0x0C, ff2mod.DC_ENABLE_ACTUATORS],
        [0x0D, 255],
        [0x0C, ff2mod.DC_STOP_ALL_EFFECTS],
    ]


# ── Effect allocation handshake ───────────────────────────────────────────────

def test_alloc_sends_create_new_effect_and_returns_block(dev):
    e = dev.alloc(ff2mod.ET_SPRING)
    assert dev.fake.features == [[ff2mod.FR_CREATE_NEW_EFFECT, ff2mod.ET_SPRING, 0x00, 0x00]]
    assert e.block == 1
    assert e.effect_type == ff2mod.ET_SPRING


def test_alloc_raises_when_device_pool_is_full(dev):
    dev.fake.feature_responses[ff2mod.FR_PID_BLOCK_LOAD] = bytes([2, 0, 2, 0, 0])
    with pytest.raises(RuntimeError, match="Full"):
        dev.alloc(ff2mod.ET_SINE)


# ── Set Effect (report 0x01) ──────────────────────────────────────────────────

def test_set_base_matches_descriptor_layout(dev):
    e = Effect(dev, block=3, effect_type=ff2mod.ET_CONSTANT_FORCE)
    e.set_base(duration_ms=1000, gain=255, direction_deg=90)
    assert dev.fake.writes == [[
        0x01,        # report id
        3,           # effect block index
        ff2mod.ET_CONSTANT_FORCE,
        0xE8, 0x03,  # duration 1000
        0x00, 0x00,  # trigger repeat interval
        0x00, 0x00,  # sample period
        255,         # gain
        0xFF,        # trigger button (none)
        0b111,       # axes enable X|Y + direction enable
        64, 0x00,    # direction instance 1 (90 deg), instance 2
        0x00, 0x00,  # start delay
    ]]


def test_set_base_axes_byte_packs_each_flag(dev):
    e = Effect(dev, block=1, effect_type=ff2mod.ET_SPRING)
    e.set_base(axis_x=True, axis_y=False, direction_enable=False)
    assert dev.fake.writes[0][11] == 0b001
    dev.fake.writes.clear()
    e.set_base(axis_x=False, axis_y=True, direction_enable=True)
    assert dev.fake.writes[0][11] == 0b110


# ── Effect parameter reports ──────────────────────────────────────────────────

def test_set_constant_force_is_signed_16_bit(dev):
    e = Effect(dev, block=2, effect_type=ff2mod.ET_CONSTANT_FORCE)
    e.set_constant_force(-255)
    assert dev.fake.writes == [[0x05, 2, 0x01, 0xFF]]


def test_set_periodic_matches_descriptor_layout(dev):
    e = Effect(dev, block=4, effect_type=ff2mod.ET_SINE)
    e.set_periodic(magnitude=180, offset=-10, phase_deg=180, period_ms=500)
    assert dev.fake.writes == [[
        0x04, 4,
        180,         # magnitude
        0xF6,        # offset -10
        128,         # phase 180 deg
        0xF4, 0x01,  # period 500
    ]]


def test_set_condition_matches_descriptor_layout(dev):
    e = Effect(dev, block=5, effect_type=ff2mod.ET_SPRING)
    e.set_condition(axis=1, cp_offset=-64, pos_coeff=127, neg_coeff=-127,
                    pos_sat=255, neg_sat=200, dead_band=10)
    assert dev.fake.writes == [[
        0x03, 5,
        1,           # parameter block offset (axis)
        0xC0,        # cp offset -64
        0x7F,        # positive coefficient
        0x81,        # negative coefficient -127
        255, 200, 10,
    ]]


def test_set_envelope_orders_levels_before_times(dev):
    e = Effect(dev, block=1, effect_type=ff2mod.ET_SINE)
    e.set_envelope(attack_level=50, attack_ms=100, fade_level=25, fade_ms=200)
    assert dev.fake.writes == [[0x02, 1, 50, 25, 0x64, 0x00, 0xC8, 0x00]]


def test_set_ramp_force_clamps_to_signed_bytes(dev):
    e = Effect(dev, block=1, effect_type=ff2mod.ET_RAMP)
    e.set_ramp_force(-127, 127)
    assert dev.fake.writes == [[0x06, 1, 0x81, 0x7F]]


# ── Effect operation (report 0x0a) and block free (0x0b) ──────────────────────

def test_play_stop_and_free_operations(dev):
    e = Effect(dev, block=7, effect_type=ff2mod.ET_SINE)
    e.play()
    e.play_solo(loop_count=3)
    e.stop()
    assert dev.fake.writes == [
        [0x0A, 7, ff2mod.OP_START, 0xFF],
        [0x0A, 7, ff2mod.OP_START_SOLO, 3],
        [0x0A, 7, ff2mod.OP_STOP, 0],
    ]


def test_free_stops_then_releases_the_block(dev):
    e = Effect(dev, block=7, effect_type=ff2mod.ET_SINE)
    e.free()
    assert dev.fake.writes == [
        [0x0A, 7, ff2mod.OP_STOP, 0],
        [0x0B, 7],
    ]


def test_effect_context_manager_frees_on_exit(dev):
    with Effect(dev, block=9, effect_type=ff2mod.ET_SINE):
        pass
    assert dev.fake.writes[-1] == [0x0B, 9]


# ── Factory methods ───────────────────────────────────────────────────────────

def test_constant_force_uploads_then_plays(dev):
    dev.constant_force(angle_deg=0, magnitude=200)
    report_ids = [w[0] for w in dev.fake.writes]
    assert report_ids == [0x01, 0x05, 0x0A]  # set effect, magnitude, play


def test_constant_force_adds_envelope_only_when_asked(dev):
    dev.constant_force(magnitude=100, attack_ms=50, fade_ms=50)
    assert [w[0] for w in dev.fake.writes] == [0x01, 0x02, 0x05, 0x0A]


def test_spring_uploads_a_condition_per_axis(dev):
    dev.spring(stiffness=100, cp_offset_x=64, cp_offset_y=-64)
    conditions = [w for w in dev.fake.writes if w[0] == 0x03]
    assert len(conditions) == 2
    assert conditions[0][2] == 0 and conditions[0][3] == 64      # X axis
    assert conditions[1][2] == 1 and conditions[1][3] == 0xC0    # Y axis


def test_spring_disables_direction_so_cp_offset_positions_the_stick(dev):
    dev.spring(stiffness=100)
    set_effect = next(w for w in dev.fake.writes if w[0] == 0x01)
    assert set_effect[11] == 0b011  # X|Y enabled, direction enable clear


def test_periodic_rejects_non_periodic_effect_types(dev):
    with pytest.raises(ValueError):
        dev.periodic(ff2mod.ET_SPRING)


def test_condition_rejects_non_condition_effect_types(dev):
    with pytest.raises(ValueError):
        dev.condition(ff2mod.ET_SINE)


def test_sine_helper_selects_the_sine_ordinal(dev):
    e = dev.sine(period_ms=100, magnitude=255)
    assert e.effect_type == ff2mod.ET_SINE


# ── Reading input reports ─────────────────────────────────────────────────────

def test_read_position_decodes_10_bit_signed_axes(dev):
    # x = 0x0E3|(0x03<<8) = 227|768 = 995 -> 995-1024 = -29 ; y = 6
    dev.fake.reads = [[1, 227, 255, 6, 0, 0, 0, 8]]
    x, y = dev.read_position()
    assert x == pytest.approx(-29 / 512.0)
    assert y == pytest.approx(6 / 512.0)


def test_read_position_centers_at_zero(dev):
    dev.fake.reads = [[1, 0, 0, 0, 0, 0, 0, 0]]
    assert dev.read_position() == (0.0, 0.0)


def test_read_position_decodes_full_deflection(dev):
    # x = 0 | (2 << 8) = 512 -> 512-1024 = -512 = full left
    dev.fake.reads = [[1, 0, 2, 0, 0]]
    assert dev.read_position() == (-1.0, 0.0)


def test_read_position_returns_newest_not_oldest_queued_report(dev):
    # A backlog of stale samples must not be replayed: the last one wins.
    dev.fake.reads = [
        [1, 0, 2, 0, 0],      # stale: full left
        [1, 100, 0, 0, 0],    # stale: x=100
        [1, 255, 1, 0, 0],    # newest: x = 255 | (1<<8) = 511 = full right
    ]
    x, _ = dev.read_position()
    assert x == pytest.approx(511 / 512.0)
    assert dev.fake.reads == []  # queue fully drained


def test_read_position_skips_interleaved_state_reports(dev):
    dev.fake.reads = [[2, 54, 0], [1, 0, 2, 0, 0]]
    assert dev.read_position() == (-1.0, 0.0)


def test_read_position_returns_none_when_nothing_ever_arrived(dev):
    dev.fake.reads = []
    assert dev.read_position() is None


def test_read_position_keeps_last_sample_when_queue_is_empty(dev):
    dev.fake.reads = [[1, 100, 0, 0, 0]]
    first = dev.read_position()
    assert dev.read_position() == first  # no new data: same answer, not None


def test_read_state_decodes_pid_state_flags(dev):
    # 54 = 0b0110110: actuators enabled, safety switch, actuator power
    dev.fake.reads = [[2, 54, 0x05]]
    assert dev.read_state() == {
        "device_paused": False,
        "actuators_enabled": True,
        "safety_switch": True,
        "actuator_override_switch": False,
        "actuator_power": True,
        "effect_playing": True,
        "block": 2,
    }


def test_read_state_reports_disabled_actuators(dev):
    dev.fake.reads = [[2, 52, 0x00]]  # bit 1 clear
    st = dev.read_state()
    assert st["actuators_enabled"] is False
    assert st["effect_playing"] is False


def test_read_state_returns_none_before_any_state_report(dev):
    dev.fake.reads = [[1, 0, 0, 0, 0]]  # only position traffic
    assert dev.read_state() is None


def test_read_state_caches_last_state_across_calls(dev):
    dev.fake.reads = [[2, 54, 0x05]]
    dev.read_state()
    dev.fake.reads = [[1, 0, 0, 0, 0]]  # only position traffic now
    assert dev.read_state()["effect_playing"] is True  # cached, not lost


def test_pump_does_not_let_position_reads_swallow_state_reports(dev):
    dev.fake.reads = [[2, 54, 0x05], [1, 100, 0, 0, 0]]
    dev.read_position()                      # drains both
    assert dev.read_state()["block"] == 2    # state survived the drain


def test_pool_info_decodes_feature_report_3(dev):
    assert dev.pool_info() == {
        "ram_pool_size": 1350,
        "simultaneous_effects_max": 15,
        "device_managed_pool": True,
        "shared_parameter_blocks": False,
    }


def test_ram_available_reads_block_load_report(dev):
    assert dev.ram_available() == 1303


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def test_close_stops_effects_and_closes_handle(dev):
    dev.close()
    assert dev.fake.writes[-1] == [0x0C, ff2mod.DC_STOP_ALL_EFFECTS]
    assert dev.fake.closed


def test_device_context_manager_closes(dev):
    with dev:
        pass
    assert dev.fake.closed
