# Jev vs LLM structured outputs — Round 1 – original policy (one big question)

| Metric | Jev (jev-latest) | LLM (gpt-oss-120b) |
|---|---|---|
| Cases | 30 | 30 |
| Accuracy | 80% | 83% |
| Median latency | 147 ms | 639 ms |
| p95 latency | 221 ms | 4349 ms |
| Cost / 1,000 decisions | $0.0200 | $0.3916 |
| Avg confidence when right | 0.819 | 0.967 |
| Avg confidence when wrong | 0.523 | 0.956 |
| Distinct confidence values | 19 | 6 |

## Auto-decide above a confidence threshold, send the rest to a human

**Jev (jev-latest)**

| Threshold | Auto-decided | Accuracy on auto | Sent to human |
|---|---|---|---|
| ≥ 0.6 | 77% | 87% | 23% |
| ≥ 0.7 | 67% | 90% | 33% |
| ≥ 0.8 | 63% | 89% | 37% |
| ≥ 0.9 | 37% | 100% | 63% |
| ≥ 0.95 | 23% | 100% | 77% |

**LLM (gpt-oss-120b)**

| Threshold | Auto-decided | Accuracy on auto | Sent to human |
|---|---|---|---|
| ≥ 0.6 | 100% | 83% | 0% |
| ≥ 0.7 | 100% | 83% | 0% |
| ≥ 0.8 | 100% | 83% | 0% |
| ≥ 0.9 | 100% | 83% | 0% |
| ≥ 0.95 | 87% | 85% | 13% |

_Bigger gap between 'confidence when right' and 'when wrong' = more useful confidence. A model whose accuracy climbs as you raise the threshold can safely automate the confident cases._