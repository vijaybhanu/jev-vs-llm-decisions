# Jev vs LLM structured outputs — Round 2 – clarified policy (one big question)

| Metric | Jev (jev-latest) | LLM (gpt-oss-120b) |
|---|---|---|
| Cases | 30 | 30 |
| Accuracy | 80% | 93% |
| Median latency | 138 ms | 2827 ms |
| p95 latency | 212 ms | 5855 ms |
| Cost / 1,000 decisions | $0.0265 | $0.2077 |
| Avg confidence when right | 0.805 | 0.980 |
| Avg confidence when wrong | 0.497 | 0.900 |
| Distinct confidence values | 20 | 6 |

## Auto-decide above a confidence threshold, send the rest to a human

**Jev (jev-latest)**

| Threshold | Auto-decided | Accuracy on auto | Sent to human |
|---|---|---|---|
| ≥ 0.6 | 67% | 90% | 33% |
| ≥ 0.7 | 57% | 94% | 43% |
| ≥ 0.8 | 50% | 100% | 50% |
| ≥ 0.9 | 47% | 100% | 53% |
| ≥ 0.95 | 43% | 100% | 57% |

**LLM (gpt-oss-120b)**

| Threshold | Auto-decided | Accuracy on auto | Sent to human |
|---|---|---|---|
| ≥ 0.6 | 100% | 93% | 0% |
| ≥ 0.7 | 100% | 93% | 0% |
| ≥ 0.8 | 100% | 93% | 0% |
| ≥ 0.9 | 100% | 93% | 0% |
| ≥ 0.95 | 87% | 100% | 13% |

_Bigger gap between 'confidence when right' and 'when wrong' = more useful confidence. A model whose accuracy climbs as you raise the threshold can safely automate the confident cases._