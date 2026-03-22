# telegram_proxy/socks5.py
"""Minimal SOCKS5 server implementation (RFC 1928).

Supports only what Telegram needs:
- No authentication (METHOD 0x00)
- CONNECT command (CMD 0x01)
- IPv4 (ATYP 0x01) and Domain (ATYP 0x03) address types
"""

import asyncio
import struct
import logging
from typing import Optional

log = logging.getLogger("tg_proxy.socks5")

# SOCKS5 constants
SOCKS_VER = 0x05
AUTH_NONE = 0x00
CMD_CONNECT = 0x01
ATYP_IPV4 = 0x01
ATYP_DOMAIN = 0x03
ATYP_IPV6 = 0x04
REP_SUCCESS = 0x00
REP_GENERAL_FAILURE = 0x01
REP_CONN_REFUSED = 0x05
REP_CMD_NOT_SUPPORTED = 0x07
REP_ATYP_NOT_SUPPORTED = 0x08


class Socks5Error(Exception):
    """SOCKS5 protocol error."""


async def handshake(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> Optional[tuple[str, int]]:
    """Perform SOCKS5 handshake. Returns (target_host, target_port) or None on error.

    Protocol flow:
    1. Client greeting -> Server method selection
    2. Client request (CONNECT) -> Server reply
    """
    try:
        return await _do_handshake(reader, writer)
    except (Socks5Error, asyncio.IncompleteReadError, ConnectionError, struct.error) as e:
        log.debug("SOCKS5 handshake failed: %s", e)
        return None
    except Exception:
        log.exception("Unexpected SOCKS5 error")
        return None


async def _do_handshake(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> Optional[tuple[str, int]]:
    # --- Phase 1: Greeting ---
    header = await asyncio.wait_for(reader.readexactly(2), timeout=10.0)
    ver, nmethods = struct.unpack("!BB", header)
    if ver != SOCKS_VER:
        raise Socks5Error(f"Bad SOCKS version: {ver}")

    methods = await reader.readexactly(nmethods)
    if AUTH_NONE not in methods:
        # No acceptable auth method
        writer.write(struct.pack("!BB", SOCKS_VER, 0xFF))
        await writer.drain()
        raise Socks5Error("Client doesn't support no-auth")

    # Accept no-auth
    writer.write(struct.pack("!BB", SOCKS_VER, AUTH_NONE))
    await writer.drain()

    # --- Phase 2: Request ---
    req_header = await asyncio.wait_for(reader.readexactly(4), timeout=10.0)
    ver, cmd, _rsv, atyp = struct.unpack("!BBBB", req_header)

    if ver != SOCKS_VER:
        raise Socks5Error(f"Bad version in request: {ver}")

    if cmd != CMD_CONNECT:
        _send_reply(writer, REP_CMD_NOT_SUPPORTED)
        await writer.drain()
        raise Socks5Error(f"Unsupported command: {cmd}")

    # Parse target address
    if atyp == ATYP_IPV4:
        raw_addr = await reader.readexactly(4)
        target_host = ".".join(str(b) for b in raw_addr)
    elif atyp == ATYP_DOMAIN:
        domain_len = (await reader.readexactly(1))[0]
        domain = await reader.readexactly(domain_len)
        target_host = domain.decode("ascii", errors="replace")
    elif atyp == ATYP_IPV6:
        raw_addr = await reader.readexactly(16)
        # Format as standard IPv6 string
        parts = struct.unpack("!8H", raw_addr)
        target_host = ":".join(f"{p:x}" for p in parts)
    else:
        _send_reply(writer, REP_ATYP_NOT_SUPPORTED)
        await writer.drain()
        raise Socks5Error(f"Unknown ATYP: {atyp}")

    raw_port = await reader.readexactly(2)
    target_port = struct.unpack("!H", raw_port)[0]

    # Send success reply (bound address 0.0.0.0:0)
    _send_reply(writer, REP_SUCCESS)
    await writer.drain()

    return (target_host, target_port)


def _send_reply(writer: asyncio.StreamWriter, rep: int) -> None:
    """Send SOCKS5 reply with bound address 0.0.0.0:0."""
    writer.write(struct.pack(
        "!BBBBIH",
        SOCKS_VER,  # VER
        rep,        # REP
        0x00,       # RSV
        ATYP_IPV4,  # ATYP
        0,          # BND.ADDR (0.0.0.0)
        0,          # BND.PORT (0)
    ))


def send_failure(writer: asyncio.StreamWriter, rep: int = REP_GENERAL_FAILURE) -> None:
    """Send failure reply. For use after handshake if tunnel setup fails."""
    _send_reply(writer, rep)
