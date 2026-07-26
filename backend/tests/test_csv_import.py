"""CSV ingestion tests: normalization, dedup, validation, idempotency."""
from __future__ import annotations

import os

import pytest

from app.csv_import import classify_category, import_csv, normalize_phone, parse_and_dedup
from app.models import Category, Player

SAMPLE = os.path.join(
    os.path.dirname(__file__), "..", "..", "sample_data", "entries_sample.csv"
)

HEADER = "Timestamp,Full Name,College Branch,Email,Phone Number,Played States or Nationals,Applying For"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("9812345678", "9812345678"),
        ("+91 9812345678", "9812345678"),
        ("09812345678", "9812345678"),
        ("91-98123-45678", "9812345678"),
        ("  9812345678  ", "9812345678"),
        ("(981) 234-5678", "9812345678"),
        ("12345", None),  # too short
        ("", None),
        (None, None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_classify_category():
    assert classify_category("Men's Team") == Category.men
    assert classify_category("women's team") == Category.women
    assert classify_category(" WOMEN ") == Category.women
    assert classify_category("Mixed Doubles") is None


def _csv(*rows: str) -> str:
    return HEADER + "\n" + "\n".join(rows) + "\n"


def test_dedup_across_formats():
    content = _csv(
        "2026/07/01 10:00:00,Alice,CS,a@x.edu,9800000000,None,Men's Team",
        "2026/07/02 10:00:00,Alice Dup,CS,a2@x.edu,+91 9800000000,States,Men's Team",
        "2026/07/03 10:00:00,Alice Dup2,CS,a3@x.edu,09800000000,Both,Men's Team",
    )
    rows, report = parse_and_dedup(content)
    assert len(rows) == 1
    assert report.duplicates_dropped == 2
    # Earliest timestamp kept.
    assert rows[0].full_name == "Alice"


def test_same_phone_different_category_kept_separately():
    content = _csv(
        "2026/07/01 10:00:00,Bob,CS,b@x.edu,9811111111,None,Men's Team",
        "2026/07/01 10:00:00,Bobbie,CS,b2@x.edu,9811111111,None,Women's Team",
    )
    rows, report = parse_and_dedup(content)
    assert len(rows) == 2
    assert report.duplicates_dropped == 0


def test_validation_skips():
    content = _csv(
        "2026/07/01 10:00:00,,CS,noname@x.edu,9855555555,None,Men's Team",  # missing name
        "2026/07/01 10:00:00,No Phone,CS,np@x.edu,,None,Men's Team",  # no phone
        "2026/07/01 10:00:00,Confused,CS,c@x.edu,9822222222,None,Mixed",  # bad category
        "2026/07/01 10:00:00,Good,CS,g@x.edu,9833333333,None,Women's Team",
    )
    rows, report = parse_and_dedup(content)
    assert len(rows) == 1
    assert report.skipped_invalid == 3
    reasons = " ".join(s.reason for s in report.skipped)
    assert "phone" in reasons and "name" in reasons and "Applying For" in reasons


def test_whitespace_trimmed():
    content = _csv(
        "2026/07/01 10:00:00, Spacey Name  ,  CS ,  s@x.edu ,  9844444444  , States , Men's Team ",
    )
    rows, _ = parse_and_dedup(content)
    assert len(rows) == 1
    assert rows[0].full_name == "Spacey Name"
    assert rows[0].category == Category.men
    assert rows[0].phone_normalized == "9844444444"


def test_import_is_idempotent(db):
    with open(SAMPLE, encoding="utf-8") as f:
        content = f.read()

    r1 = import_csv(db, content)
    count1 = db.query(Player).count()
    r2 = import_csv(db, content)
    count2 = db.query(Player).count()

    assert count1 == count2  # re-import changes nothing
    assert r1.imported == r2.imported
    assert count1 == r1.imported


def test_sample_has_expected_shape(db):
    with open(SAMPLE, encoding="utf-8") as f:
        report = import_csv(db, f.read())
    # 35 men + 28 women unique, plus the two whitespace-only new entrants (1 M, 1 W).
    assert report.per_category_counts["men"] == 36
    assert report.per_category_counts["women"] == 29
    assert report.duplicates_dropped == 3
    assert report.skipped_invalid == 3
