# Extraction eval harness

Measures a tender analysis against a tracker a human analyst actually produced
for the same tender, so "the extraction is noisy" becomes a number that can go
down.

## Why

Two analyst-authored trackers exist for tenders this pipeline has also
processed. They are the only ground truth available, and comparing against them
is what turned a vague quality complaint into this:

| | analyst | pipeline (pre-rewrite) |
|---|---|---|
| SMEDA Dashboard, 125 pages | 57 rows | 686 rows |
| MOITT NODE, 528 pages | 266 rows | not run |

Both analysts, independently, produced ~0.5 rows per page. The pipeline produced
5.5. The recorded baseline in `baselines.json` is the full picture:

```
recall     70.2%   40/57 gold obligations found
precision   5.8%   40/686 emitted rows map to a gold row
ratio      12.04x
marks     extracted 222 against a stated 100 -> DOES NOT MATCH
```

Recall being only 70% is the part that is easy to miss: the over-extraction was
not buying completeness. 17 of the analyst's 57 obligations were absent from a
686-row sheet.

## Running it

Score a workbook the pipeline produced. No database, no API key, no network:

```bash
python -m tests.eval.run_eval --workbook path/to/requirements_and_matches.xlsx \
    --gold smeda_dashboard --verbose
```

Score a tender in the database, which is the loop to use after a prompt edit:

```bash
python -m tests.eval.run_eval --tender-id <uuid> --gold smeda_dashboard
```

`--verbose` is the useful mode. It prints the gold obligations that were missed
(the regressions that matter) and the emitted rows that matched nothing (noise,
or occasionally a real find the analyst left out - read them before assuming
they are all noise).

Gold sets: `smeda_dashboard`, `moitt_node`.

## Reading the numbers

- **RECALL is the number that must not regress.** Everything else is a
  legitimate trade-off; silently dropping a mandatory submission requirement is
  not. Use `--fail-under 0.70` as a CI gate.
- **PRECISION is the noise measure.** It is expected to be low against a
  non-exhaustive reference, because the analyst's sheet is one competent answer
  rather than the only one. Read the unmatched rows before treating a precision
  number as a verdict.
- **RATIO** is blunt but it is what a reviewer feels first.
- **marks** catches the scoring-band bug: bands are alternatives for one
  criterion, and summing them reported a 100-mark tender as 222.

## What this harness cannot tell you

Four of the 17 missed SMEDA rows are ones the analyst *derived* rather than
found: "Final Technical Pack QA", "Final Financial Pack QA", "EPADS Upload &
Verification", and a conditional presentation row. No extractor can produce them
from the document text, so recall has a ceiling near 93% on this gold set until
those are generated some other way. Do not chase the last 7% with prompt edits.

The gold sets are also not exhaustive or infallible. They are one analyst's
work, and where a run disagrees with them it is worth looking at both.

## Files

- `gold/*.json` - the analyst trackers, normalised. Extracted from the original
  `.xlsx` sheets; `Section Name` in those sheets is a group marker set once per
  section and blank beneath, so it is carried forward per row here.
- `score.py` - similarity and metrics. Token overlap plus a reference-agreement
  bonus, deliberately not embeddings; see the module docstring for why.
- `test_score.py` - tests the scorer, not extraction. The instrument has to be
  trustworthy before its readings mean anything.
- `run_eval.py` - the CLI.
- `baselines.json` - recorded runs, for `--save-baseline` comparison.
