"""
Jev (System One) vs OpenAI structured outputs on the same labelled decisions.

Usage:
    pip install httpx openai
    export TYPESAFE_API_KEY=...      # Jev key (or point TYPESAFE_BASE_URL at a gateway)
    export OPENAI_API_KEY=...
    python compare.py --cases cases.csv
    python compare.py --cases cases.csv --mock     # offline dry run, no API calls

cases.csv columns: id, case, label
  - case  = the extracted info you would normally send to the LLM
  - label = the correct outcome (must be one of the keys in DECISION below)
"""

import argparse, csv, json, os, random, statistics, time
from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------------------
# 1. The decision. Edit this to match your real pipeline.
# ---------------------------------------------------------------------------
POLICY = """Expense reimbursement policy. Apply the rules in order; the first rule that applies decides.
1. Never reimbursable -> reject: alcohol (if a bill includes any alcohol, reject the whole request;
   the employee can resubmit without it), personal items, gym memberships, gifts to employees, fines and tickets.
2. Meals: maximum $75 per person. Over the limit -> reject.
   Client meals must name the client; if the name is missing -> needs_clarification.
3. A receipt is required for any expense over $25. Missing receipt -> needs_clarification.
4. Travel (flights, hotels, rental cars) costing more than $500 in total needs a pre-approval ID.
   Missing ID -> needs_clarification. Travel of $500 or less needs no pre-approval.
5. The business purpose must be clear. Vague or missing purpose -> needs_clarification.
6. Home-office supplies are reimbursable with a manager's approval note.
7. If the expense passes all the rules above -> approve."""

QUESTION = "Given the policy and the expense request, what should happen to this request?"

DECISION = {
    "approve": "The request clearly follows policy and has everything needed.",
    "reject": "The request clearly violates policy or is not reimbursable.",
    "needs_clarification": "Information is missing or ambiguous; a human must ask the submitter before deciding.",
}

