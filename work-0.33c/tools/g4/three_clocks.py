"""G4: compare three clocks in a diag-tsc probe run (read-only).

  python -I tools/g4/three_clocks.py evidence/g4/<run-id>

host     = host monotonic time when each heartbeat line arrived (timing_probe.py)
irq      = guest timer-interrupt count / 100 Hz        (what the accepted kernel calls uptime)
tsc      = guest TSC delta / (TSC counts per 10 ms * 100), calibrated in the same PIT window
Expected interrupts over the window = tsc seconds * 100; lost = expected - delivered.
"""
import json
import re
import sys
from pathlib import Path

run = Path(sys.argv[1])
lines = [json.loads(l) for l in (run / "serial-timed.jsonl").read_text().splitlines()]
diag = next(re.search(r"tsc_per_10ms=(\d+)", x["line"]) for x in lines if x["line"].startswith("ABR|DIAG"))
tsc_per_s = int(diag.group(1)) * 100
ticks = []
for x in lines:
    m = re.search(r"ABR\|TICK\|uptime_s=(\d+)\|spurious=\d+\|interrupts=(\d+)\|tsc=(\d+)", x["line"])
    if m:
        ticks.append((x["t_ns"] / 1e9, int(m.group(1)), int(m.group(2)), int(m.group(3))))
a, b = ticks[1], ticks[-1]
host = b[0] - a[0]
irq = (b[2] - a[2]) / 100
tsc = (b[3] - a[3]) / tsc_per_s
expected = tsc * 100
delivered = b[2] - a[2]
probe = json.loads((run / "probe.json").read_text())
out = {"run": run.name, "accel": probe["accelerator"], "cpu": probe["cpu_model"], "load": probe["load_burners"],
       "host_s": round(host, 3), "irq_s": round(irq, 3), "tsc_s": round(tsc, 3),
       "irq_per_host": round(irq / host, 4), "tsc_per_host": round(tsc / host, 4),
       "interrupts_expected": round(expected), "interrupts_delivered": delivered,
       "interrupts_lost": round(expected - delivered), "delivery_ratio": round(delivered / expected, 4),
       "tsc_hz_measured": tsc_per_s}
print(json.dumps(out))
(run / "three-clocks.json").write_text(json.dumps(out, indent=1) + "\n")
