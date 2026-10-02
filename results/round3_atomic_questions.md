# Jev vs LLM structured outputs — Round 3 – Jev answers 7 yes/no questions, code applies the rules

| Metric | Jev (jev-latest) | LLM (gpt-oss-120b) |
|---|---|---|
| Cases | 30 | 30 |
| Accuracy | 90% | 97% |
| Median latency | 136 ms | 3647 ms |
| p95 latency | 172 ms | 6175 ms |
| Cost / 1,000 decisions | $0.0263 | $0.2011 |
| Avg confidence when right | 0.686 | 0.979 |
| Avg confidence when wrong | 0.387 | 0.900 |
| Distinct confidence values | 21 | 6 |

## Auto-decide above a confidence threshold, send the rest to a human

**Jev (jev-latest)**

| Threshold | Auto-decided | Accuracy on auto | Sent to human |
|---|---|---|---|
| ≥ 0.6 | 67% | 95% | 33% |
| ≥ 0.7 | 53% | 94% | 47% |
| ≥ 0.8 | 43% | 92% | 57% |
| ≥ 0.9 | 30% | 100% | 70% |
| ≥ 0.95 | 20% | 100% | 80% |

**LLM (gpt-oss-120b)**

| Threshold | Auto-decided | Accuracy on auto | Sent to human |
|---|---|---|---|
| ≥ 0.6 | 100% | 97% | 0% |
| ≥ 0.7 | 100% | 97% | 0% |
| ≥ 0.8 | 100% | 97% | 0% |
| ≥ 0.9 | 100% | 97% | 0% |
| ≥ 0.95 | 93% | 100% | 7% |

_Bigger gap between 'confidence when right' and 'when wrong' = more useful confidence. A model whose accuracy climbs as you raise the threshold can safely automate the confident cases._