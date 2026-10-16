# TODO

Everything the PLAN.md spec asks for is in the repo (two fitted plants plus an illustrative
chamber+wall one, firmware on/off with OFF-anticipation and duty limit, PID with anti-windup
and relay quantisation, MPC sketch, metrics, door and ambient disturbances, Streamlit page,
static figures, honest README). What is left needs Mariam, her device, or a browser.

## Needs the device or Mariam

1. **Heater power.** Measure the heater's wattage (or read it off the element) and put it in
   `data/model_params.json`; then `metrics.energy_kwh_at` can give kWh per scenario instead of
   heater-on minutes. Repo #1's TODO asks for the same measurement.
2. **The first-approach overshoot.** The real device overshot 32 °C by 1.42 °C on its first
   run from cold on 2026-10-03; the firmware logic on the heater-lag plant does not (0.15 °C),
   on the dead-time plant it does (1.54 °C) but that plant is wrong afterwards. Candidate
   explanations to check on the device: the firmware version that day (anticipation was 0.3 °C
   before FW 1.1.4 and the day may have run an older build), a rise-rate buffer that had not
   filled during the first minutes, or the element being hotter than the model's `E` state
   after a long ON stretch. Log one more cold start with `HEATER_COAST_LEAD_S` visible in the
   debug output and compare with `scenarios.replay()`.
3. **The 1.0–2.2 h gap.** On the real day the chamber fell to 30.2 °C with the heater off and
   the target at 32 °C. The export has no pause/alarm field; find out from the device's alarm
   log or SD CSV what blocked the heater, and if it was a pause add a `blocked` column to
   `data/incubator_2026-10-03.csv` so the replay can honour it.
4. **A real door opening.** The door loss ×10 and the 10-minute opening are guesses. Open the
   door for a timed 2 minutes on the real device, export the history, and fit `loss_gain` so
   the simulated dip matches; then the door scenario and its numbers are measured, not
   illustrative.
5. **Run the Streamlit page in a browser** (`make app`). It was only run headless by
   `tests/test_app.py` in the cloud sandbox.

## Could be done in the cloud (not required by the spec)

6. Add the 90-minute `HEATER_MAX_ON_MS` alarm to the simulator interlock (WALKTHROUGH extension).
7. Let `MPCSketch` use an ambient forecast and compare on `ambient_drift(offset=+5)`.
8. Replace the exhaustive search in `MPCSketch` with a small QP (cvxpy) so a longer horizon is
   affordable; keep the enumerating version as the reference in tests.

Closed on 2026-10-16: the anticipation × coast-lead sweep (`sweep.py`, figure 08, README
"Where the firmware's two constants sit"); the MPC is now built from the heater-lag fit
(`default_controllers`, pinned by a test); the `make_figures.py` runtime note.
