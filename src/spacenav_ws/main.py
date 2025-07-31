import asyncio
import logging
import os
from pathlib import Path

import typer
import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from rich.logging import RichHandler

from spacenav_ws.controller import create_mouse_controller
from spacenav_ws.navigation import DEFAULT_REMAP, NavigationConfig, parse_remap
from spacenav_ws.raw_input import PACKET_SIZE, decode_packet
from spacenav_ws.spacenav import get_async_spacenav_socket_reader
from spacenav_ws.wamp import WampSession

LOG_LEVEL = os.environ.get("SPACENAV_WS_LOG_LEVEL", "INFO").upper()

# TODO: This handler isn't used for the uvicorn logs and I can't be bothered finding the magic logging incantations to make it so.
logging.basicConfig(level=LOG_LEVEL, format="%(message)s", datefmt="[%X]", handlers=[RichHandler()])

ORIGINS = [
    "https://127.51.68.120",
    "https://127.51.68.120:8181",
    "https://3dconnexion.com",
    "https://cad.onshape.com",
]

PACKAGE_DATA_DIR = Path(__file__).parent / "data"
CERT_DIR = PACKAGE_DATA_DIR / "certs"

cli = typer.Typer()
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "OPTIONS"], allow_headers=["*"])


@app.get("/3dconnexion/nlproxy")
async def get_info():
    """HTTP info endpoint for the 3Dconnexion client. Returns which port the WAMP bridge will use and its version."""
    return {"port": 8181, "version": "1.4.8.21486"}


@app.get("/")
def homepage():
    """Tiny bit of HTML that displays mouse movement data"""
    html = """
    <html>
        <body>
            <h1>Mouse Stream</h1>
            <p>Move your spacemouse and motion data should appear here!</p>
            <pre id="output"></pre>
            <script>
                const evtSource = new EventSource("/events");
                const maxLines = 30;
                const lines = [];

                evtSource.onmessage = function(event) {
                    lines.push(event.data);
                    if (lines.length > maxLines) {lines.shift()}
                    document.getElementById("output").textContent = lines.join("\\n");
                };
            </script>
        </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=200)


async def get_mouse_event_generator():
    reader, _ = await get_async_spacenav_socket_reader()
    while True:
        mouse_event = await reader.readexactly(PACKET_SIZE)
        event_data = decode_packet(mouse_event)
        yield f"data: {event_data}\n\n"  # <- SSE format


@app.get("/events")
async def event_stream():
    """Stream mouse motion data"""
    return StreamingResponse(get_mouse_event_generator(), media_type="text/event-stream")


@app.websocket("/")
async def nlproxy(ws: WebSocket):
    """This is the websocket that webapplications should connect to for mouse data"""
    wamp_session = WampSession(ws)
    spacenav_reader, _ = await get_async_spacenav_socket_reader()
    remap = os.environ.get("SPACENAV_WS_REMAP", DEFAULT_REMAP)
    ctrl = await create_mouse_controller(wamp_session, spacenav_reader, nav_config=NavigationConfig(remap=remap))
    # TODO, better error handling then just dropping the websocket disconnect on the floor?
    async with asyncio.TaskGroup() as tg:
        tg.create_task(ctrl.start_mouse_event_stream(), name="mouse")
        tg.create_task(ctrl.wamp_state_handler.start_wamp_message_stream(), name="wamp")


@cli.command()
def serve(host: str = "127.51.68.120", port: int = 8181, hot_reload: bool = False, remap: str = DEFAULT_REMAP):
    """Start the server that sends spacenav to browser based applications like onshape"""
    parse_remap(remap)
    os.environ["SPACENAV_WS_REMAP"] = remap
    cert_file = CERT_DIR / f"{host}.crt"
    key_file = CERT_DIR / f"{host}.key"
    if not cert_file.exists() or not key_file.exists():
        raise typer.BadParameter(
            f"Missing TLS certs for {host}. Run: make certs HOST={host}",
            param_hint="host",
        )
    logging.warning(f"Navigate to: https://{host}:{port} You should be prompted to add the cert as an exception to your browser!!")
    uvicorn.run(
        "spacenav_ws.main:app",
        host=host,
        port=port,
        ws="auto",
        ssl_certfile=cert_file,
        ssl_keyfile=key_file,
        log_level=LOG_LEVEL.lower(),
        reload=hot_reload,
    )


@cli.command()
def read_mouse():
    """This echos the output from the spacenav socket, usefull for checking if things are working under the hood"""

    async def read_mouse_stream():
        logging.info("Start moving your mouse!")
        async for event in get_mouse_event_generator():
            logging.info(event.strip())

    asyncio.run(read_mouse_stream())


if __name__ == "__main__":
    cli()
