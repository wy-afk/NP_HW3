# common/proto.py
#!/usr/bin/env python3
import json
import socket
import struct
from typing import Any, Dict

MAX_FRAME = 65536
HEADER_STRUCT = struct.Struct("!I")
DEFAULT_TIMEOUT = 300.0  # 5 minutes

class FramedSocket:
    def __init__(self, sock: socket.socket, timeout: float = DEFAULT_TIMEOUT):
        self.sock = sock
        self.sock.settimeout(timeout)

    # ---- raw framing ----
    def _recvn(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Socket closed during recvall")
            buf += chunk
        return buf

    def send_raw(self, data: bytes) -> None:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data must be bytes-like")
        length = len(data)
        if length > MAX_FRAME:
            raise ValueError("frame too large")
        self.sock.sendall(HEADER_STRUCT.pack(length))
        if length:
            self.sock.sendall(data)

    def recv_raw(self) -> bytes:
        header = self._recvn(HEADER_STRUCT.size)
        (length,) = HEADER_STRUCT.unpack(header)
        if length <= 0 or length > MAX_FRAME:
            raise ValueError("invalid frame length")
        return self._recvn(length)

    # ---- JSON helpers ----
    def send_json(self, obj: Dict[str, Any]) -> None:
        data = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.send_raw(data)

    def recv_json(self) -> Dict[str, Any]:
        data = self.recv_raw()
        return json.loads(data.decode("utf-8"))

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass

def connect(host: str, port: int, timeout: float = DEFAULT_TIMEOUT) -> FramedSocket:
    s = socket.create_connection((host, port), timeout=timeout)
    s.settimeout(timeout)
    return FramedSocket(s, timeout=timeout)
