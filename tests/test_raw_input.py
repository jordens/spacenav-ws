import struct

import pytest

from spacenav_ws.raw_input import PACKET_FORMAT, PACKET_SIZE, decode_packet
from spacenav_ws.types import ButtonSample, MotionSample


def test_decode_motion_packet_preserves_raw_axis_contract():
    # Upstream spacenavd/libspnav carries motion.period in milliseconds.
    packet = struct.pack(PACKET_FORMAT, 0, 10, 20, 30, 40, 50, 60, 70)

    event = decode_packet(packet)

    assert event == MotionSample(tx=10, ty=20, tz=30, rx=40, ry=50, rz=60, period_ms=70)


def test_decode_button_packet():
    pressed = struct.pack(PACKET_FORMAT, 1, 2, 0, 0, 0, 0, 0, 0)
    released = struct.pack(PACKET_FORMAT, 2, 2, 0, 0, 0, 0, 0, 0)

    assert decode_packet(pressed) == ButtonSample(button_id=2, pressed=True)
    assert decode_packet(released) == ButtonSample(button_id=2, pressed=False)


def test_decode_packet_rejects_wrong_size():
    with pytest.raises(ValueError):
        decode_packet(b"\x00" * (PACKET_SIZE - 1))
