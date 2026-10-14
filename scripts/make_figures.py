"""Run every controller on every scenario and write figures/*.png + figures/results.json.

The README quotes only numbers from results.json, so re-running this script reproduces
every figure and every number in it. Runtime: about half a minute.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from thermosim import __version__, metrics, scenarios, simulate  # noqa: E402
from thermosim.controllers import FirmwareHysteresis  # noqa: E402
from thermosim.disturbances import load_trace  # noqa: E402
from thermosim.plant import PLANTS, load_params, make_plant  # noqa: E402

FIG_DIR = ROOT / "figures"
PLANT_LABEL = {
    "first_order": "first-order + dead time (fitted)",
    "heater_lag": "heater-lag (fitted)",
    "chamber_wall": "chamber + wall (illustrative)",
}
COLOURS = {
    "on/off firmware": "#1f77b4",
    "on/off plain": "#7f7f7f",
    "PID relay": "#d62728",
    "MPC sketch": "#2ca02c",
}
plt.rcParams.update({"figure.dpi": 110, "savefig.dpi": 110, "font.size": 9})


def eval_from(sc_name: str) -> float:
    return 3600.0 if sc_name in ("setpoint step", "door opening") else 0.0


def run_matrix(params: dict) -> tuple[dict, dict]:
    runs: dict = {}
    results: dict = {}
    for plant_name in PLANTS:
        runs[plant_name] = {}
        results[plant_name] = {}
        for sc in scenarios.all_scenarios():
            runs[plant_name][sc.name] = {}
            results[plant_name][sc.name] = {}
            for ctl in scenarios.default_controllers(params):
                plant = make_plant(plant_name, params)
                df = simulate.run(plant, ctl, sc)
                m = metrics.compute(df, plant.a, t_from_s=eval_from(sc.name))
                runs[plant_name][sc.name][ctl.name] = df
                results[plant_name][sc.name][ctl.name] = m.as_dict()
    return runs, results


def plot_scenario(runs: dict, sc_name: str, plant_name: str, fname: str, title: str) -> None:
    sub = runs[plant_name][sc_name]
    n = len(sub)
    fig, axes = plt.subplots(
        2, 1, figsize=(11, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    ax, axh = axes
    first = next(iter(sub.values()))
    t_h = first["t_s"] / 3600.0
    ax.plot(t_h, first["target"], "k--", lw=1, label="target")
    ax.fill_between(
        t_h,
        first["target"] - 0.2,
        first["target"] + 0.2,
        color="k",
        alpha=0.07,
        label="±0.2 °C band",
    )
    if first["door"].any():
        ax.fill_between(
            t_h,
            0,
            1,
            where=first["door"] > 0,
            transform=ax.get_xaxis_transform(),
            color="orange",
            alpha=0.15,
            label="door open",
        )
    if (first["t_out"].max() - first["t_out"].min()) > 0.05:
        ax2 = ax.twinx()
        ax2.plot(t_h, first["t_out"], color="tab:orange", lw=0.8, alpha=0.7)
        ax2.set_ylabel("ambient °C", color="tab:orange")
    for i, (name, df) in enumerate(sub.items()):
        ax.plot(t_h, df["temp"], color=COLOURS[name], lw=1.1, label=name)
        on = df["heater"].to_numpy().astype(bool)
        axh.fill_between(t_h, i, i + 0.8, where=on, color=COLOURS[name], step="post")
    lo = min(df["temp"].min() for df in sub.values())
    ax.set_ylim(max(lo - 0.5, 26.0), max(df["temp"].max() for df in sub.values()) + 0.5)
    ax.set_ylabel("chamber °C")
    ax.set_title(f"{title} — plant: {PLANT_LABEL[plant_name]}")
    ax.legend(loc="lower right", ncol=3, fontsize=8)
    axh.set_yticks([i + 0.4 for i in range(n)])
    axh.set_yticklabels(list(sub.keys()), fontsize=8)
    axh.set_ylim(0, n)
    axh.set_xlabel("time (h)")
    axh.set_ylabel("heater on")
    fig.tight_layout()
    fig.savefig(FIG_DIR / fname)
    plt.close(fig)


def plot_metric_bars(results: dict, plant_name: str, fname: str) -> None:
    keys = [
        ("overshoot_c", "overshoot (°C)"),
        ("heater_on_min", "heater on (min)"),
        ("switches", "relay switch-ons"),
        ("rms_error_c", "RMS error (°C)"),
    ]
    scs = list(results[plant_name].keys())
    ctls = list(COLOURS.keys())
    fig, axes = plt.subplots(1, len(keys), figsize=(13, 3.4))
    width = 0.2
    x = np.arange(len(scs))
    for ax, (key, label) in zip(axes, keys, strict=True):
        for j, ctl in enumerate(ctls):
            vals = [results[plant_name][s][ctl][key] for s in scs]
            ax.bar(x + (j - 1.5) * width, vals, width, color=COLOURS[ctl], label=ctl)
        ax.set_xticks(x)
        ax.set_xticklabels(scs, fontsize=8, rotation=15)
        ax.set_title(label, fontsize=9)
    axes[0].legend(fontsize=7)
    fig.suptitle(f"Metrics per scenario — plant: {PLANT_LABEL[plant_name]}", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIG_DIR / fname)
    plt.close(fig)


def plot_robustness(runs: dict, fname: str) -> None:
    fig, ax = plt.subplots(figsize=(11, 4))
    for plant_name, style in zip(PLANTS, ["-", "--", ":"], strict=True):
        df = runs[plant_name]["cold start"]["on/off firmware"]
        ax.plot(
            df["t_s"] / 3600,
            df["temp"],
            style,
            color=COLOURS["on/off firmware"],
            label=f"firmware on/off — {PLANT_LABEL[plant_name]}",
        )
        df = runs[plant_name]["cold start"]["MPC sketch"]
        ax.plot(
            df["t_s"] / 3600,
            df["temp"],
            style,
            color=COLOURS["MPC sketch"],
            label=f"MPC sketch — {PLANT_LABEL[plant_name]}",
        )
    ax.axhline(34.5, color="k", lw=0.8, ls="--")
    ax.set_ylim(33, 38)
    ax.set_xlim(0, 2)
    ax.set_xlabel("time (h)")
    ax.set_ylabel("chamber °C")
    ax.set_title("Same controllers, three plants: cold start to 34.5 °C")
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(FIG_DIR / fname)
    plt.close(fig)


def replay(params: dict) -> dict:
    """Firmware logic on the fitted plant, driven by the real day's targets and ambient."""
    rows = load_trace()
    sc = scenarios.replay()
    out: dict = {}
    fig, axes = plt.subplots(
        2, 1, figsize=(11, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    t_real = np.array([r["t_s"] for r in rows]) / 3600
    real_temp = np.array([r["temp"] for r in rows])
    real_on = np.array([r["heater"] for r in rows])
    axes[0].plot(t_real, [r["target"] for r in rows], "k--", lw=1, label="target (real)")
    axes[0].plot(t_real, real_temp, color="k", lw=1.2, label="measured chamber")
    axes[1].fill_between(
        t_real, 0, 0.8, where=real_on > 0, color="k", step="post", label="real heater"
    )
    for i, plant_name in enumerate(["first_order", "heater_lag"]):
        plant = make_plant(plant_name, params)
        df = simulate.run(plant, FirmwareHysteresis(), sc)
        sim = df.set_index("t_s")["temp"].reindex([r["t_s"] for r in rows]).to_numpy()
        colour = ["tab:blue", "tab:green"][i]
        axes[0].plot(
            t_real, sim, color=colour, lw=1, label=f"simulated — {PLANT_LABEL[plant_name]}"
        )
        idx = np.array([int(r["t_s"]) for r in rows])
        sim_on = df["heater"].to_numpy()[idx] > 0
        axes[1].fill_between(t_real, 1 + i, 1.8 + i, where=sim_on, color=colour, step="post")
        out[plant_name] = {
            "rmse_c": round(float(np.sqrt(np.nanmean((sim - real_temp) ** 2))), 3),
            "max_abs_error_c": round(float(np.nanmax(np.abs(sim - real_temp))), 3),
            "sim_heater_on_fraction": round(float(df["heater"].mean()), 3),
            "sim_switch_ons": int(metrics.switch_count(df["heater"])),
        }
    out["real"] = {
        "heater_on_fraction": round(float(real_on.mean()), 3),
        "switch_ons": int(metrics.switch_count(__import__("pandas").Series(real_on))),
        "readings": len(rows),
        "span_h": round(float(t_real[-1]), 2),
    }
    axes[0].set_ylabel("°C")
    axes[0].set_title("Replay of 2026-10-03: real device vs firmware logic on the fitted plants")
    axes[0].legend(fontsize=8, loc="lower right")
    axes[1].set_yticks([0.4, 1.4, 2.4])
    axes[1].set_yticklabels(["real", "sim first-order", "sim heater-lag"], fontsize=8)
    axes[1].set_xlabel("time (h)")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "06_replay_real_day.png")
    plt.close(fig)
    return out


def main() -> None:
    FIG_DIR.mkdir(exist_ok=True)
    params = load_params()
    runs, results = run_matrix(params)
    plot_scenario(runs, "cold start", "heater_lag", "01_cold_start.png", "Cold start")
    plot_scenario(runs, "setpoint step", "heater_lag", "02_setpoint_step.png", "Setpoint step")
    plot_scenario(runs, "door opening", "heater_lag", "03_door_opening.png", "Door opening")
    plot_scenario(runs, "ambient drift", "heater_lag", "04_ambient_drift.png", "Ambient drift")
    plot_metric_bars(results, "heater_lag", "05_metrics.png")
    plot_robustness(runs, "07_plant_robustness.png")
    rep = replay(params)
    fo = params["first_order"]
    kp, ti, _ = scenarios._simc(fo)
    out = {
        "version": __version__,
        "source": "scripts/make_figures.py; plants from data/model_params.json "
        "(incubator-telemetry-analysis, one device, one day); ambient trace from "
        "data/incubator_2026-10-03.csv",
        "controllers": {
            "on/off firmware": "Config.h defaults: band 0.4, anticipation 0.1, coast 200 s, "
            "min off 30 s, duty 600 s on / 60 s rest",
            "on/off plain": "band 0.4, nothing else",
            "PID relay": f"SIMC PI on the first-order fit: kp={kp:.3f} /°C, Ti={ti:.1f} min, "
            "120 s time-proportioning window, 10 s minimum pulse",
            "MPC sketch": "heater-lag internal model, horizon 4 × 120 s, 5 duty levels, "
            "λ_u 0.02, λ_sw 0.05, bias correction",
        },
        "scenarios": {sc.name: sc.description for sc in scenarios.all_scenarios()},
        "metrics_note": "evaluated from t=0 (cold start, ambient drift) or from the event at "
        "1 h (setpoint step, door opening); heating_c = a × heater-on minutes, proportional to "
        "energy (heater power unknown)",
        "matrix": results,
        "replay_2026_10_03": rep,
    }
    (FIG_DIR / "results.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(rep, indent=1))
    for plant_name in PLANTS:
        print(f"\n[{plant_name}]")
        for sc_name, by_ctl in results[plant_name].items():
            for ctl, m in by_ctl.items():
                print(
                    f"  {sc_name:14s} {ctl:16s} ttt={m['time_to_target_min']!s:>6} "
                    f"over={m['overshoot_c']:5.2f} on={m['heater_on_min']:5.1f}min "
                    f"sw={m['switches']:3d} rms={m['rms_error_c']:.3f} "
                    f"band={m['in_band_fraction']:.2f} final={m['final_error_c']:+.3f}"
                )


if __name__ == "__main__":
    main()
