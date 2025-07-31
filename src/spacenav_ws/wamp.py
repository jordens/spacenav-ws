"""Basic WAMP V1 protocol."""

import asyncio
import logging
import os
import random
import string
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, ClassVar, Dict, NamedTuple, Optional, Type

from fastapi import WebSocket


WIRE_LOG_WAMP = os.environ.get("SPACENAV_WS_WIRE_LOG", "0") == "1"
DEFAULT_RPC_TIMEOUT_S = 2.0


def _rand_id(width: int) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=width))


class WAMP_MSG_TYPE(IntEnum):
    WELCOME = 0
    PREFIX = 1
    CALL = 2
    CALLRESULT = 3
    CALLERROR = 4
    SUBSCRIBE = 5
    UNSUBSCRIBE = 6
    PUBLISH = 7
    EVENT = 8


class WampMessage(tuple[Any, ...]):
    # This WampMessage class maintains a classvariable with all the registered message types!
    REGISTRY: Dict[WAMP_MSG_TYPE, Type["WampMessage"]] = {}
    MSG_TYPE: ClassVar[WAMP_MSG_TYPE]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        WampMessage.REGISTRY[cls.MSG_TYPE] = cls

    def serialize(self) -> list[Any]:
        return list(self)

    def serialize_with_msg_id(self) -> list[Any]:
        return [self.MSG_TYPE, *self.serialize()]


class Welcome(NamedTuple("WelcomeBase", [("session_id", str), ("version", int), ("server_ident", str)]), WampMessage):
    MSG_TYPE: ClassVar[WAMP_MSG_TYPE] = WAMP_MSG_TYPE.WELCOME


class Prefix(NamedTuple("PrefixBase", [("prefix", str), ("uri", str)]), WampMessage):
    MSG_TYPE: ClassVar[WAMP_MSG_TYPE] = WAMP_MSG_TYPE.PREFIX


class Call(NamedTuple("CallBase", [("call_id", str), ("proc_uri", str), ("args", list[Any])]), WampMessage):
    MSG_TYPE: ClassVar[WAMP_MSG_TYPE] = WAMP_MSG_TYPE.CALL

    def __new__(cls, call_id: str, proc_uri: str, *args: Any):
        return super().__new__(cls, call_id, proc_uri, list(args))

    def serialize(self) -> list[Any]:
        return [self.call_id, self.proc_uri, *self.args]

    @classmethod
    def create(cls, proc_uri: str, *args: Any):
        return Call(_rand_id(18), proc_uri, *args)


class CallResult(NamedTuple("CallResultBase", [("call_id", str), ("result", Any)]), WampMessage):
    MSG_TYPE: ClassVar[WAMP_MSG_TYPE] = WAMP_MSG_TYPE.CALLRESULT


class CallError(NamedTuple("CallErrorBase", [("call_id", str), ("error_uri", str), ("desc", str), ("details", Optional[Any])]), WampMessage):
    MSG_TYPE: ClassVar[WAMP_MSG_TYPE] = WAMP_MSG_TYPE.CALLERROR

    def __new__(cls, call_id: str, error_uri: str, desc: str, details: Optional[Any] = None):
        return super().__new__(cls, call_id, error_uri, desc, details)


class Subscribe(NamedTuple("SubscribeBase", [("topic", str)]), WampMessage):
    MSG_TYPE: ClassVar[WAMP_MSG_TYPE] = WAMP_MSG_TYPE.SUBSCRIBE


class Unsubscribe(NamedTuple("UnsubscribeBase", [("topic", str)]), WampMessage):
    MSG_TYPE: ClassVar[WAMP_MSG_TYPE] = WAMP_MSG_TYPE.UNSUBSCRIBE


class Publish(NamedTuple("PublishBase", [("topic", str), ("payload", Any)]), WampMessage):
    MSG_TYPE: ClassVar[WAMP_MSG_TYPE] = WAMP_MSG_TYPE.PUBLISH


class Event(NamedTuple("EventBase", [("topic", str), ("payload", Any)]), WampMessage):
    MSG_TYPE: ClassVar[WAMP_MSG_TYPE] = WAMP_MSG_TYPE.EVENT


class WampError(RuntimeError):
    pass


class WampClosedError(WampError):
    pass


class WampRpcTimeoutError(WampError):
    pass


class WampRpcRemoteError(WampError):
    pass


@dataclass
class InFlightRpc:
    gate: asyncio.Event
    result: Any = None
    error: Any = None


