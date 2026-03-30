import asyncio
import logging
import os
import sys

SPACENAV_SOCKET_PATH = os.environ.get("SPACENAV_SOCKET_PATH", "/var/run/spnav.sock")


async def open_spacenav_connection() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    try:
        return await asyncio.open_unix_connection(SPACENAV_SOCKET_PATH)
    except (FileNotFoundError, ConnectionRefusedError):
        logging.error("Space mouse not found at %s", SPACENAV_SOCKET_PATH)
        sys.exit(1)