# Pricing (USD per 1M tokens). Check current prices before publishing numbers.
JEV_PRICE_IN = float(os.getenv("JEV_PRICE_IN", "0.042"))
OPENAI_PRICE_IN = float(os.getenv("OPENAI_PRICE_IN", "0.25"))
OPENAI_PRICE_OUT = float(os.getenv("OPENAI_PRICE_OUT", "2.00"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
JEV_MODEL = os.getenv("JEV_MODEL", "jev-latest")
JEV_URL = os.getenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai") + "/v1/systemone"


def compute_facts(c: dict) -> dict:
    """The deterministic checks, done in code (like the extraction step in a real pipeline).
    Uses the structured columns in cases.csv: category, amount, people, receipt."""
    amount = float(c["amount"])
    f = {"amount_usd": amount,
         "receipt_required": amount > 25,
         "receipt_provided": c["receipt"] == "yes"}
    if c["category"] == "meal":
        if c.get("people"):
            per_person = round(amount / int(c["people"]), 2)
            f["per_person_usd"] = per_person
            f["over_meal_limit_75"] = per_person > 75
        else:
            f["per_person_usd"] = "unknown (number of people not given)"
            f["over_meal_limit_75"] = False if amount <= 75 else "unknown"
    if c["category"] == "travel":
        f["preapproval_required"] = amount > 500
    return f

# ---------------------------------------------------------------------------
# 2. The two callers. Each returns: decision, confidence (0-1), latency_s, cost_usd
# ---------------------------------------------------------------------------
def call_jev(c: dict, client, facts: bool = False) -> dict:
    state = {"policy": POLICY, "expense_request": c["case"]}
    if facts:
        state["computed_facts (checked by code, trust these)"] = compute_facts(c)
    body = {
        "model": JEV_MODEL,
        "state": state,
        "questions": {
            "decision": {"type": "choice", "instructions": QUESTION, "criteria": DECISION}
        },
    }
    for attempt in range(5):
        t0 = time.perf_counter()
        r = client.post(JEV_URL, json=body)
        if r.status_code in (429, 529):
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        break
    latency = time.perf_counter() - t0  # successful call only
    data = r.json()
    ans = data["answers"]["decision"]
    tokens_in = data.get("usage", {}).get("input_tokens", 0)
    return {
        "decision": ans["choice"],
        "confidence": ans.get("confidence"),
        "probabilities": ans.get("probabilities", {}),
        "latency_s": latency,
        "cost_usd": tokens_in * JEV_PRICE_IN / 1e6,  # output tokens are free
    }


# Atomic mode: Jev answers small yes/no questions in ONE call (evaluated in parallel),
# and plain code applies the policy rules. "Smart if-statements" instead of one big question.
ATOMIC_QUESTIONS = {
    "never_reimbursable": ("Does this expense include alcohol, a personal item, a gym membership, "
                           "a gift to an employee, or a fine or ticket?",
                           "It includes at least one of those items", "It includes none of those items"),
    "client_meal": ("Is this a meal with a client or prospective client?",
                    "It is a meal with a client", "It is not a client meal"),
    "client_named": ("Is the client's name or company given?",
                     "A client name or company is given", "No client name or company is given"),
    "preapproval_id": ("Is a pre-approval ID or reference given?",
                       "A pre-approval ID is given", "No pre-approval ID is given"),
    "purpose_clear": ("Is the business purpose of this expense clear and specific?",
                      "The business purpose is clear", "The purpose is vague, missing or unclear"),
    "home_office": ("Is this a supply for a home office?",
                    "It is a home-office supply", "It is not a home-office supply"),
    "manager_approved": ("Does the request mention a manager's approval?",
                         "A manager's approval is mentioned", "No manager approval is mentioned"),
}


def combine(c: dict, p: dict) -> tuple:
    """The policy, as code. p = Jev's probability that each statement is true.
    Returns (decision, confidence, questions used). Confidence = the least certain
    Jev answer that the decision depended on (certainty = |2p - 1|)."""
    facts = compute_facts(c)
    used = []
    def yes(q):
        used.append(q)
        return p[q] >= 0.5
    def out(decision):
        conf = min([abs(2 * p[q] - 1) for q in used], default=1.0)
        return decision, conf, used
    if yes("never_reimbursable"):                                   # rule 1
        return out("reject")
    if c["category"] == "meal":                                      # rule 2
        if facts.get("over_meal_limit_75") is True:
            return out("reject")
        if facts.get("over_meal_limit_75") == "unknown":
            return out("needs_clarification")
        if yes("client_meal") and not yes("client_named"):
            return out("needs_clarification")
    if facts["receipt_required"] and not facts["receipt_provided"]:  # rule 3
        return out("needs_clarification")
    if facts.get("preapproval_required") and not yes("preapproval_id"):  # rule 4
        return out("needs_clarification")
    if not yes("purpose_clear"):                                     # rule 5
        return out("needs_clarification")
    if c["category"] == "other" and yes("home_office") and not yes("manager_approved"):  # rule 6
        return out("needs_clarification")
    return out("approve")                                            # rule 7


def call_jev_atomic(c: dict, client) -> dict:
    questions = {q: {"type": "noul", "instructions": ins, "criteria": {"true": t, "false": f}}
                 for q, (ins, t, f) in ATOMIC_QUESTIONS.items()}
    body = {"model": JEV_MODEL, "state": {"expense_request": c["case"]}, "questions": questions}
    for attempt in range(5):
        t0 = time.perf_counter()
        r = client.post(JEV_URL, json=body)
        if r.status_code in (429, 529):
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        break
    latency = time.perf_counter() - t0
    data = r.json()
    p = {q: float(a["noul"]) for q, a in data["answers"].items()}
    decision, conf, used = combine(c, p)
    tokens_in = data.get("usage", {}).get("input_tokens", 0)
    return {
        "decision": decision,
        "confidence": conf,
        "probabilities": {q: p[q] for q in used},  # the answers the decision relied on
        "latency_s": latency,
        "cost_usd": tokens_in * JEV_PRICE_IN / 1e6,
    }


OPENAI_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": list(DECISION)},
        "confidence": {"type": "number", "description": "Your confidence 0-1 that the decision is correct"},
    },
    "required": ["decision", "confidence"],
    "additionalProperties": False,
}


def call_openai(c: dict, client, facts: bool = False) -> dict:
    options = "\n".join(f"- {k}: {v}" for k, v in DECISION.items())
    user = c["case"]
    if facts:
        user += "\n\nComputed facts (checked by code, trust these):\n" + json.dumps(compute_facts(c), indent=2)
    messages = [
        {"role": "system", "content": f"{POLICY}\n\n{QUESTION}\nOptions:\n{options}"},
        {"role": "user", "content": user},
    ]
    import re
    from openai import RateLimitError, InternalServerError
    for attempt in range(12):
        t0 = time.perf_counter()
        try:
            r = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "decision", "strict": True, "schema": OPENAI_SCHEMA}},
            )
            break
        except RateLimitError as e:
            # Free tiers allow only a few requests per minute: wait as told, then retry.
            m = re.search(r"retry in ([\d.]+)s", str(e))
            wait = float(m.group(1)) + 1 if m else 20
            print(f"  rate limited, waiting {wait:.0f}s...", flush=True)
            time.sleep(wait)
        except InternalServerError:
            # 500/503 "high demand": the provider is overloaded, try again shortly.
            print("  model busy (503), waiting 30s...", flush=True)
            time.sleep(30)
    else:
        raise SystemExit("Still failing after many retries (daily quota used up, or the model is down). Progress is saved; rerun later to continue.")
    latency = time.perf_counter() - t0  # time of the successful call only, not the waiting
    out = json.loads(r.choices[0].message.content)
    u = r.usage
    return {
        "decision": out["decision"],
        "confidence": out["confidence"],  # self-reported: this is what we're testing
        "probabilities": {},
        "latency_s": latency,
        "cost_usd": u.prompt_tokens * OPENAI_PRICE_IN / 1e6 + u.completion_tokens * OPENAI_PRICE_OUT / 1e6,
    }


