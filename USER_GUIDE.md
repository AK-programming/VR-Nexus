# VR-Nexus — User Guide

VR-Nexus reads a procurement tender for you. It extracts every requirement,
scores how many marks each is worth, matches each one against your company's own
evidence — case studies, methodology documents, company documents — and hands
you a reviewable requirements tracker and a ready-to-submit document pack. You
stay in control: VR-Nexus proposes the matches, and a person confirms them
before anything is finalized.

This guide is for the people who use VR-Nexus to win bids. For running and
deploying the system, see `README.md` (developers) and `docs/DEPLOYMENT.md`
(operations).

## The big picture

There are two halves to VR-Nexus, and they work best in this order:

1. **The Evidence Library** is your company's memory — the case studies,
   methodology documents and company documents you can prove things with. You
   build it once and top it up over time. The tender analysis can only match
   against evidence you have already added and trained.
2. **Tender Analysis** is where a specific tender is uploaded and read
   end-to-end, and where you review the result and generate the output pack.

So the first time you use VR-Nexus, spend a little time in the Evidence Library
before you upload your first tender.

## Signing in

Register with your name, email and a password, then sign in. Registration does
not sign you in automatically — you will be taken to the sign-in page with a
confirmation, which is deliberate. After five wrong passwords an account is
locked for a short while.

There are two roles, **Admin** and **User**. Day-to-day tender work — uploading,
reviewing, finalizing, training the library — is available to both; Admin adds
account administration on top.

## Part 1 — Build your Evidence Library

Open **Documents** from the sidebar. The library is organised into three
categories, each on its own tab:

- **Case studies** — projects you have delivered, with their sectors, clients
  and outcomes.
- **Methodology** — how you do the work, broken down by phase.
- **Company documents** — certificates, registrations, policies and other
  single-purpose files.

To add evidence:

1. Go to **Documents → Upload** and drag your files in (PDF, Word, PowerPoint and
   images are accepted). Add any metadata you know — sector, client, service
   line — which sharpens later matching.
2. Back on the library listing, press **Train** (also called "memorize"). This
   indexes the document: it is split into passages, tagged, and turned into the
   searchable vectors the tender matcher uses. You can watch this happen live on
   the indexing progress view.
3. A trained document is available to the tender matcher immediately — there is
   no restart or nightly job. Pressing Train again only re-indexes what changed.

If you upload the exact same file twice, VR-Nexus tells you it is a duplicate
rather than storing it again. A merely similar file uploads with a gentle
warning for you to judge.

You do not need an internet connection or any API key for the library to work —
indexing runs locally.

## Part 2 — Upload a tender

Open **Tender Analysis** from the sidebar, then **Upload**.

1. Drop in the tender PDF (up to 100 MB, up to several hundred pages). PDFs only
   — VR-Nexus reads pages directly and preserves page numbers.
2. Optionally fill in the tender's name, reference, issuing authority, sector,
   location, value and deadline. All of this is optional — VR-Nexus fills in
   what it can from the document itself, so a blank form is a valid upload.
3. Continue. The analysis starts immediately.

## Part 3 — Watch the analysis

The **Processing** view shows the tender moving through eight steps: Parse →
Chunk → Extract → Merge → Match → Report → Assemble → Review. A live indicator
tells you whether the page is receiving updates in real time, polling, or
temporarily out of contact.

You can close the tab and come back later — the progress lives on the server,
not in your browser, so you will find the tender exactly where it got to. If a
background step is interrupted, processing resumes from the last completed chunk
rather than starting the whole tender over.

When the tender reaches **Ready for review**, the analysis is done and it is your
turn.

## Part 4 — Review the tender

Open the tender (from Processing, or from the Tender Analysis list) to reach the
**review workspace**. This is where you check VR-Nexus's work clause by clause.

At the top you get the headline numbers: how many requirements were found, your
coverage (the share of available marks your evidence currently answers), how many
matches are waiting on your decision, and how many requirements have no evidence
yet.

Below that, every extracted requirement is a row showing its page, section and
clause, whether it is mandatory, its evaluation type, the marks it carries, the
best match confidence, and a coverage chip:

- **Covered** — answered by an accepted match, or an auto-match VR-Nexus is
  confident in and you have not rejected. Its marks count toward coverage.
- **Review** — a suggested match is waiting for your decision.
- **Missing** — nothing in your library answers this yet.
- **No evidence needed** — the requirement needs no supporting document.

Use the **All / Needs review / Missing** filter to focus on the rows that still
need you.

Expand a row to see the candidate documents. For each one you can:

- **Accept** it — confirm this document answers the requirement.
- **Reject** it — this document does not, and its marks should not count.
- **Reassign** it — pick a different document from your library instead. A
  search box helps you find the right one. After reassigning, Accept it to count
  its marks.

Every decision updates the coverage and marks totals immediately, so you always
see the real state, not a guess.

## Part 5 — Finalize and download the pack

When the matches look right, press **Finalize tender**. This is the deliberate
human checkpoint — VR-Nexus never finalizes on its own, because a wrong auto-match
should never silently cost you marks.

Finalizing rebuilds the output pack from the matches you accepted and locks the
analysis. You can finalize again later if you change a decision.

**Download output** gives you a single ZIP containing:

- **`requirements_and_matches.xlsx`** — the tracker, with four sheets:
  *Requirements* (every clause with its coverage and the file that answers it),
  *Summary* (counts and marks totalled overall, by section and by evaluation
  type), *Evidence Matches* (every candidate with its confidence and your
  decision), and *Instructions*.
- **The original tender**, for reference.
- **A `Required Documents` folder** holding a copy of every accepted piece of
  evidence, named by category and title — ready to attach to your submission.
- A `summary.json` with the headline figures.

## The AI Assistant

Open **AI Assistant** from the sidebar to ask your Evidence Library questions in
plain language — "What water-supply projects have we delivered?", "Summarise our
QA methodology." Every answer is drawn only from your indexed documents and shows
the exact passages it used, each linking to the source document. Nothing is
answered from outside your library.

Two modes share the box:

- **Ask** returns a written answer with its sources. If the library cannot
  support the question — or if generated answers are switched off in your
  deployment — you will see the closest passages instead, clearly marked as not
  grounded, so you can read them yourself.
- **Find** skips the writing and just returns the ranked passages, which is handy
  when you want the source material directly.

Use the category selector to search only case studies, only methodology, or only
company documents.

## Tips

- Build and train the library *before* running a tender — the matcher can only
  find evidence you have already added.
- A low coverage number early on usually means missing evidence, not a bad
  tender. Add the relevant documents to the library, retrain, and re-run.
- "Not grounded" on an answer is honest, not broken: it means your library does
  not yet contain something that answers the question.
- Re-finalize after any further review to regenerate the output pack.
