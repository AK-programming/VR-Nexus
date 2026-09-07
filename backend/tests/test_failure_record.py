"""The failure record behind the Processing page's error log.

`_error_detail` is what turns a raised exception into the text an operator reads
when a tender did not finish. It runs with no database, no Redis and no worker —
it is a pure function over an exception object — so these tests raise real
exceptions and read what would be written to `Tender.error_detail`.

What is being pinned:

* the exception **class** always appears, because `str(exc)` alone is empty or
  near-useless for a whole family of exceptions and "something failed" with no
  type is the least helpful line an error log can carry;
* the **stack tail** is kept, because "which call raised" is the question a
  failure has to answer, and it is the tail rather than the head that answers it;
* the result is **bounded**, so one pathological traceback cannot fill the column.
"""
import pytest

from app.tasks.tender_pipeline import (
    ERROR_DETAIL_LIMIT,
    ERROR_FRAME_COUNT,
    _error_detail,
)


def _raise(exc: BaseException) -> BaseException:
    """Returns `exc` with a real __traceback__ attached."""
    try:
        raise exc
    except BaseException as caught:  # noqa: BLE001 - the point is to capture it
        return caught


def test_includes_class_and_message():
    detail = _error_detail(_raise(ValueError("page 12 is not a PDF page")))

    assert detail.startswith("ValueError: page 12 is not a PDF page")


def test_names_the_class_even_when_the_message_is_empty():
    """A bare `RuntimeError()` stringifies to "". Without the class name the log
    would show a blank line where the reason should be."""
    detail = _error_detail(_raise(RuntimeError()))

    assert detail.startswith("RuntimeError")
    assert detail.strip() != ""


def test_keeps_the_stack_tail():
    """The frame that raised has to survive — it is the whole point of keeping a
    trace rather than just the message."""
    def inner():
        raise KeyError("clause_requirement_description")

    try:
        inner()
    except KeyError as exc:
        detail = _error_detail(exc)

    assert "inner" in detail
    assert "test_failure_record.py" in detail


def test_is_bounded():
    """A deep recursion produces a traceback far longer than the column; the
    result is clipped rather than rejected by the database."""
    def recurse(n: int):
        if n == 0:
            raise ZeroDivisionError("bottom")
        recurse(n - 1)

    try:
        recurse(60)
    except ZeroDivisionError as exc:
        detail = _error_detail(exc)

    assert len(detail) <= ERROR_DETAIL_LIMIT
    # And it kept the *end* of the stack, not the start.
    assert detail.count("in recurse") <= ERROR_FRAME_COUNT


@pytest.mark.parametrize(
    "exc",
    [ValueError("bad"), OSError("no such file"), TimeoutError()],
)
def test_never_returns_empty(exc):
    assert _error_detail(_raise(exc)).strip() != ""
