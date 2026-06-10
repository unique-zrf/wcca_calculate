# Resistor Divider Worst Case Model

Model ID: `resistor_divider`

The model calculates output voltage for a two-resistor divider:

```text
Vout = Vin * Rbottom / (Rtop + Rbottom)
```

Worst minimum output uses `Vin_min`, `Rtop_max`, and `Rbottom_min`.
Worst maximum output uses `Vin_max`, `Rtop_min`, and `Rbottom_max`.

Limitations:

- Does not include ADC input leakage.
- Does not include sampling capacitor loading.
- Does not include PCB leakage or contamination paths.
- Not intended for high-frequency divider networks.

