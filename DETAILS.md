# Details: case-by-case walkthrough and technical notes

Companion to the [README](README.md). This page goes through the specific claims that changed between rounds and explains how each call and score works.

## Round by round: the cases worth looking at

Out of 30 claims, most were right in every round. These are the ones that tell the story. Case numbers match `cases.csv`, and every value below is in the per-round CSVs in [`results/`](results/).

### Round 1: short policy, one question

| Case | Claim | Label | Jev | LLM |
|---|---|---|---|---|
| 5 | Flight + hotel $1,240, no pre-approval reference | needs clarification | reject (0.68) | reject (0.99) |
| 9 | Taxi $48, no receipt | needs clarification | reject (0.80) | reject (0.95) |
| 14 | Client dinner $260 + $90 cocktails | needs clarification* | reject (0.88) | reject (0.99) |
| 3 | Flight $420 (pre-approval only needed over $500) | approve | needs clarification (0.39) | approve |
| 23 | Dinner $210 for 2 people (limit $75/person) | reject | approve (0.24) | reject |
| 30 | Printer ink, manager note "approved WFH supplies" | approve | reject (0.15) | approve |
| 18 | Hotel $380, purpose "misc" | needs clarification | needs clarification | approve (0.90) |
| 28 | Rental car $610, no pre-approval ID | needs clarification | needs clarification | reject (0.95) |

\* relabelled `reject` in Round 2.

- **Cases 5, 9, 14: both models disagreed with my label the same way.** The 5-line policy said receipts and pre-approval were "required" but not what happens when they're missing. That was a policy gap, not a model error, and it's why Round 2 exists.
- **Cases 3, 23, 30: Jev-only misses, all at low confidence (0.15–0.39).** Two need a number comparison ($420 vs $500; $210 ÷ 2 vs $75). For case 23 Jev's probabilities were approve 0.50 / reject 0.38: close to a coin flip, and the confidence score said so.
- **Cases 18, 28: LLM-only misses at 0.90–0.95 confidence.** Across Round 1 the LLM was 0.90–0.99 on every mistake.

### Round 2: explicit 7-rule policy, one question

The clearer policy fixed cases 5, 9 and 14 for **both** models. The LLM also fixed 18 and 28 and went from 25 to 28.

Jev went the other way on approvals:

| Case | Claim | Label | Jev (R2) | Jev (R2 + facts) |
|---|---|---|---|---|
| 3 | Flight $420 | approve | needs clarification (0.45) | needs clarification (0.38), even with `preapproval_required: false` |
| 11 | Office supplies $31 | approve | needs clarification (0.77) | needs clarification (0.59) |
| 16 | Conference registration $350 | approve | needs clarification (0.68) | needs clarification (0.64) |
| 21 | Coffee for team standup $28 | approve | needs clarification (0.40) | needs clarification (0.46) |
| 23 | Dinner $210 for 2 people | reject | reject (0.59) | **reject (1.00)** with `per_person_usd: 105` |

- **Jev became over-cautious.** It got all 17 reject and needs-clarification claims right but only 6–7 of 13 approvals, answering "needs clarification" on ordinary claims. Spotting one violation is a quick judgement; confirming that none of 7 rules applies is a step-by-step check.
- **Code-computed facts fixed the arithmetic, not the caution.** Case 23 went from 0.59 to 1.00, but case 3 stayed wrong even when told pre-approval wasn't required.
- **The LLM's two Round 2 mistakes (cases 4 and 22) were both at 0.90**, its lowest value. With facts added, only case 22 remained wrong.

### Round 3: 7 yes/no questions, code applies the rules

Jev now answers narrow questions; it never sees the policy. Its `probabilities` column in [`round3_atomic_questions.csv`](results/round3_atomic_questions.csv) shows its answer to each question the decision used.

| Case | Claim | Label | Key Jev answer | Result |
|---|---|---|---|---|
| 3 | Flight $420 | approve | purpose clear 0.86 | approve ✓ (fixed) |
| 17 | Uber during client visit | approve | purpose clear 0.84 | approve ✓ (fixed) |
| 21 | Coffee for standup | approve | purpose clear 0.88 | approve ✓ (fixed) |
| 8 | Taxi to airport $22 | approve | purpose clear **0.50** | approve ✓, confidence 0.00 |
| 11 | Office supplies $31 | approve | purpose clear **0.55** | approve ✓, confidence 0.10 |
| 12 | Solo lunch while travelling $19 | approve | purpose clear **0.51** | approve ✓, confidence 0.02 |
| 4 | Flight + hotel to Denver, has pre-approval ID | approve | pre-approval 0.99, purpose clear **0.10** | needs clarification ✗ |
| 16 | Conference registration $350 | approve | purpose clear **0.41** | needs clarification ✗ |
| 22 | Software, "unclear if approved by IT" | needs clarification | purpose clear **0.59** | approve ✗ (LLM also wrong) |

- **Narrow questions fixed most of the approval problem:** 6 of 13 approvals in Round 2 + facts, 11 of 13 here. All 10 rejects stayed right, and the concrete questions came back near-certain ("Pre-approval ID given?" 0.99 / 0.04; "Client named?" 0.99 / 0.04).
- **Every miss and all three shaky wins trace to one question: "Is the business purpose clear?"** It's the vaguest of the 7, and Jev's answers to it sat between 0.41 and 0.59 on five claims.
- **Case 4 is a debatable label.** The claim never states why the trip happened, so "purpose not clear" is defensible under rule 5. I labelled it `approve` assuming a pre-approval ID covers the purpose, but the policy doesn't say that. I left the policy unchanged rather than edit it after seeing the results.

## Technical notes

- **Jev calls.** One `POST /v1/systemone` per claim with `model: "jev-latest"`, a `state` and a map of typed questions. Rounds 1–2 use one `choice` question with three options; Round 3 sends seven `noul` (true/false) questions in the same request. Output tokens are free; cost = input tokens × $0.042 / 1M.
- **LLM calls.** OpenAI-compatible Chat Completions with `response_format: json_schema` (strict): `decision` is an enum of the three labels and `confidence` is a number the model writes itself. It's a self-report, not a token probability.
- **Jev confidence (Rounds 1–2).** TypeSafe's `confidence` field, `(3 × p_max − 1) / 2` for three options. Confidence 0 means the top option is no better than a 1-in-3 guess.
- **Round 3 confidence.** For each yes/no answer *p*, certainty is `|2p − 1|` (0 at p = 0.5, 1 at p = 0 or 1). The decision's confidence is the lowest certainty among the answers the rules actually used to reach it, so one shaky answer makes the whole decision uncertain. This is my own choice, not a TypeSafe feature, and it is stricter than the Round 1–2 measure, so confidence values aren't comparable across rounds.
- **Round 3 rule code** (`combine` in [`compare.py`](compare.py)) applies the rules in order and stops at the first one that fires. It was checked by feeding it hand-written perfect answers for all 30 claims: it reproduces every label.
- **Facts** (`compute_facts`) come from the structured columns in `cases.csv` (category, amount, people, receipt), standing in for fields an upstream extraction step would produce.
- **Latency** is wall-clock time of the successful API call only; time spent waiting out rate limits is excluded.
- **Saved answers.** Every response is cached in `cache_*.jsonl`, keyed by a hash of the policy, question set and case, so a changed policy never reuses stale answers. Round 3 reused the LLM's Round 2 + facts answers because its setup didn't change.
