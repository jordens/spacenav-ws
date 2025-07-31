from __future__ import annotations

import struct
from typing import Union

from spacenav_ws.types import ButtonSample, MotionSample

PACKET_FORMAT = "iiiiiiii"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)

RawInputEvent = Union[MotionSample, ButtonSample]


def decode_packet(packet: bytes) -> RawInputEvent:
    if len(packet) != PACKET_SIZE:
        raise ValueError(f"Expected {PACKET_SIZE} bytes, got {len(packet)}")

    msg_type, a1, a2, a3, a4, a5, a6, a7 = struct.unpack(PACKET_FORMAT, packet)
    # Upstream spacenavd AF_UNIX protocol:
    #   UEV_MOTION  = 0
    #   UEV_PRESS   = 1
    #   UEV_RELEASE = 2
    # Motion packets carry raw axes in fields 1..6 and period_ms in field 7.
    if msg_type == 0:
        return MotionSample(tx=a1, ty=a2, tz=a3, rx=a4, ry=a5, rz=a6, period_ms=a7)
    if msg_type in (1, 2):
        return ButtonSample(button_id=a1, pressed=msg_type == 1)
    raise ValueError(f"Unknown spacenav packet type: {msg_type}")
