# cc-repro — reproducing congestion-control results on a laptop

A rootless network-emulation testbed (Linux namespaces + `tc`) that reproduces
published results on TCP congestion control, starting with the loss-resilience
and bufferbloat results of BBR (Cardwell et al., ACM Queue 2016). The goal after
that is to check from-scratch user-space implementations against the Linux kernel
on the same experiments.

Status and phases: [docs/PLAN.md](docs/PLAN.md).

## Testbed

```
snd ──(netem: RTT/2 + random loss)──> rtr ──(tbf: rate + buffer)──> rcv
snd <───────────────────────────────── rtr <──(netem: RTT/2)──────── rcv
```

- **No root needed.** Each run re-executes itself inside a private
  user + network + mount namespace (`unshare -rnm`), so it never touches the
  host network and always starts with clean kernel TCP state.
- **Delay and the bottleneck sit on different links**, so netem's own queue
  never acts as a hidden extra buffer.
- **Offloads (TSO/GSO/GRO) are off**, so the shaper sees real packets instead
  of 64 KB super-packets.
- The sender samples the kernel's `struct tcp_info` every 10 ms (cwnd, RTT,
  pacing and delivery rate, retransmissions). Goodput is measured at the receiver.

## Running

Requirements: Linux with unprivileged user namespaces, `iproute2`, `ethtool`,
Python 3.10+ with matplotlib. For BBR, load the module once: `sudo modprobe tcp_bbr`.

```bash
python3 -m ccrepro.run_one --cc cubic --rate 100 --rtt 100 --buffer 1 --loss 0.1 \
    --duration 30 --out results/demo          # one flow
python3 experiments/loss_sweep.py --cc cubic bbr --runs 3 --jobs 6
python3 analysis/plot_loss.py                 # -> figures/loss_sweep.png
```

## Layout

```
ccrepro/      netns.py (topology), flow.py (sender/receiver), tcpinfo.py, run_one.py
experiments/  one script per figure
analysis/     plotting and summary tables
docs/         plan, findings
```
