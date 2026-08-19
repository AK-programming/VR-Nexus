"""Loads the built-in parsers so the category registry is populated.

Importing this module is what makes `base.get_parser(category)` resolve. It
exists as a separate module rather than living in `__init__.py` so that importing
`app.services.parsers.base` (for its dataclasses, in tests for example) does not
drag in PyMuPDF, python-docx and python-pptx.
"""
from app.models.enums import DocumentCategory
from app.services.library.parsers import base, case_study, company, methodology  # noqa: F401
from app.services.library.parsers.base import ParseResult, RawDoc, get_parser, parse

__all__ = ["DocumentCategory", "ParseResult", "RawDoc", "get_parser", "parse", "base"]
