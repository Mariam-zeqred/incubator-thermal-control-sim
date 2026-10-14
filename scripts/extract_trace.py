"""Extract the simulation inputs from the real incubator history exported in
incubator-telemetry-analysis (data/hive-1C5A00_history_2026-10-03.json).

Usage:  python scripts/extract_trace.py <path-to-history.json> [out.csv]

Writes data/incubator_2026-10-03.csv with the columns the simulator needs:
t_s (seconds since the first reading), temp (chamber °C), temp_out (ambient °C),
target (°C), heater (0/1), door (0/1). Nothing is modified or smoothed.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

OUT_DEFAULT = Path(__file__).resolve().parents[1] / "data" / "incubator_2026-10-03.csv"


def main() -> None:
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else OUT_DEFAULT
    rows = json.loads(src.read_text())
    rows.sort(key=lambda r: r["ts"])
    t0 = rows[0]["ts"]
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["t_s", "temp", "temp_out", "target", "heater", "door"])
        for r in rows:
            w.writerow(
                [
                    r["ts"] - t0,
                    r["temp"],
                    r["tempOut"],
                    r["targetTemp"],
                    int(bool(r["heater"])),
                    int(r["door"] != "shut"),
                ]
            )
    print(f"{len(rows)} rows -> {out}")


if __name__ == "__main__":
    main()
