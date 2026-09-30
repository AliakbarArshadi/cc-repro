"""Dumbbell topology built from Linux network namespaces -- no root needed.

    snd ──(netem: RTT/2 delay + random loss)──> rtr ──(tbf: rate + buffer)──> rcv
    snd <──────────────────────────────────── rtr <──(netem: RTT/2 delay)──── rcv

Three design rules, each of which breaks results silently if ignored:

1. Delay and bottleneck live on different links. netem has its own packet queue;
   if the rate limiter sat behind it, netem's queue would become an extra,
   unaccounted-for buffer and "buffer size" would stop meaning anything.
2. Segmentation offloads (TSO/GSO/GRO) are off. With them on, the kernel hands
   64 KB "super-packets" to the qdiscs, so tbf shapes bursts instead of packets.
3. Everything happens inside a private user+net+mount namespace (see enter()),
   so the host network is never touched and every run starts from a clean kernel
   TCP state (no cached ssthresh/RTT from a previous run).
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import asdict, dataclass

MTU = 1500
SND_IP, RCV_IP = "10.0.1.1", "10.0.2.1"


@dataclass(frozen=True)
class Link:
    rate_mbit: float = 100.0   # bottleneck bandwidth
    rtt_ms: float = 100.0      # base round-trip propagation delay
    buffer_bdp: float = 1.0    # bottleneck queue size, in multiples of the BDP
    loss_pct: float = 0.0      # random loss on the data path, percent

    @property
    def bdp_bytes(self) -> int:
        return int(self.rate_mbit * 1e6 / 8 * self.rtt_ms / 1e3)

    @property
    def buffer_bytes(self) -> int:
        # Never below two full packets, or tbf drops everything.
        return max(int(self.buffer_bdp * self.bdp_bytes), 2 * MTU)

    def as_dict(self) -> dict:
        return asdict(self) | {"bdp_bytes": self.bdp_bytes, "buffer_bytes": self.buffer_bytes}


def enter() -> None:
    """Re-exec the current program inside a fresh user+net+mount namespace.

    Inside, we are "root" (uid 0 mapped to the real user), which is enough to
    create veths and qdiscs in namespaces we own. /run gets a private tmpfs so
    `ip netns add` can create its mount points without touching the host.
    """
    if os.environ.get("CCREPRO_IN_NS") == "1":
        subprocess.run(["mount", "-t", "tmpfs", "tmpfs", "/run"], check=True)
        return
    env = os.environ | {"CCREPRO_IN_NS": "1"}
    main = sys.modules["__main__"]
    spec = getattr(main, "__spec__", None)
    # Re-run the same way we were started: `python -m pkg.mod` or `python file.py`.
    target = ["-m", spec.name] if spec else [sys.argv[0]]
    os.execvpe("unshare", ["unshare", "-rnm", "--", sys.executable, *target, *sys.argv[1:]], env)


def sh(*cmd: str) -> None:
    subprocess.run(cmd, check=True)


def ns(name: str, *cmd: str) -> None:
    sh("ip", "netns", "exec", name, *cmd)


def build(link: Link) -> None:
    for n in ("snd", "rtr", "rcv"):
        sh("ip", "netns", "add", n)
        ns(n, "ip", "link", "set", "lo", "up")
        # Room for several BDPs in flight; the defaults would cap cwnd on long-fat links.
        ns(n, "sysctl", "-qw", "net.ipv4.tcp_rmem=4096 131072 67108864")
        ns(n, "sysctl", "-qw", "net.ipv4.tcp_wmem=4096 16384 67108864")
        ns(n, "sysctl", "-qw", "net.ipv4.tcp_no_metrics_save=1")

    wires = [("snd", "s-r", SND_IP, "rtr", "r-s", "10.0.1.2"),
             ("rcv", "d-r", RCV_IP, "rtr", "r-d", "10.0.2.2")]
    for a, a_if, a_ip, b, b_if, b_ip in wires:
        sh("ip", "link", "add", a_if, "type", "veth", "peer", "name", b_if)
        for node, ifc, ip in ((a, a_if, a_ip), (b, b_if, b_ip)):
            sh("ip", "link", "set", ifc, "netns", node)
            ns(node, "ip", "addr", "add", f"{ip}/24", "dev", ifc)
            ns(node, "ethtool", "-K", ifc, "tso", "off", "gso", "off", "gro", "off")
            ns(node, "ip", "link", "set", ifc, "up")
    ns("snd", "ip", "route", "add", "default", "via", "10.0.1.2")
    ns("rcv", "ip", "route", "add", "default", "via", "10.0.2.2")
    ns("rtr", "sysctl", "-qw", "net.ipv4.ip_forward=1")

    half = f"{link.rtt_ms / 2}ms"
    # netem's own limit must hold a full one-way BDP of packets so it never drops.
    netem_limit = str(max(10_000, 4 * link.bdp_bytes // MTU))
    data_path = ["netem", "delay", half, "limit", netem_limit]
    if link.loss_pct > 0:
        data_path += ["loss", "random", f"{link.loss_pct}%"]
    ns("snd", "tc", "qdisc", "add", "dev", "s-r", "root", *data_path)
    ns("rcv", "tc", "qdisc", "add", "dev", "d-r", "root", "netem", "delay", half, "limit", netem_limit)

    # Bottleneck. burst = 1 ms of tokens (at least 2 packets): large enough for tbf to
    # reach its configured rate, small enough not to let line-rate bursts through.
    burst = max(2 * MTU, int(link.rate_mbit * 1e6 / 8 / 1000))
    ns("rtr", "tc", "qdisc", "add", "dev", "r-d", "root", "tbf",
       "rate", f"{link.rate_mbit}mbit", "burst", str(burst), "limit", str(link.buffer_bytes))


def qdisc_stats() -> str:
    out = subprocess.run(["ip", "netns", "exec", "rtr", "tc", "-s", "qdisc", "show", "dev", "r-d"],
                         capture_output=True, text=True, check=True)
    return out.stdout
