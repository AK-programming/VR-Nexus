"""Scoring an extracted tracker against a human-authored one.

Why this exists
---------------
Extraction quality was, until this module, a matter of opinion. The pipeline
produced 687 rows for a 125-page tender where an analyst produced 57, and the
only available descriptions of the problem were "too much irrelevant thing" and
"not the desired output" - both true, neither actionable, and neither able to
tell you whether a prompt edit helped or hurt.

Two analyst-authored trackers exist for tenders this pipeline has also
processed (see gold/). They are the only ground truth available, so they are the
benchmark. This module answers three questions about any run:

  RECALL     of the obligations the analyst found, how many did we find?
             This is the number that must not regress. Everything else can be
             traded off; silently losing a mandatory submission requirement
             cannot.
  PRECISION  of the rows we emitted, how many correspond to something the
             analyst thought was worth a row? This is the noise measure.
  RATIO      rows emitted / gold rows. Blunt, but it is the number a reviewer
             feels first, and it caught the original problem.

Deliberately NOT a pass/fail unit test. Extraction is a judgment call against a
non-exhaustive reference: the analyst's sheet is one competent answer, not the
only one, and a row we emit that they omitted is sometimes a genuine find. So
this reports numbers for a human to read and compare, and the only hard gate
worth wiring into CI is "recall did not drop against the last recorded run".

Similarity
----------
Matching is token-overlap (F1 over content words) plus a bonus when the
tender's own reference number agrees, and deliberately NOT embeddings.
Embeddings would score paraphrase better, but they would add a ~130MB model
download to a scoring script, make the numbers non-deterministic across
fastembed versions, and make a regression in the scorer indistinguishable from
a regression in extraction. Token overlap is crude, reproducible and free, and
it is sufficient here because both sides of the comparison are now short
imperative sentences about the same procurement artefacts. `--verbose` prints
the near-misses so a human can check what the crudeness cost.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

GOLD_DIR = Path(__file__).parent / "gold"

#: Words that carry no discriminating signal between two procurement
#: obligations. Kept short on purpose: an aggressive stoplist makes unrelated
#: rows look similar, which inflates both recall and precision and would make
#: this module lie in the flattering direction.
_STOP = {
    "a", "an", "and", "or", "the", "of", "to", "in", "on", "for", "at", "by",
    "with", "as", "is", "are", "be", "been", "shall", "should", "must", "will",
    "may", "any", "all", "this", "that", "these", "those", "it", "its", "from",
    "provide", "submit", "ensure", "prepare", "complete", "please",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: Above this token-F1 an emitted row is taken to be the same obligation as a
#: gold row. Calibrated by hand against the SMEDA pair list: 0.45 accepts
#: "Provide NTN and STRN/PST registrations" against "Must be registered with
#: relevant tax authorities. Must have NTN and STRN and PST registration"
#: while still rejecting two different eligibility criteria from the same list.
#: Raise it and recall drops for honest paraphrase; lower it and unrelated rows
#: in the same section start matching each other.
MATCH_THRESHOLD = 0.45

#: Added to the score when both sides cite the same tender reference. A shared
#: citation is strong evidence two rows are the same obligation even when the
#: wording diverges, which is exactly the case for a row the analyst rewrote
#: heavily.
REFERENCE_BONUS = 0.25


def tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOP and len(t) > 1}


def normalise_reference(ref: str) -> set[str]:
    """Reference citations as comparable fragments.

    "BDS Clause 6 / ITB 7.1" and "ITB 7.1" should agree, so a reference is
    reduced to the set of its alphanumeric fragments and compared by overlap
    rather than by string equality.
    """
    return {t for t in _TOKEN_RE.findall((ref or "").lower()) if t not in ("clause", "form", "no")}


def similarity(emitted: dict, gold: dict) -> float:
    """Token-F1 on the description, plus a reference-agreement bonus, capped at 1."""
    a, b = tokens(emitted.get("description", "")), tokens(gold.get("description", ""))
    if not a or not b:
        f1 = 0.0
    else:
        overlap = len(a & b)
        if not overlap:
            f1 = 0.0
        else:
            precision, recall = overlap / len(a), overlap / len(b)
            f1 = 2 * precision * recall / (precision + recall)

    ref_a, ref_b = normalise_reference(emitted.get("reference", "")), normalise_reference(gold.get("reference", ""))
    bonus = REFERENCE_BONUS if ref_a and ref_b and (ref_a & ref_b) else 0.0
    return min(1.0, f1 + bonus)


@dataclass
class Result:
    gold_name: str
    gold_rows: int
    emitted_rows: int
    matched_pairs: list = field(default_factory=list)   # (emitted_idx, gold_idx, score)
    missed_gold: list = field(default_factory=list)     # gold rows nothing matched
    unmatched_emitted: list = field(default_factory=list)

    @property
    def recall(self) -> float:
        return len(self.matched_pairs) / self.gold_rows if self.gold_rows else 0.0

    @property
    def precision(self) -> float:
        return len(self.matched_pairs) / self.emitted_rows if self.emitted_rows else 0.0

    @property
    def ratio(self) -> float:
        return self.emitted_rows / self.gold_rows if self.gold_rows else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def score(emitted: list[dict], gold: list[dict], gold_name: str = "") -> Result:
    """Greedy one-to-one match, best pairs first.

    One-to-one matters: without it, twelve near-identical emitted rows all match
    the single gold row they duplicate, and the duplication that was the whole
    problem scores as perfect recall. Greedy-by-best-score is used rather than
    an optimal assignment because the pairings that matter here are not close
    (a correct match scores far above the runner-up), and greedy is inspectable
    when someone asks why two particular rows were paired.
    """
    candidates = []
    for i, e in enumerate(emitted):
        for j, g in enumerate(gold):
            s = similarity(e, g)
            if s >= MATCH_THRESHOLD:
                candidates.append((s, i, j))
    candidates.sort(reverse=True)

    used_e: set[int] = set()
    used_g: set[int] = set()
    pairs = []
    for s, i, j in candidates:
        if i in used_e or j in used_g:
            continue
        used_e.add(i)
        used_g.add(j)
        pairs.append((i, j, round(s, 3)))

    return Result(
        gold_name=gold_name,
        gold_rows=len(gold),
        emitted_rows=len(emitted),
        matched_pairs=pairs,
        missed_gold=[gold[j] for j in range(len(gold)) if j not in used_g],
        unmatched_emitted=[emitted[i] for i in range(len(emitted)) if i not in used_e],
    )


def load_gold(name: str) -> dict:
    path = GOLD_DIR / (name if name.endswith(".json") else f"{name}.json")
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in GOLD_DIR.glob("*.json")))
        raise SystemExit(f"No gold set {name!r}. Available: {available}")
    return json.loads(path.read_text(encoding="utf-8"))


def report(result: Result, meta: dict, verbose: bool = False, cost: dict | None = None) -> str:
    """The human-readable scorecard."""
    pages = meta.get("pages") or 0
    lines = [
        "",
        f"  {result.gold_name}",
        f"  {'=' * max(len(result.gold_name), 40)}",
        f"  gold rows          {result.gold_rows:>6}   ({result.gold_rows / pages:.2f}/page)" if pages
        else f"  gold rows          {result.gold_rows:>6}",
        f"  emitted rows       {result.emitted_rows:>6}   ({result.emitted_rows / pages:.2f}/page)" if pages
        else f"  emitted rows       {result.emitted_rows:>6}",
        f"  ratio              {result.ratio:>6.2f}x  (1.00 is analyst parity)",
        "",
        f"  RECALL             {result.recall:>6.1%}   {len(result.matched_pairs)}/{result.gold_rows} gold obligations found",
        f"  PRECISION          {result.precision:>6.1%}   {len(result.matched_pairs)}/{result.emitted_rows} emitted rows map to a gold row",
        f"  F1                 {result.f1:>6.1%}",
    ]
    if cost:
        lines += [
            "",
            f"  input tokens       {cost.get('input_tokens', 0):>6,}",
            f"  output tokens      {cost.get('output_tokens', 0):>6,}",
            f"  cost (USD)         ${cost.get('cost', 0):.3f}",
        ]
    if verbose:
        lines += ["", f"  MISSED GOLD ROWS ({len(result.missed_gold)}) - these are the regressions that matter:"]
        for g in result.missed_gold[:40]:
            lines.append(f"    [{g.get('reference', '') or '-'}] {g.get('description', '')[:96]}")
        if len(result.missed_gold) > 40:
            lines.append(f"    ... and {len(result.missed_gold) - 40} more")
        lines += ["", f"  UNMATCHED EMITTED ROWS ({len(result.unmatched_emitted)}) - noise, or finds the analyst omitted:"]
        for e in result.unmatched_emitted[:40]:
            sec = (e.get("section") or "")[:30]
            lines.append(f"    ({sec}) {e.get('description', '')[:88]}")
        if len(result.unmatched_emitted) > 40:
            lines.append(f"    ... and {len(result.unmatched_emitted) - 40} more")
    return "\n".join(lines) + "\n"
