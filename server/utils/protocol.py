# server/utils/protocol.py
import json
import struct

MAX_LEN = 64 * 1024  # 64 KiB


def send(sock, obj: dict):
    """
    Send a Python dict as a JSON message with 4-byte length prefix.
    """
    data = json.dumps(obj).encode("utf-8")
    length = len(data)
    if length > MAX_LEN:
        raise ValueError(f"Message too large: {length} bytes")

    header = struct.pack("!I", length)  # 4-byte uint32, network byte order
    sock.sendall(header + data)


def recvall(sock, n: int) -> bytes | None:
    """
    Receive exactly n bytes from socket (or None on EOF).
    """
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def recv(sock) -> dict | None:
    """
    Receive a JSON message (dict) framed with 4-byte length.
    Returns None if connection closed cleanly.
    """
    header = recvall(sock, 4)
    if header is None:
        return None

    (length,) = struct.unpack("!I", header)
    if length <= 0 or length > MAX_LEN:
        raise ValueError(f"Invalid length: {length}")

    body = recvall(sock, length)
    if body is None:
        return None

    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")
