# Walkthrough (for Mariam)

## Why it is built this way

Repo #1 fitted *how the chamber behaves*; here that model is driven by *controllers*,
including a step-by-step re-implementation of your own firmware's heater decision. The aim
is not a "better" controller than the one you shipped but numbers for what the on/off logic
costs and buys against PID and MPC on the same relay. The result: your firmware is the only
one with no overshoot on the fitted plant, at the price of a small low bias, and heater
energy is the same for all four, which is physics, not the controller.

Three choices matter. The **interlock lives in the simulator**, so the door and the 40 °C
cut-off apply equally to every controller, as `Interlock.*` does in the firmware. **Every
README number comes from `figures/results.json`**, written by `scripts/make_figures.py`, so
`make check` reproduces the README. And the **replay of the real day** (figure 06) is in the
repo precisely because it does not match everywhere.

## File map

- `src/thermosim/plant.py` – three plants; only `heater_lag` and `first_order` are fitted.
- `controllers/onoff.py` – `FirmwareHysteresis` follows `Control.cpp` (thresholds, 60-sample
  rise rate, projection, min OFF, duty rest), each rule a small method; `PlainHysteresis`.
- `controllers/pid.py` – PI with conditional-integration anti-windup, SIMC tuning, pulses.
- `controllers/mpc.py` – enumerates duty sequences on the heater-lag model, bias-corrected.
- `simulate.py` – the 1 s loop with interlock; `scenarios.py`, `disturbances.py`,
  `metrics.py` – events, real `tempOut` trace and door, scores.
- `scripts/make_figures.py` – the matrix (3 plants × 4 scenarios × 4 controllers).
- `app/streamlit_app.py` – sliders for the firmware constants, PID gains and MPC weights.
- `tests/` – 36 tests: plant physics, each firmware rule alone, interlock, replay RMSE.

## Three questions a professor may ask

**"Your firmware is on/off; why not PID?"** Because the actuator is a relay. A PID's output
on a relay is pulse width, which the firmware's 600 s / 60 s duty limit already is. On the
fitted plant the simulated PID has no bias but needs six times the relay switch-ons for the
same band, and the firmware's coast-lead projection already removes the overshoot a
thermostat has (figure 01). On/off with anticipation is the right complexity for a 99-minute
time constant, a 5-minute heater lag and a 0.4 °C band; PID would pay off only if the band
had to shrink below the sensor's noise.

**"How do you know the simulation is right?"** Partly. The replay (figure 06) shows the
firmware logic on the fitted plant reproducing the real duty (19.6 % vs 19.2 %) and the pulse
pattern at 34.5 and 38.8 °C with 0.21 °C RMSE after the first step. It does *not* reproduce the
1.4 °C overshoot of the first approach from cold (the dead-time plant does, but then
saw-tooths), and it is in-sample. So: good near the setpoint, wrong on the first heat-up;
TODO.md item 2 is about finding out why.

**"What does the chamber+wall plant show?"** That the ranking depends on the plant. With fast
air and a slow wall, the firmware chatters and the MPC overshoots 2.7 °C because its model is
wrong, while the dumb thermostat wins. That plant is illustrative (the data cannot identify a
wall), but it is the argument for fitting a model before choosing a controller.

## One thing you could extend

Give `MPCSketch` the ambient forecast instead of a constant: the device measures `tempOut`,
so the controller could predict the loss term for the next 8 minutes. Compare it with the
firmware logic on a hotter-day trace (`ambient_drift(offset=+5)`), where the loss changes
most.
