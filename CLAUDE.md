# CLAUDE.md

Project instructions for Claude Code.

## Start here — project context

Before exploring the tree, read **`PROJECT_CONTEXT.md`** in this folder. It is the
single onboarding file — what VR-Nexus is, where every important file lives, the
workflow, how to run it, current status, and the traps — so you do not have to
re-discover the project (and burn context) each new session. Read it first.

## Skill activation

At the start of any task-oriented session — any interaction where you will
use tools and produce deliverables — invoke the task-observer skill before
beginning work. This ensures skill improvement opportunities are captured
throughout the session.

When loading any skill, check the observation log for OPEN observations
tagged to that skill. Apply their insights to the current work, even if
the skill file hasn't been updated yet. This enables immediate application
of observations before they're permanently integrated during the weekly
review.

### Task Observer workspace

The observation log and related state live on the stable project path (not
the working directory, which may be an ephemeral checkout):

```
~/.claude/projects/C--Users-Muhammad-Afnan-Khan-Desktop-Frontend-Design-vr-nexus-frontend/skill-observations/
```

- `log.md` — the observation log
- `cross-cutting-principles.md` — principles that apply across all skills
- `last-review-date.txt` — `never`, or the date the last review actually ran
- `archive/` — resolved observations, created on first archival
