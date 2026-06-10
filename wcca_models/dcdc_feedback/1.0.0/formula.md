# DC/DC Feedback Network Worst Case Model

Model ID: `dcdc_feedback`

The model calculates a regulator feedback-set output voltage from reference voltage and feedback-divider limits:

```text
Vout = Vref * (1 + Rtop / Rbottom)
Vout_worst_min = Vref_min * (1 + Rtop_min / Rbottom_max)
Vout_worst_max = Vref_max * (1 + Rtop_max / Rbottom_min)
```

Resistor bounds include tolerance, optional aging, and optional tempco over the declared project temperature range.

Limitations:

- Does not model line/load regulation, output ripple, or transient response.
- Does not model compensation, loop stability, or feed-forward capacitors.
- Assumes the converter controller follows the ideal feedback equation.
- Does not include reference drift beyond the supplied `vref_min` and `vref_max`.
