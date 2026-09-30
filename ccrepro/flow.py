"""One bulk TCP flow: a receiver that measures goodput and a sender that samples cwnd.

    python3 -m ccrepro.flow recv --port 5000 --duration 30 --out rx.json
    python3 -m ccrepro.flow send --dst 10.0.2.1 --port 5000 --cc bbr --duration 30 --out tx.json

Goodput is measured at the receiver: bytes that actually arrived in order,
which is what an application sees. The sender aborts with RST when the time is
up, so data still sitting in its buffer is never counted.
"""

import argparse
import json
import socket
import struct
import threading
import time

from . import tcpinfo

CHUNK = 64 * 1024


def receive(port: int, duration: float, bin_s: float, out: str, ready: str | None) -> None:
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(1)
    if ready:
        open(ready, "w").close()
    conn, _ = srv.accept()
    # Keep draining after the measurement window instead of closing: closing
    # first would RST a sender that is still writing. The timeout covers the
    # case where the sender's own RST is lost (it happens at 50% loss).
    conn.settimeout(1.0)
    accepted = time.monotonic()
    buf = bytearray(1 << 20)
    bins = [0] * int(duration / bin_s + 1)
    t0 = None
    while True:
        try:
            n = conn.recv_into(buf)
        except socket.timeout:
            idle_since = t0 if t0 is not None else accepted
            if time.monotonic() - idle_since > duration + 5:
                break
            continue
        except ConnectionResetError:
            break
        if n == 0:
            break
        now = time.monotonic()
        if t0 is None:
            t0 = now
        i = int((now - t0) / bin_s)
        if i < len(bins):
            bins[i] += n
    total = sum(bins)
    with open(out, "w") as f:
        json.dump({"bin_s": bin_s, "bins": bins, "bytes": total,
                   "goodput_mbit": total * 8 / duration / 1e6}, f)


def send(dst: str, port: int, cc: str, duration: float, sample_ms: float, out: str) -> None:
    s = socket.socket()
    # Set before connect() so the handshake and slow start already use this algorithm.
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_CONGESTION, cc.encode())
    s.connect((dst, port))
    s.settimeout(0.5)   # so the loop re-checks the clock even when the send buffer is full

    samples, stop = [], threading.Event()
    t0 = time.monotonic()

    def sampler():
        while not stop.is_set():
            samples.append({"t": time.monotonic() - t0, **tcpinfo.read(s)})
            time.sleep(sample_ms / 1e3)

    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    payload = memoryview(b"\0" * CHUNK)
    while time.monotonic() - t0 < duration:
        try:
            s.send(payload)
        except socket.timeout:
            pass
        except (BrokenPipeError, ConnectionResetError):
            break
    stop.set()
    th.join()
    final = tcpinfo.read(s)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))  # RST on close
    s.close()
    with open(out, "w") as f:
        json.dump({"cc": cc, "final": final, "samples": samples}, f)


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="role", required=True)
    r = sub.add_parser("recv")
    r.add_argument("--port", type=int, default=5000)
    r.add_argument("--duration", type=float, required=True)
    r.add_argument("--bin", type=float, default=0.1)
    r.add_argument("--out", required=True)
    r.add_argument("--ready", help="file to create once listening")
    t = sub.add_parser("send")
    t.add_argument("--dst", required=True)
    t.add_argument("--port", type=int, default=5000)
    t.add_argument("--cc", required=True)
    t.add_argument("--duration", type=float, required=True)
    t.add_argument("--sample-ms", type=float, default=10)
    t.add_argument("--out", required=True)
    a = p.parse_args()
    if a.role == "recv":
        receive(a.port, a.duration, a.bin, a.out, a.ready)
    else:
        send(a.dst, a.port, a.cc, a.duration, a.sample_ms, a.out)


if __name__ == "__main__":
    main()
