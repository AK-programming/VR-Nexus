"""
Excel export customization — client requirement (Users admin page follow-up):
"Set excel sheet to customize when the excel sheet form first show them to
user that i make it and that on user that what column they want what they
delete and what they mean they will set there format after that implement
that changes and then paste on the folder."

Two levels, per the client's own clarifying answers:
  - A REUSABLE default the user sets up once on their account
    (User.default_excel_template) and that applies to every tender they
    generate from then on.
  - A PER-TENDER override (Tender.excel_template_override), because "the
    problem they want the different format for the different [tenders] but
    may be the same tender" — one tender can still deviate from the saved
    default without changing it for every other tender.

Both columns store exactly this shape (as JSON), validated through
ExcelTemplate so a malformed/stale value can never reach openpyxl. See
app/tasks/tender_pipeline.py's _resolve_excel_template / _apply_excel_template
for how a template turns into the actual Requirements sheet, and
app/api/routes/excel_template.py for the endpoints that read/write it.
"""
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# The fixed columns _assemble_folder can build, keyed stably so a template
# survives a future label wording change. "page_number" through "coverage"
# mirrors TENDER_HEADERS + VRNEXUS_HEADERS in tender_pipeline.py exactly —
# see FIXED_COLUMN_REGISTRY there for the key -> (label, getter) mapping this
# schema's `key` field refers to.
FIXED_COLUMN_KEYS: list[str] = [
    "page_number",
    "section_name",
    "responsibility",
    "reference_number",
    "description",
    "mandatory",
    "evaluation_impact",
    "owner_bd",
    "owner_technical",
    "owner_finance_legal",
    "owner_hr",
    "owner_joint",
    # Legacy partner columns, kept selectable for tenders analysed before the
    # owner_* columns existed. See FIXED_COLUMN_REGISTRY in
    # app/tasks/tender_pipeline.py.
    "dpl",
    "prime",
    "the_t",
    "joint_responsibility",
    "evidence_description",
    "remarks",
    "marks",
    "matched_files",
    "coverage",
]

MAX_TEMPLATE_COLUMNS = 60
MAX_ADDED_COLUMNS = 20


class ExcelColumnConfig(BaseModel):
    """One column in the customized sheet, in the order the user wants it.

    `key` is either one of FIXED_COLUMN_KEYS, or the exact label of one of
    this tender's own extracted "extra" fields (Requirement.extra_fields) —
    the assembler treats any key it doesn't recognise as an extra-field
    lookup and simply produces a blank column if the tender never had that
    field, rather than erroring on a template written against a different
    tender.
    """

    key: str = Field(..., min_length=1, max_length=120)
    # What the user wants the header cell to say. Defaults to the platform's
    # own label when the user hasn't renamed it (see the assembler).
    label: Optional[str] = Field(default=None, max_length=120)
    visible: bool = True


class ExcelTemplate(BaseModel):
    """A saved (or one-off) export shape for the Requirements sheet.

    `columns` empty/None means "use the platform default" (every fixed
    column + every extra field this tender produced, in the original order)
    — that is also what a brand-new account has, so nothing changes for a
    user who never opens the customizer.
    """

    columns: list[ExcelColumnConfig] = Field(default_factory=list)
    # "They are able to delete the empty rows" — when true, a row whose
    # visible columns are ALL blank is dropped from the sheet.
    delete_empty_rows: bool = False
    # "They are able to add some column etc" — extra blank columns appended
    # after the configured ones, for the user's own manual notes; VR-Nexus
    # has no data to put in them, so they always render empty.
    added_columns: list[str] = Field(default_factory=list)

    @field_validator("columns")
    @classmethod
    def _cap_columns(cls, v: list[ExcelColumnConfig]) -> list[ExcelColumnConfig]:
        if len(v) > MAX_TEMPLATE_COLUMNS:
            raise ValueError(f"A template can have at most {MAX_TEMPLATE_COLUMNS} columns.")
        return v

    @field_validator("added_columns")
    @classmethod
    def _cap_added(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_ADDED_COLUMNS:
            raise ValueError(f"A template can add at most {MAX_ADDED_COLUMNS} extra blank columns.")
        cleaned = [str(name).strip()[:120] for name in v if str(name).strip()]
        return cleaned


class ExcelTemplateOut(BaseModel):
    """GET response: the template plus whether it's actually set (None means
    "no template saved yet, platform default applies") vs. an explicit,
    possibly-empty ExcelTemplate the user chose."""

    template: Optional[ExcelTemplate] = None


class ExcelTemplateIn(BaseModel):
    """PUT body. `template: null` explicitly clears back to the platform
    default (distinct from omitting the field, which most clients can't do
    anyway — FastAPI treats a JSON body as the whole object here)."""

    template: Optional[ExcelTemplate] = None
