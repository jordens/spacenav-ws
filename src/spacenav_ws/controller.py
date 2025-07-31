from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from spacenav_ws.navigation import NavigationConfig, apply_motion_with_mode, motion_activity
from spacenav_ws.onshape_bridge import OnshapeBridge
from spacenav_ws.raw_input import PACKET_SIZE, decode_packet
from spacenav_ws.types import ButtonSample, MotionSample, MotionAxesMode, NavigationMode
from spacenav_ws.wamp import Call, CallResult, Prefix, Subscribe, WampSession

SUPPORTED_CLIENTS = {"Onshape", "WebThreeJS Sample", "web_threejs.html"}
NAVIGATION_MODE_TOGGLE_BUTTON = 0
MOTION_AXES_CYCLE_BUTTON = 1
MODE_CYCLE = (
    NavigationMode.OBJECT,
    NavigationMode.TARGET_CAMERA,
)


def filter_motion_sample(sample: MotionSample, axes_mode: MotionAxesMode) -> MotionSample:
    if axes_mode is MotionAxesMode.ALL:
        return sample
    if axes_mode is MotionAxesMode.ROTATION_ONLY:
        return MotionSample(tx=0, ty=0, tz=0, rx=sample.rx, ry=sample.ry, rz=sample.rz, period_ms=sample.period_ms)
    return MotionSample(tx=sample.tx, ty=sample.ty, tz=sample.tz, rx=0, ry=0, rz=0, period_ms=sample.period_ms)


@dataclass
class Controller:
    reader: asyncio.StreamReader
    wamp_state_handler: WampSession
    client_metadata: dict[str, Any]
    nav_config: NavigationConfig = field(default_factory=NavigationConfig)
    stop_idle_timeout_s: float = 0.08

    def __post_init__(self):
        self.id = "controller0"
        self.subscribed = False
        self.focus = False
        self.bridge = OnshapeBridge(
            self.wamp_state_handler,
            self.controller_uri,
        )
        self.motion_active = False
        self.last_motion_at = 0.0
        self.latest_motion: MotionSample | None = None
        self.motion_ready = asyncio.Event()
        self.mode = NavigationMode.OBJECT
        self.axes_mode = MotionAxesMode.ALL
        self.wamp_state_handler.wamp.subscribe_handlers[self.controller_uri] = self.subscribe
        self.wamp_state_handler.wamp.call_handlers["wss://127.51.68.120/3dconnexion#update"] = self.client_update

    @property
    def controller_uri(self) -> str:
        return f"wss://127.51.68.120/3dconnexion3dcontroller/{self.id}"

    def is_supported_client(self) -> bool:
        return self.client_metadata.get("name") in SUPPORTED_CLIENTS

    async def subscribe(self, msg: Subscribe):
        logging.info("handling subscribe %s", msg)
        self.subscribed = True
        self.focus = True

    async def client_update(self, controller_id: str, args: dict[str, Any]):
        logging.debug("Got update for '%s': %s", controller_id, args)
        if (focus := args.get("focus")) is not None:
            self.focus = bool(focus)
            if not self.focus:
                await self._stop_motion()

    async def start_mouse_event_stream(self):
        logging.info("Starting the mouse stream")
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._poll_input_loop(), name="input")
            tg.create_task(self._motion_loop(), name="motion")
            tg.create_task(self._stop_idle_loop(), name="stop-idle")

    async def _poll_input_loop(self):
        while True:
            packet = await self.reader.readexactly(PACKET_SIZE)
            event = decode_packet(packet)
            if isinstance(event, MotionSample):
                await self._enqueue_motion(event)
            elif isinstance(event, ButtonSample) and event.pressed:
                await self._handle_button(event.button_id)

    async def _enqueue_motion(self, event: MotionSample):
        self.latest_motion = event
        self.motion_ready.set()

    async def _motion_loop(self):
        while True:
            await self.motion_ready.wait()
            self.motion_ready.clear()
            event = self.latest_motion
            self.latest_motion = None
            if event is None:
                continue
            await self._handle_motion(event)

    async def _handle_button(self, button_id: int):
        if not self.is_supported_client():
            return
        if button_id == NAVIGATION_MODE_TOGGLE_BUTTON:
            index = MODE_CYCLE.index(self.mode) if self.mode in MODE_CYCLE else 0
            self.mode = MODE_CYCLE[(index + 1) % len(MODE_CYCLE)]
            logging.info("Switched navigation mode to %s", self.mode.value)
            await self._stop_motion()
            return
        if button_id == MOTION_AXES_CYCLE_BUTTON:
            self.axes_mode = {
                MotionAxesMode.ALL: MotionAxesMode.ROTATION_ONLY,
                MotionAxesMode.ROTATION_ONLY: MotionAxesMode.TRANSLATION_ONLY,
                MotionAxesMode.TRANSLATION_ONLY: MotionAxesMode.ALL,
            }[self.axes_mode]
            logging.info("Switched motion axes mode to %s", self.axes_mode.value)
            await self._stop_motion()

    async def _handle_motion(self, event: MotionSample):
        if not (self.focus and self.subscribed and self.is_supported_client()):
            return
        self.last_motion_at = monotonic()

        sample = MotionSample(
            tx=event.tx,
            ty=event.ty,
            tz=event.tz,
            rx=event.rx,
            ry=event.ry,
            rz=event.rz,
            period_ms=max(0, event.period_ms),
        )
        sample = filter_motion_sample(sample, self.axes_mode)
        if motion_activity(sample, self.nav_config) <= 0.0:
            await self._stop_motion()
            return

        gesture_start = not self.motion_active
        if gesture_start:
            logging.debug("Starting motion gesture")
            await self.bridge.set_motion(True)
            self.motion_active = True

        logging.debug("Reading current navigation state")
        current_state = await self.bridge.read_navigation_state()
        # spacenavd's motion.period is time since the previous emitted motion event.
        # After idle silence, the first non-zero sample can carry a large period that
        # should not be integrated as active motion. Bootstrap the gesture with dt=0.
        if gesture_start:
            sample = MotionSample(
                tx=sample.tx,
                ty=sample.ty,
                tz=sample.tz,
                rx=sample.rx,
                ry=sample.ry,
                rz=sample.rz,
                period_ms=0,
            )

        next_state = apply_motion_with_mode(current_state, sample, self.nav_config, self.mode)
        logging.debug(
            "Writing navigation update tx=%s ty=%s tz=%s rx=%s ry=%s rz=%s dt_ms=%s",
            sample.tx,
            sample.ty,
            sample.tz,
            sample.rx,
            sample.ry,
            sample.rz,
            sample.period_ms,
        )
        await self.bridge.write_navigation_state(next_state, previous_state=current_state)

    async def _stop_idle_loop(self):
        while True:
            await asyncio.sleep(self.stop_idle_timeout_s / 4.0)
            if not self.motion_active:
                continue
            if monotonic() - self.last_motion_at > self.stop_idle_timeout_s:
                await self._stop_motion()

    async def _stop_motion(self):
        if self.motion_active:
            logging.debug("Stopping motion gesture")
            await self.bridge.set_motion(False)
        self.motion_active = False


