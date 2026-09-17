"""Every name used in `app/` is actually defined or imported.

Why this exists as a test
-------------------------
A name used in a branch the suite never executes is invisible to everything
else we have. `python -m py_compile` accepts it, because it is syntactically
valid. Importing the module accepts it, because the name is only resolved when
the line runs. And the suite accepts it, because nothing calls that line.

That is not hypothetical. The tender pipeline's Stage A triage block shipped
referencing three names the module did not import - `extraction_model`,
`record_usage` and `UsagePurpose` - and the first a user knew about it was a
tender failing with "name '_extraction_model' is not defined" after a full
parse, chunk and metadata pass. Fixing the first would have exposed the second,
and the second the third, one failed run at a time.

Deliberately narrow: undefined names only. Unused imports and other pyflakes
findings are style, this codebase has some, and failing the suite on them would
get the whole check disabled. The one thing this asserts is the one thing that
breaks production.
"""
import subprocess
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _undefined_names() -> list[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pyflakes", str(APP_DIR)],
        capture_output=True, text=True,
    )
    # pyflakes exits 1 when it has findings, which is normal here.
    if result.returncode not in (0, 1):
        pytest.skip(f"pyflakes could not run: {result.stderr.strip()[:200]}")

    findings = []
    for line in result.stdout.splitlines():
        if "undefined name" not in line:
            continue
        # SQLAlchemy relationship annotations are quoted forward references -
        # `Mapped[list["Requirement"]]` - which resolve through the registry at
        # mapper-configuration time, not at import. pyflakes cannot see that,
        # so every model file reports them. They are marked `# noqa: F821` at
        # the source, which is how they are told apart from a real mistake.
        path, _, rest = line.partition(":")
        line_no = rest.split(":", 1)[0]
        try:
            source = Path(path).read_text(encoding="utf-8").splitlines()[int(line_no) - 1]
        except (OSError, ValueError, IndexError):
            findings.append(line)
            continue
        if "noqa: F821" in source or "Mapped[" in source:
            continue
        findings.append(line)
    return findings


def test_no_undefined_names_in_app():
    findings = _undefined_names()
    assert not findings, (
        "Names used but never defined or imported. Each one is a NameError "
        "waiting for the code path to run:\n  " + "\n  ".join(findings)
    )
