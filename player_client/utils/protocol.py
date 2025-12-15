import json
import struct

MAX_LEN = 64 * 1024


def send(sock, obj: dict):
    data = json.dumps(obj).encode("utf-8")
    header = struct.pack("!I", len(data))
    sock.sendall(header + data)


def recvall(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def recv(sock):
    header = recvall(sock, 4)
    if header is None:
        return None
    (length,) = struct.unpack("!I", header)
    body = recvall(sock, length)
    if body is None:
        return None
    return json.loads(body.decode("utf-8"))
