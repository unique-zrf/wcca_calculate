# LDO Power Rail Worst Case Model

Model ID: `ldo_power_rail`

The model applies output accuracy and optional line/load regulation as an additive percent error:

```text
total_error = output_accuracy + load_regulation + line_regulation
Vout_worst_min = Vout_nominal * (1 - total_error)
Vout_worst_max = Vout_nominal * (1 + total_error)
```

Limitations:

- Does not model dropout failure.
- Does not model transient response.
- Does not include thermal shutdown or current limiting.

