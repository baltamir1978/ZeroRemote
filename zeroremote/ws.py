# SPDX-License-Identifier: MIT
"""WebSocket mínimo (RFC 6455) sobre los streams de asyncio.

La biblioteca estándar no trae WebSocket y en el Cardputer no se instala nada con pip: basta
con el saludo, tramas de texto/binarias sin fragmentar, ping/pong y cierre. Los mensajes del
navegador son pequeños (teclas), así que se rechaza cualquier trama de más de 64 KB.
"""

import asyncio
import base64
import hashlib
import struct

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_INCOMING = 64 * 1024

OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA


def accept_key(client_key: str) -> str:
    """Sec-WebSocket-Accept para la Sec-WebSocket-Key del navegador."""
    digest = hashlib.sha1((client_key.strip() + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_frame(payload: bytes, opcode: int) -> bytes:
    """Trama del servidor: FIN, sin máscara (el servidor nunca enmascara)."""
    n = len(payload)
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([n])
    elif n < 1 << 16:
        head += bytes([126]) + struct.pack(">H", n)
    else:
        head += bytes([127]) + struct.pack(">Q", n)
    return head + payload


def unmask(data: bytes, mask: bytes) -> bytes:
    # Por bloques de enteros en vez de byte a byte: en el CM0 el bucle de Python se nota.
    n = len(data)
    if n == 0:
        return data
    reps = (n + 3) // 4
    key = int.from_bytes((mask * reps)[:n], "little")
    return (int.from_bytes(data, "little") ^ key).to_bytes(n, "little")


class ProtocolError(Exception):
    pass


async def read_frame(reader: asyncio.StreamReader):
    """Devuelve (opcode, payload). Las tramas del cliente tienen que venir enmascaradas."""
    b0, b1 = await reader.readexactly(2)
    opcode = b0 & 0x0F
    if not b0 & 0x80 or opcode == OP_CONT:
        raise ProtocolError("fragmented frames are not supported")
    if not b1 & 0x80:
        raise ProtocolError("client frames must be masked")
    n = b1 & 0x7F
    if n == 126:
        (n,) = struct.unpack(">H", await reader.readexactly(2))
    elif n == 127:
        (n,) = struct.unpack(">Q", await reader.readexactly(8))
    if n > MAX_INCOMING:
        raise ProtocolError("frame too large")
    mask = await reader.readexactly(4)
    return opcode, unmask(await reader.readexactly(n), mask)
