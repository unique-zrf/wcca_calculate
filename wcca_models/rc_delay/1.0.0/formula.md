# RC Delay Worst Case Model

Model ID: `rc_delay`

The model calculates rising RC delay to a voltage threshold:

```text
t = -R * C * ln(1 - Vthreshold / Vinitial)
```

Worst minimum delay uses `R_min`, `C_min`, `threshold_min`, and `v_initial_max`.
Worst maximum delay uses `R_max`, `C_max`, `threshold_max`, and `v_initial_min`.

Limitations:

- Only supports first-order rising RC charge behavior.
- Does not model comparator propagation delay.
- Does not model capacitor leakage, dielectric absorption, or nonlinear capacitance.

