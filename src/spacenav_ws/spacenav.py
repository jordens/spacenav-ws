import asyncio
import logging
import os
import socket
import sys

from spacenav_ws.raw_input import PACKET_SIZE, decode_packet

SPACENAV_SOCKET_PATH = os.environ.get("SPACENAV_SOCKET_PATH", "/var/run/spnav.sock")


def get_sync_spacenav_socket():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SPACENAV_SOCKET_PATH)
    return s


async def get_async_spacenav_socket_reader() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    try:
        return await asyncio.open_unix_connection(SPACENAV_SOCKET_PATH)
    except (FileNotFoundError, ConnectionRefusedError):
        logging.error("Space mouse not found at %s", SPACENAV_SOCKET_PATH)
        sys.exit(1)


if __name__ == "__main__":
    sock = get_sync_spacenav_socket()
    while True:
        chunk = sock.recv(PACKET_SIZE)
        print(decode_packet(chunk))