def call_mock(case: str, label: str, name: str) -> dict:
    """Fake results so you can check the pipeline and report without keys."""
    rng = random.Random(hash((case, name)))
    right = rng.random() < (0.85 if name == "jev" else 0.8)
    decision = label if right else rng.choice([k for k in DECISION if k != label])
    conf = rng.uniform(0.75, 0.99) if right else rng.uniform(0.4, 0.9)
    if name == "openai":
        conf = round(rng.choice([0.9, 0.95, 0.95, 0.98]), 2)  # LLMs tend to say "0.95" a lot
    return {"decision": decision, "confidence": conf, "probabilities": {},
            "latency_s": rng.uniform(0.07, 0.5) if name == "jev" else rng.uniform(1.5, 6),
            "cost_usd": 400 * JEV_PRICE_IN / 1e6 if name == "jev" else 0.0004}

# ---------------------------------------------------------------------------
# 3. Metrics
# ---------------------------------------------------------------------------
def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def summarize(rows, name):
    n = len(rows)
    correct = [r["decision"] == r["label"] for r in rows]
    lat = [r["latency_s"] for r in rows]
    s = {
        "model": name,
        "n": n,
        "accuracy": sum(correct) / n,
        "p50_latency_s": statistics.median(lat),
        "p95_latency_s": pct(lat, 95),
        "cost_per_1k_decisions_usd": 1000 * sum(r["cost_usd"] for r in rows) / n,
        "distinct_confidence_values": len({round(r["confidence"], 2) for r in rows}),
    }
    # Does confidence separate right from wrong?
    right_c = [r["confidence"] for r, c in zip(rows, correct) if c]
    wrong_c = [r["confidence"] for r, c in zip(rows, correct) if not c]
    s["avg_conf_when_right"] = statistics.mean(right_c) if right_c else None
    s["avg_conf_when_wrong"] = statistics.mean(wrong_c) if wrong_c else None
    # Threshold policy: auto-decide above T, send the rest to a human
    s["thresholds"] = []
    for t in (0.6, 0.7, 0.8, 0.9, 0.95):
        auto = [c for r, c in zip(rows, correct) if r["confidence"] >= t]
        s["thresholds"].append({
            "threshold": t,
            "auto_decided_pct": len(auto) / n,
            "accuracy_on_auto": (sum(auto) / len(auto)) if auto else None,
            "to_human_pct": 1 - len(auto) / n,
        })
    return s


def fmt(x, kind="pct"):
    if x is None:
        return "–"
    return f"{x:.0%}" if kind == "pct" else f"{x:.3f}"


