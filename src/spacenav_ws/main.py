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
from spacenav_ws.spacenav import open_spacenav_connection
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
HOMEPAGE_HTML = """
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


@app.get("/3dconnexion/nlproxy")
async def nlproxy_info():
    """HTTP info endpoint for the 3Dconnexion client. Returns which port the WAMP bridge will use and its version."""
    return {"port": 8181, "version": "1.4.8.21486"}


@app.get("/")
def smoke_test_page():
    """Tiny bit of HTML that displays mouse movement data."""
    return HTMLResponse(content=HOMEPAGE_HTML, status_code=200)


async def iter_mouse_events():
    reader, _ = await open_spacenav_connection()
    while True:
        yield f"data: {decode_packet(await reader.readexactly(PACKET_SIZE))}\n\n"


@app.get("/events")
async def mouse_event_stream():
    """Stream mouse motion data."""
    return StreamingResponse(iter_mouse_events(), media_type="text/event-stream")


@app.websocket("/")
async def bridge_websocket(ws: WebSocket):
    """WebSocket endpoint for browser clients that speak the nlproxy WAMP protocol."""
    wamp_session = WampSession(ws)
    spacenav_reader, _ = await open_spacenav_connection()
    remap = os.environ.get("SPACENAV_WS_REMAP", DEFAULT_REMAP)
    controller = await create_mouse_controller(wamp_session, spacenav_reader, nav_config=NavigationConfig(remap=remap))
    # TODO, better error handling then just dropping the websocket disconnect on the floor?
    async with asyncio.TaskGroup() as tg:
        tg.create_task(controller.start_mouse_event_stream(), name="mouse")
        tg.create_task(controller.session.start_wamp_message_stream(), name="wamp")


@cli.command()
def serve(host: str = "127.51.68.120", port: int = 8181, hot_reload: bool = False, remap: str = DEFAULT_REMAP):
    """Start the server that sends spacenav to browser-based applications like Onshape."""
    parse_remap(remap)
    os.environ["SPACENAV_WS_REMAP"] = remap
    cert_file = CERT_DIR / f"{host}.crt"
    key_file = CERT_DIR / f"{host}.key"
    if not cert_file.exists() or not key_file.exists():
        raise typer.BadParameter(
            f"Missing TLS certs for {host}. Run: make certs HOST={host}",
            param_hint="host",
        )
    logging.warning("Navigate to: https://%s:%s You should be prompted to add the cert as an exception to your browser.", host, port)
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


@cli.command("read-mouse")
def read_mouse_events():
    """Echo raw decoded events from the spacenav socket."""

    async def log_mouse_stream():
        logging.info("Start moving your mouse!")
        async for event in iter_mouse_events():
            logging.info(event.strip())

    asyncio.run(log_mouse_stream())


if __name__ == "__main__":
    cli()
