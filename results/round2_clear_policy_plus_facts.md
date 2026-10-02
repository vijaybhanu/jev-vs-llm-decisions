# Jev vs LLM structured outputs — Round 2 – clarified policy + code-computed facts

| Metric | Jev (jev-latest) | LLM (gpt-oss-120b) |
|---|---|---|
| Cases | 30 | 30 |
| Accuracy | 77% | 97% |
| Median latency | 129 ms | 3647 ms |
| p95 latency | 177 ms | 6175 ms |
| Cost / 1,000 decisions | $0.0287 | $0.2011 |
| Avg confidence when right | 0.870 | 0.979 |
| Avg confidence when wrong | 0.431 | 0.900 |
| Distinct confidence values | 16 | 6 |

## Auto-decide above a confidence threshold, send the rest to a human

**Jev (jev-latest)**

| Threshold | Auto-decided | Accuracy on auto | Sent to human |
|---|---|---|---|
| ≥ 0.6 | 67% | 95% | 33% |
| ≥ 0.7 | 63% | 100% | 37% |
| ≥ 0.8 | 57% | 100% | 43% |
| ≥ 0.9 | 57% | 100% | 43% |
| ≥ 0.95 | 53% | 100% | 47% |

**LLM (gpt-oss-120b)**

| Threshold | Auto-decided | Accuracy on auto | Sent to human |
|---|---|---|---|
| ≥ 0.6 | 100% | 97% | 0% |
| ≥ 0.7 | 100% | 97% | 0% |
| ≥ 0.8 | 100% | 97% | 0% |
| ≥ 0.9 | 100% | 97% | 0% |
| ≥ 0.95 | 93% | 100% | 7% |

_Bigger gap between 'confidence when right' and 'when wrong' = more useful confidence. A model whose accuracy climbs as you raise the threshold can safely automate the confident cases._