def report(summaries, path):
    lines = [f"# Jev vs LLM structured outputs ({os.path.basename(path)})\n"]
    lines.append("| Metric | " + " | ".join(s["model"] for s in summaries) + " |")
    lines.append("|---|" + "---|" * len(summaries))
    rows = [
        ("Cases", lambda s: str(s["n"])),
        ("Accuracy", lambda s: fmt(s["accuracy"])),
        ("Median latency", lambda s: f'{s["p50_latency_s"]*1000:.0f} ms'),
        ("p95 latency", lambda s: f'{s["p95_latency_s"]*1000:.0f} ms'),
        ("Cost / 1,000 decisions", lambda s: f'${s["cost_per_1k_decisions_usd"]:.4f}'),
        ("Avg confidence when right", lambda s: fmt(s["avg_conf_when_right"], "num")),
        ("Avg confidence when wrong", lambda s: fmt(s["avg_conf_when_wrong"], "num")),
        ("Distinct confidence values", lambda s: str(s["distinct_confidence_values"])),
    ]
    for label, f in rows:
        lines.append(f"| {label} | " + " | ".join(f(s) for s in summaries) + " |")

    lines.append("\n## Auto-decide above a confidence threshold, send the rest to a human\n")
    for s in summaries:
        lines.append(f"**{s['model']}**\n")
        lines.append("| Threshold | Auto-decided | Accuracy on auto | Sent to human |")
        lines.append("|---|---|---|---|")
        for t in s["thresholds"]:
            lines.append(f"| ≥ {t['threshold']} | {fmt(t['auto_decided_pct'])} | "
                         f"{fmt(t['accuracy_on_auto'])} | {fmt(t['to_human_pct'])} |")
        lines.append("")
    lines.append("_Bigger gap between 'confidence when right' and 'when wrong' = more useful "
                 "confidence. A model whose accuracy climbs as you raise the threshold can safely "
                 "automate the confident cases._")
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# 4. Run
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="cases.csv")
    ap.add_argument("--mock", action="store_true", help="no API calls, fake results")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--only", choices=["jev", "openai"], help="run just one model")
    ap.add_argument("--fresh", action="store_true", help="ignore saved answers and call the APIs again")
    ap.add_argument("--facts", action="store_true", help="give both models the code-computed checks")
    ap.add_argument("--atomic", action="store_true",
                    help="Jev answers small yes/no questions and code applies the rules (LLM runs with --facts)")
    args = ap.parse_args()

    cases = list(csv.DictReader(open(args.cases, encoding="utf-8-sig")))
    bad = [c["id"] for c in cases if c["label"] not in DECISION]
    if bad:
        raise SystemExit(f"Labels not in DECISION for ids: {bad}")

    runners = {}
    if args.mock:
        runners = {n: (lambda n: lambda c: call_mock(c["case"], c["label"], n))(n) for n in ("jev", "openai")}
    else:
        if args.only != "openai":
            import httpx
            jc = httpx.Client(timeout=30, headers={"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}"})
            if args.atomic:
                runners["jev"] = lambda c: call_jev_atomic(c, jc)
            else:
                runners["jev"] = lambda c: call_jev(c, jc, args.facts)
        if args.only != "jev":
            from openai import OpenAI
            oc = OpenAI()
            runners["openai"] = lambda c: call_openai(c, oc, args.facts or args.atomic)

    import hashlib
    variant = "atomic" if args.atomic else ("facts" if args.facts else "text")
    def vhash_for(v):
        extra = json.dumps(ATOMIC_QUESTIONS) if v == "atomic" else ""
        return hashlib.sha1((POLICY + QUESTION + json.dumps(DECISION) + v + extra).encode()).hexdigest()[:8]
    # In atomic mode only Jev changes; the LLM keeps its facts setup (and its saved answers).
    model_variant = {"jev": variant, "openai": "facts" if variant == "atomic" else variant}
    print(f"Variant: {variant}", flush=True)
    all_rows, summaries = [], []
    for name, fn in runners.items():
        print(f"Running {name} on {len(cases)} cases...", flush=True)
        model_id = JEV_MODEL if name == "jev" else OPENAI_MODEL
        cache_path = f"cache_{name}_{model_id.replace('/', '_')}.jsonl"
        vhash = vhash_for(model_variant[name])
        cache = {}
        if not args.fresh and not args.mock and os.path.exists(cache_path):
            for line in open(cache_path, encoding="utf-8"):
                rec = json.loads(line)
                if rec["key"].startswith(vhash + "|"):
                    cache[rec["key"]] = rec["result"]
            if cache:
                print(f"  reusing {len(cache)} saved answers for this setup (use --fresh to redo)", flush=True)
        done = [0]
        def tracked(c, fn=fn, name=name, vhash=vhash):
            key = f"{vhash}|{c['id']}|{c['case']}"
            if key in cache:
                r = cache[key]
            else:
                r = fn(c)
                if not args.mock:
                    with open(cache_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"key": key, "result": r}) + "\n")
            done[0] += 1
            ok = "✓" if r["decision"] == c["label"] else "✗"
            print(f"  [{name}] {done[0]}/{len(cases)} case {c['id']}: {r['decision']} {ok} "
                  f"(conf {r['confidence']:.2f}, {r['latency_s']*1000:.0f} ms)", flush=True)
            return r
        if args.workers == 1:  # plain loop: Ctrl+C stops it immediately
            results = [tracked(c) for c in cases]
        else:
            with ThreadPoolExecutor(args.workers) as ex:
                results = list(ex.map(tracked, cases))
        rows = [{**c, **r, "model": name,
                 "probabilities": json.dumps({k: round(v, 3) for k, v in r["probabilities"].items()})}
                for c, r in zip(cases, results)]
        all_rows += rows
        label = (f"Jev ({JEV_MODEL}, {model_variant[name]})" if name == "jev"
                 else f"LLM ({OPENAI_MODEL}, {model_variant[name]})")
        summaries.append(summarize(rows, label))

    with open(f"results_{variant}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["model", "id", "label", "decision", "confidence",
                                          "probabilities", "latency_s", "cost_usd", "case"], extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)
    json.dump(summaries, open(f"summary_{variant}.json", "w", encoding="utf-8"), indent=2)
    print(report(summaries, f"report_{variant}.md"))
    print(f"\nWrote results_{variant}.csv, summary_{variant}.json, report_{variant}.md")


if __name__ == "__main__":
    main()
