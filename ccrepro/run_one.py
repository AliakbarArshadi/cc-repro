"""Run a single flow over a freshly built dumbbell and write one result directory.

    python3 -m ccrepro.run_one --cc cubic --rate 100 --rtt 100 --buffer 1 --loss 0.1 \
        --duration 30 --out results/loss/cubic_loss0.1_run0

Each invocation lives in its own namespaces, so several can run in parallel.
"""

import argparse
import json
import os
import subprocess
import sys
import time

from . import netns


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cc", required=True)
    p.add_argument("--rate", type=float, default=100)
    p.add_argument("--rtt", type=float, default=100)
    p.add_argument("--buffer", type=float, default=1.0, help="bottleneck buffer in BDPs")
    p.add_argument("--loss", type=float, default=0.0, help="random loss, percent")
    p.add_argument("--duration", type=float, default=30)
    p.add_argument("--out", required=True)
    a = p.parse_args()

    netns.enter()   # re-execs into private namespaces on first call
    link = netns.Link(a.rate, a.rtt, a.buffer, a.loss)
    netns.build(link)
    os.makedirs(a.out, exist_ok=True)
    rx, tx, ready = (os.path.join(a.out, f) for f in ("rx.json", "tx.json", ".ready"))

    py = [sys.executable, "-m", "ccrepro.flow"]
    recv = subprocess.Popen(["ip", "netns", "exec", "rcv", *py, "recv",
                             "--duration", str(a.duration), "--out", rx, "--ready", ready])
    while not os.path.exists(ready):
        time.sleep(0.01)
    os.remove(ready)
    subprocess.run(["ip", "netns", "exec", "snd", *py, "send", "--dst", netns.RCV_IP,
                    "--cc", a.cc, "--duration", str(a.duration), "--out", tx], check=True)
    recv.wait(timeout=30)

    with open(os.path.join(a.out, "meta.json"), "w") as f:
        json.dump({"cc": a.cc, "duration": a.duration, "link": link.as_dict(),
                   "bottleneck_qdisc": netns.qdisc_stats()}, f, indent=2)


if __name__ == "__main__":
    main()
