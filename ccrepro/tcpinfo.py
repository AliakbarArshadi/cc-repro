"""Read the kernel's per-socket TCP state (struct tcp_info, include/uapi/linux/tcp.h).

This is what `ss -ti` prints, read directly with getsockopt(TCP_INFO) so we can
sample it every few milliseconds from inside the sender.
"""

import socket
import struct

TCP_INFO = getattr(socket, "TCP_INFO", 11)

# (name, offset, struct format). Offsets follow the uapi struct layout: 8 single
# bytes first (state, ca_state, ...), then 32- and 64-bit counters.
_FIELDS = [
    ("ca_state", 1, "B"),          # 0 Open, 1 Disorder, 2 CWR, 3 Recovery, 4 Loss
    ("rto_us", 8, "I"),
    ("snd_mss", 16, "I"),
    ("unacked", 24, "I"),          # packets in flight
    ("lost", 32, "I"),
    ("rtt_us", 68, "I"),           # smoothed RTT
    ("rttvar_us", 72, "I"),
    ("snd_ssthresh", 76, "I"),
    ("snd_cwnd", 80, "I"),         # in packets
    ("total_retrans", 100, "I"),
    ("pacing_rate", 104, "Q"),     # bytes/s
    ("bytes_acked", 120, "Q"),
    ("min_rtt_us", 148, "I"),
    ("delivery_rate", 160, "Q"),   # bytes/s, the kernel's own estimate
    ("bytes_sent", 200, "Q"),
    ("bytes_retrans", 208, "Q"),
]
SIZE = 232


def read(sock: socket.socket) -> dict:
    raw = sock.getsockopt(socket.IPPROTO_TCP, TCP_INFO, SIZE)
    return {name: struct.unpack_from("<" + fmt, raw, off)[0]
            for name, off, fmt in _FIELDS if off + struct.calcsize(fmt) <= len(raw)}
