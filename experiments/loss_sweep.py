"""Goodput vs. random loss rate -- reproduces the loss figure of Cardwell et al.,
"BBR: Congestion-Based Congestion Control", ACM Queue 14(5), 2016.

Paper setup: one 60 s flow on a 100 Mbit/s, 100 ms RTT link, random loss from
0.001% to 50%. We use 30 s flows (the long-run average settles well before that;
see the per-second goodput in each rx.json) and repeat every point because
netem's loss is not seedable on this iproute2.

    python3 experiments/loss_sweep.py --cc cubic bbr --runs 3 --jobs 4
Finished points are skipped, so an interrupted sweep can simply be restarted.
"""

import argparse
import itertools
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOSS_PCT = [0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1, 2, 5, 10, 15, 20, 30, 50]


def run(cc: str, loss: float, run_id: int, args) -> str:
    out = os.path.join(args.results, f"{cc}_loss{loss}_run{run_id}")
    if os.path.exists(os.path.join(out, "meta.json")):
        return f"skip {out}"
    cmd = [sys.executable, "-m", "ccrepro.run_one", "--cc", cc, "--loss", str(loss),
           "--rate", str(args.rate), "--rtt", str(args.rtt), "--buffer", str(args.buffer),
           "--duration", str(args.duration), "--out", out]
    try:
        # Handshakes at 50% loss can take a while (SYN backoff), but never minutes.
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=args.duration * 3 + 120)
    except subprocess.TimeoutExpired:
        return f"FAIL {out} (timeout)"
    return f"{'ok  ' if r.returncode == 0 else 'FAIL'} {out}" + ("" if r.returncode == 0 else "\n" + r.stderr[-800:])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cc", nargs="+", default=["cubic", "bbr"])
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--rate", type=float, default=100)
    p.add_argument("--rtt", type=float, default=100)
    p.add_argument("--buffer", type=float, default=1.0)
    p.add_argument("--duration", type=float, default=30)
    p.add_argument("--results", default=os.path.join(ROOT, "results", "loss_sweep"))
    args = p.parse_args()

    jobs = list(itertools.product(args.cc, LOSS_PCT, range(args.runs)))
    with ThreadPoolExecutor(args.jobs) as pool:
        futures = [pool.submit(run, *j, args) for j in jobs]
        for i, f in enumerate(as_completed(futures), 1):
            print(f"[{i}/{len(jobs)}] {f.result()}", flush=True)


if __name__ == "__main__":
    main()
