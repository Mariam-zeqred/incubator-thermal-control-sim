"""thermosim: thermal model of a queen-bee incubator and heater controllers to compare.

plant        -- first-order, heater-lag and chamber+wall models (parameters from repo #1)
controllers  -- firmware on/off, plain on/off, PID with relay quantisation, MPC sketch
disturbances -- constant / real-trace ambient, door openings
simulate     -- the loop with the firmware's interlock
metrics      -- time to target, overshoot, heater-on time, switching count, ...
scenarios    -- cold start, setpoint step, door opening, ambient drift, real-day replay
"""

__version__ = "0.1.0"
