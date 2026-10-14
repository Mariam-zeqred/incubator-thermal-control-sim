"""Interactive page: pick a plant, a scenario and controller settings, see the run.

make app        (python -m streamlit run app/streamlit_app.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from thermosim import metrics, scenarios, simulate  # noqa: E402
from thermosim.controllers import (  # noqa: E402
    FirmwareHysteresis,
    MPCSketch,
    PIDRelay,
    PlainHysteresis,
    tune_pid_simc,
)
from thermosim.plant import PLANTS, load_params, make_plant  # noqa: E402

PLANT_LABEL = {
    "heater_lag": "heater-lag (fitted, best)",
    "first_order": "first-order + dead time (fitted)",
    "chamber_wall": "chamber + wall (illustrative)",
}
SCENARIOS = {
    "cold start": scenarios.cold_start,
    "setpoint step": scenarios.setpoint_step,
    "door opening": scenarios.door_opening,
    "ambient drift": scenarios.ambient_drift,
}


def sidebar(params: dict) -> tuple[str, str, list]:
    st.sidebar.header("Plant")
    plant_name = st.sidebar.selectbox(
        "model", list(PLANTS), format_func=lambda k: PLANT_LABEL[k], key="plant"
    )
    st.sidebar.header("Scenario")
    sc_name = st.sidebar.selectbox("event", list(SCENARIOS), key="scenario")

    fo = params["first_order"]
    kp0, ti0, _ = tune_pid_simc(fo["a_c_per_min"], fo["b_per_min"], fo["dead_time_s"])
    ctls: list = []

    st.sidebar.header("Controllers")
    with st.sidebar.expander("on/off firmware", expanded=True):
        use_fw = st.checkbox("include", True, key="fw")
        band = st.slider("band (°C)", 0.1, 1.0, 0.4, 0.05, key="fw_band")
        antic = st.slider("OFF anticipation (°C)", 0.0, 0.4, 0.1, 0.05, key="fw_antic")
        coast = st.slider("coast lead (s)", 0, 600, 200, 20, key="fw_coast")
        duty_on = st.slider("max ON before rest (s)", 0, 1800, 600, 60, key="fw_duty")
        rest = st.slider("rest (s)", 0, 300, 60, 10, key="fw_rest")
        if use_fw:
            ctls.append(
                FirmwareHysteresis(
                    band=band,
                    anticipation=antic,
                    coast_lead_s=coast,
                    duty_on_s=duty_on,
                    duty_rest_s=rest,
                )
            )
    with st.sidebar.expander("on/off plain"):
        if st.checkbox("include", True, key="plain"):
            ctls.append(PlainHysteresis(band=band))
    with st.sidebar.expander("PID relay"):
        use_pid = st.checkbox("include", True, key="pid")
        kp = st.slider("kp (duty/°C)", 0.05, 2.0, float(round(kp0, 2)), 0.01, key="pid_kp")
        ti = st.slider("Ti (min)", 1.0, 120.0, float(round(ti0, 1)), 1.0, key="pid_ti")
        window = st.slider("window (s)", 30, 600, 120, 30, key="pid_win")
        if use_pid:
            ctls.append(PIDRelay(kp=kp, ti_min=ti, window_s=window))
    with st.sidebar.expander("MPC sketch"):
        use_mpc = st.checkbox("include", True, key="mpc")
        lam_u = st.slider("λ energy", 0.0, 0.5, 0.02, 0.01, key="mpc_lu")
        lam_sw = st.slider("λ switching", 0.0, 0.5, 0.05, 0.01, key="mpc_lsw")
        if use_mpc:
            so = params["second_order"]
            ctls.append(
                MPCSketch(
                    a=so["a_c_per_min"],
                    b=so["b_per_min"],
                    tau_h_min=so["tau_h_min"],
                    lambda_u=lam_u,
                    lambda_sw=lam_sw,
                    window_s=window,
                )
            )
    return plant_name, sc_name, ctls


def main() -> None:
    st.set_page_config(page_title="Incubator thermal control sim", layout="wide")
    st.title("Incubator heater control: on/off vs PID vs MPC")
    params = load_params()
    plant_name, sc_name, ctls = sidebar(params)
    sc = SCENARIOS[sc_name]()
    st.caption(sc.description)
    if not ctls:
        st.info("Tick at least one controller in the sidebar.")
        return

    fig, (ax, axh) = plt.subplots(
        2, 1, figsize=(11, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    rows = []
    t_from = 3600.0 if sc_name in ("setpoint step", "door opening") else 0.0
    for i, ctl in enumerate(ctls):
        plant = make_plant(plant_name, params)
        df = simulate.run(plant, ctl, sc)
        t_h = df["t_s"] / 3600
        if i == 0:
            ax.plot(t_h, df["target"], "k--", lw=1, label="target")
            if df["door"].any():
                ax.fill_between(
                    t_h,
                    0,
                    1,
                    where=df["door"] > 0,
                    color="orange",
                    alpha=0.15,
                    transform=ax.get_xaxis_transform(),
                    label="door open",
                )
        ax.plot(t_h, df["temp"], lw=1.1, label=ctl.name)
        axh.fill_between(t_h, i, i + 0.8, where=df["heater"] > 0, step="post")
        m = metrics.compute(df, plant.a, t_from_s=t_from).as_dict()
        m["controller"] = ctl.name
        rows.append(m)
    ax.set_ylabel("chamber °C")
    ax.legend(fontsize=8)
    axh.set_yticks([i + 0.4 for i in range(len(ctls))])
    axh.set_yticklabels([c.name for c in ctls], fontsize=8)
    axh.set_xlabel("time (h)")
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    table = pd.DataFrame(rows).set_index("controller")
    st.dataframe(table, use_container_width=True)
    st.markdown(
        "Metrics from the event onwards. `heating_c` = a × heater-on minutes (proportional to "
        "energy; the heater's wattage is not known). `switches` counts relay switch-ons; each "
        "one is wear on a mechanical relay and a current surge on a solid-state one."
    )


if __name__ == "__main__" or st.runtime.exists():
    main()