class WampProtocol:
    """
    https://wamp-proto.org/wamp_bp_latest_ietf.html#name-session-establishment Offcourse nothing is compliant and the Onshape client doesn't even send a HELLO lol.
    """

    def __init__(self, websocket: WebSocket):
        self._socket = websocket
        self._server_id = "snbridge v0.0.1"
        self._session_id = _rand_id(16)
        self._send_lock = asyncio.Lock()

        self.prefixes = {}
        self.call_handlers: dict[str, Callable[..., Awaitable[Any]]] = {}
        self.subscribe_handlers: dict[str, Callable[[Subscribe], Awaitable[Any]]] = {}

    async def begin(self):
        await self._socket.accept(subprotocol="wamp")
        await self.send_message(Welcome(self._session_id, 1, self._server_id))

    async def send_message(self, msg: WampMessage):
        if WIRE_LOG_WAMP:
            logging.debug(f"sending WAMP message: {msg=}")
        async with self._send_lock:
            await self._socket.send_json(msg.serialize_with_msg_id())

    async def next_message(self) -> WampMessage:
        data = await self._socket.receive_json()
        msg_type = WAMP_MSG_TYPE(data[0])
        msg = WampMessage.REGISTRY[msg_type](*data[1:])
        if WIRE_LOG_WAMP:
            logging.debug(f"received WAMP message: {msg=}")
        return msg

    async def run_message_handler(self, msg: WampMessage):
        # Introspect WampSession class for handlers called handle_{msg_type}
        handler = getattr(self, f"handle_{msg.MSG_TYPE.name.lower()}", self._handle_unimplemented_msg)
        return await handler(msg)

    async def _handle_unimplemented_msg(self, msg: WampMessage):
        logging.warning("Unhandled WAMP message type: %s", msg.MSG_TYPE)

    async def handle_prefix(self, msg: Prefix):
        self.prefixes[msg.prefix] = msg.uri

    async def handle_call(self, msg: Call):
        rpc_name = self.resolve(msg.proc_uri)
        rpc = self.call_handlers.get(rpc_name)

        if rpc is None:
            logging.warning("Unhandled WAMP RPC: %s", msg.proc_uri)
            await self.send_message(CallError(msg.call_id, "wamp.error.not_found", f"RPC {msg.proc_uri!r} not registered", details=None))
        else:
            await self.send_message(CallResult(msg.call_id, await rpc(*msg.args)))

    async def handle_subscribe(self, msg: Subscribe):
        topic = self.resolve(msg.topic)
        handler = self.subscribe_handlers.get(topic)
        if handler is None:
            logging.warning("Unknown subscribable: %s", topic)
        else:
            logging.debug(f"handle subscribe to '{topic}' by calling: {handler}")
            await handler(msg)

    async def handle_callresult(self, msg: CallResult):
        logging.warning("No callresult handler for msg: %s", msg)

    async def handle_callerror(self, msg: CallError):
        logging.warning("No callerror handler for msg: %s", msg)

    def resolve(self, uri: str) -> str:
        """Resolve any registered prefixes in the uri"""
        if ":" not in uri:
            return uri
        prefix, res = uri.split(":", 1)
        return self.prefixes.get(prefix, "") + res


class WampSession:
    def __init__(self, websocket: WebSocket, rpc_timeout_s: float = DEFAULT_RPC_TIMEOUT_S):
        self.wamp = WampProtocol(websocket)
        self.rpc_timeout_s = rpc_timeout_s

        self.in_flight_rpcs: dict[str, InFlightRpc] = {}
        self.closed = False
        self.close_error: BaseException | None = None

        self.wamp.handle_callresult = self.handle_callresult
        self.wamp.handle_callerror = self.handle_callerror

    async def close(self, exc: BaseException | None = None):
        if self.closed:
            return
        self.closed = True
        self.close_error = exc
        error = exc or WampClosedError("WAMP session closed")
        for rpc in self.in_flight_rpcs.values():
            rpc.error = error
            rpc.gate.set()

    async def start_wamp_message_stream(self):
        try:
            while True:
                msg = await self.wamp.next_message()
                await self.wamp.run_message_handler(msg)
        except BaseException as exc:
            await self.close(exc)
            raise

    async def client_rpc(self, controller_uri: str, method: str, *args):
        if self.closed:
            raise WampClosedError("WAMP session closed") from self.close_error

        call = Call.create(method, "", *args)
        rpc = InFlightRpc(gate=asyncio.Event())
        self.in_flight_rpcs[call.call_id] = rpc
        try:
            await self.wamp.send_message(Event(controller_uri, call.serialize_with_msg_id()))
            try:
                await asyncio.wait_for(rpc.gate.wait(), timeout=self.rpc_timeout_s)
            except TimeoutError as exc:
                rpc.error = WampRpcTimeoutError(f"WAMP RPC timed out after {self.rpc_timeout_s}s: {call.proc_uri}")
                raise rpc.error from exc

            if rpc.error is not None:
                if isinstance(rpc.error, BaseException):
                    raise rpc.error
                raise WampRpcRemoteError(str(rpc.error))
            return rpc.result
        except BaseException as exc:
            if not self.closed and not isinstance(exc, (WampRpcRemoteError, WampRpcTimeoutError)):
                await self.close(exc)
            raise
        finally:
            self.in_flight_rpcs.pop(call.call_id, None)

    async def handle_callresult(self, msg: CallResult):
        rpc = self.in_flight_rpcs.get(msg.call_id)
        if rpc is None:
            logging.warning("Ignoring unexpected WAMP callresult for %s", msg.call_id)
            return
        rpc.result = msg.result
        rpc.gate.set()

    async def handle_callerror(self, msg: CallError):
        rpc = self.in_flight_rpcs.get(msg.call_id)
        if rpc is None:
            logging.warning("Ignoring unexpected WAMP callerror for %s", msg.call_id)
            return
        rpc.error = WampRpcRemoteError(f"{msg.error_uri}: {msg.desc}")
        rpc.gate.set()
