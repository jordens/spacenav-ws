import asyncio

from spacenav_ws.controller import Controller, filter_motion_sample
from spacenav_ws.types import MotionAxesMode, MotionSample, NavigationMode
from spacenav_ws.wamp import WampSession


class DummyWebSocket:
    async def accept(self, subprotocol=None):
        return None

    async def send_json(self, payload):
        return None


class DummyReader:
    async def readexactly(self, n):
        raise NotImplementedError


def make_controller(client_metadata=None):
    reader = DummyReader()
    session = WampSession(DummyWebSocket())
    return Controller(
        reader=reader,
        wamp_state_handler=session,
        client_metadata=client_metadata or {"name": "Onshape", "version": 0.6},
    )


def test_zero_motion_sample_stops_motion():
    controller = make_controller()
    calls = []

    async def fake_set_motion(active: bool):
        calls.append(active)

    controller.focus = True
    controller.subscribed = True
    controller.motion_active = True
    controller.bridge.set_motion = fake_set_motion

    asyncio.run(controller._handle_motion(MotionSample(tx=0, ty=0, tz=0, rx=0, ry=0, rz=0, period_ms=8)))

    assert calls == [False]
    assert controller.motion_active is False


async def _exercise_focus_drop():
    controller = make_controller()
    calls = []

    async def fake_set_motion(active: bool):
        calls.append(active)

    controller.bridge.set_motion = fake_set_motion
    controller.motion_active = True

    await controller.client_update(controller.id, {"focus": False})
    return controller, calls


def test_focus_drop_stops_motion():
    controller, calls = asyncio.run(_exercise_focus_drop())

    assert calls == [False]
    assert controller.motion_active is False


async def _exercise_idle_stop():
    controller = make_controller()
    calls = []

    async def fake_set_motion(active: bool):
        calls.append(active)

    controller.bridge.set_motion = fake_set_motion
    controller.motion_active = True
    controller.last_motion_at = 0.0
    controller.stop_idle_timeout_s = 0.01

    task = asyncio.create_task(controller._stop_idle_loop())
    try:
        await asyncio.sleep(0.03)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return controller, calls


def test_quiescence_stops_motion():
    controller, calls = asyncio.run(_exercise_idle_stop())

    assert calls == [False]
    assert controller.motion_active is False


def test_each_motion_sample_reads_fresh_navigation_state():
    controller = make_controller()
    controller.focus = True
    controller.subscribed = True
    event = MotionSample(tx=1, ty=0, tz=0, rx=0, ry=0, rz=0, period_ms=8)
    calls = []

    async def fake_set_motion(active: bool):
        calls.append(("motion", active))

    async def fake_read_navigation_state():
        calls.append(("read", None))
        raise RuntimeError("stop after fresh state read")

    controller.bridge.set_motion = fake_set_motion
    controller.bridge.read_navigation_state = fake_read_navigation_state

    try:
        asyncio.run(controller._handle_motion(event))
    except RuntimeError as exc:
        assert str(exc) == "stop after fresh state read"

    assert calls == [("motion", True), ("read", None)]


def test_first_active_sample_zeros_dt_at_gesture_start():
    controller = make_controller()
    controller.focus = True
    controller.subscribed = True
    event = MotionSample(tx=1, ty=0, tz=0, rx=0, ry=0, rz=0, period_ms=1234)
    seen = {}

    async def fake_set_motion(active: bool):
        return None

    async def fake_read_navigation_state():
        return object()

    async def fake_write_navigation_state(next_state, previous_state=None):
        return None

    controller.bridge.set_motion = fake_set_motion
    controller.bridge.read_navigation_state = fake_read_navigation_state
    controller.bridge.write_navigation_state = fake_write_navigation_state

    from spacenav_ws import controller as controller_module

    original_apply_motion = controller_module.apply_motion_with_mode

    def fake_apply_motion(state, sample, config, mode):
        seen["period_ms"] = sample.period_ms
        seen["mode"] = mode
        raise RuntimeError("stop after apply_motion capture")

    controller_module.apply_motion_with_mode = fake_apply_motion
    try:
        try:
            asyncio.run(controller._handle_motion(event))
        except RuntimeError as exc:
            assert str(exc) == "stop after apply_motion capture"
    finally:
        controller_module.apply_motion_with_mode = original_apply_motion

    assert seen["period_ms"] == 0
    assert seen["mode"] is NavigationMode.OBJECT


def test_noninitial_sample_preserves_daemon_period_ms():
    controller = make_controller()
    controller.focus = True
    controller.subscribed = True
    controller.motion_active = True
    event = MotionSample(tx=1, ty=0, tz=0, rx=0, ry=0, rz=0, period_ms=42)
    seen = {}

    async def fake_read_navigation_state():
        return object()

    async def fake_write_navigation_state(next_state, previous_state=None):
        return None

    controller.bridge.read_navigation_state = fake_read_navigation_state
    controller.bridge.write_navigation_state = fake_write_navigation_state

    from spacenav_ws import controller as controller_module

    original_apply_motion = controller_module.apply_motion_with_mode

    def fake_apply_motion(state, sample, config, mode):
        seen["period_ms"] = sample.period_ms
        raise RuntimeError("stop after apply_motion capture")

    controller_module.apply_motion_with_mode = fake_apply_motion
    try:
        try:
            asyncio.run(controller._handle_motion(event))
        except RuntimeError as exc:
            assert str(exc) == "stop after apply_motion capture"
    finally:
        controller_module.apply_motion_with_mode = original_apply_motion

    assert seen["period_ms"] == 42


def test_button_0_toggles_navigation_mode():
    controller = make_controller()
    controller.focus = True
    controller.subscribed = True

    asyncio.run(controller._handle_button(0))
    assert controller.mode is NavigationMode.TARGET_CAMERA

    asyncio.run(controller._handle_button(0))
    assert controller.mode is NavigationMode.OBJECT


def test_button_1_cycles_motion_axes_mode():
    controller = make_controller()
    controller.focus = True
    controller.subscribed = True

    asyncio.run(controller._handle_button(1))
    assert controller.axes_mode is MotionAxesMode.ROTATION_ONLY

    asyncio.run(controller._handle_button(1))
    assert controller.axes_mode is MotionAxesMode.TRANSLATION_ONLY

    asyncio.run(controller._handle_button(1))
    assert controller.axes_mode is MotionAxesMode.ALL


def test_filter_motion_sample_zeroes_disabled_axes():
    sample = MotionSample(tx=1, ty=2, tz=3, rx=4, ry=5, rz=6, period_ms=7)

    rotation_only = filter_motion_sample(sample, MotionAxesMode.ROTATION_ONLY)
    assert rotation_only == MotionSample(tx=0, ty=0, tz=0, rx=4, ry=5, rz=6, period_ms=7)

    translation_only = filter_motion_sample(sample, MotionAxesMode.TRANSLATION_ONLY)
    assert translation_only == MotionSample(tx=1, ty=2, tz=3, rx=0, ry=0, rz=0, period_ms=7)


def test_button_toggle_does_not_require_focus_or_subscription():
    controller = make_controller()

    asyncio.run(controller._handle_button(0))
    assert controller.mode is NavigationMode.TARGET_CAMERA