async def create_mouse_controller(
    wamp_state_handler: WampSession,
    spacenav_reader: asyncio.StreamReader,
    nav_config: NavigationConfig | None = None,
) -> Controller:
    await wamp_state_handler.wamp.begin()
    msg = await wamp_state_handler.wamp.next_message()
    while isinstance(msg, Prefix):
        await wamp_state_handler.wamp.run_message_handler(msg)
        msg = await wamp_state_handler.wamp.next_message()

    assert isinstance(msg, Call)
    assert msg.proc_uri == "3dx_rpc:create" and msg.args[0] == "3dconnexion:3dmouse"
    mouse_id = "mouse0"
    logging.info('Created 3d mouse "%s" for version %s', mouse_id, msg.args[1])
    await wamp_state_handler.wamp.send_message(CallResult(msg.call_id, {"connexion": mouse_id}))

    msg = await wamp_state_handler.wamp.next_message()
    assert isinstance(msg, Call)
    assert msg.proc_uri == "3dx_rpc:create" and msg.args[0] == "3dconnexion:3dcontroller" and msg.args[1] == mouse_id
    metadata = msg.args[2]
    controller = Controller(spacenav_reader, wamp_state_handler, metadata, nav_config=nav_config or NavigationConfig())
    logging.info(
        'Created controller "%s" for mouse "%s", for client "%s", version "%s"',
        controller.id,
        mouse_id,
        metadata["name"],
        metadata["version"],
    )
    await wamp_state_handler.wamp.send_message(CallResult(msg.call_id, {"instance": controller.id}))
    return controller
