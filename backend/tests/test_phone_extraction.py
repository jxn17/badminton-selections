"""Phone-number auto-detection from arbitrary pasted text (used by the paste-to-
schedule feature). The regex is deliberately permissive; correctness comes from
resolving each candidate against real players, tested separately in
test_service_scheduling.py."""
from __future__ import annotations

from app.csv_import import extract_candidate_phones, normalize_phone


def test_extracts_clean_number():
    assert extract_candidate_phones("9876543210") == ["9876543210"]


def test_extracts_with_plus91_and_spaces():
    out = extract_candidate_phones("+91 90632 27011")
    assert out == ["+91 90632 27011"]
    assert normalize_phone(out[0]) == "9063227011"


def test_extracts_from_whatsapp_style_line():
    text = "1. John Doe +91 90632 27011\n2. Jane +91 98765 43210"
    out = [normalize_phone(c) for c in extract_candidate_phones(text)]
    assert "9063227011" in out
    assert "9876543210" in out
    # The leading list markers ("1.", "2.") must NOT get concatenated into a number.
    assert "1" not in out and "2" not in out


def test_dates_are_not_matched_as_phones():
    text = "27/07/2026 18:18:07 Some Name +91 90632 27011"
    out = [normalize_phone(c) for c in extract_candidate_phones(text)]
    assert out.count("9063227011") == 1
    # No digit-run from the date/time survives as a plausible 10-digit phone.
    assert not any(c and c.startswith("2707202") for c in out)


def test_leading_zero_and_bare_number():
    out = [normalize_phone(c) for c in extract_candidate_phones("09811223344 and 9876543210")]
    assert "9811223344" in out
    assert "9876543210" in out


def test_no_numbers_returns_empty():
    assert extract_candidate_phones("no phone numbers here, just words") == []


def test_dedupes_repeated_candidates():
    out = extract_candidate_phones("9876543210 ... 9876543210 again")
    assert len(out) == 1
