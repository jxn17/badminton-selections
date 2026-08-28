"""CSV ingestion tests for the Trials form format."""
from __future__ import annotations

import os

import pytest

from app.csv_import import classify_gender, import_csv, normalize_phone, parse_and_dedup
from app.models import Category, Player

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "..", "sample_data", "entries_sample.csv")
HEADER = "Timestamp,Name,Gender,Phone Number,Registration Number,Year of Study (4th years not allowed),Level of Exprience"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("9812345678", "9812345678"),
        ("+91 9812345678", "9812345678"),
        ("09812345678", "9812345678"),
        ("91-98123-45678", "9812345678"),
        ("  9812345678  ", "9812345678"),
        ("+919515422428", "9515422428"),
        ("12345", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_classify_gender():
    assert classify_gender("Male") == Category.men
    assert classify_gender("female") == Category.women
    assert classify_gender(" FEMALE ") == Category.women
    assert classify_gender("Other") is None


def _csv(*rows: str) -> str:
    return HEADER + "\n" + "\n".join(rows) + "\n"


def test_dedup_same_phone_different_formats():
    content = _csv(
        "27/07/2026 10:00:00,Alice,Female,9800000000,261090050001,1st Year,School",
        "28/07/2026 10:00:00,Alice Dup,Female,+91 9800000000,261090050001,1st Year,Casual",
        "29/07/2026 10:00:00,Alice Dup2,Female,09800000000,261090050001,1st Year,School",
    )
    rows, report = parse_and_dedup(content)
    assert len(rows) == 1
    assert report.duplicates_dropped == 2
    assert rows[0].full_name == "Alice"  # earliest timestamp kept


def test_same_phone_across_gender_kept_separately():
    content = _csv(
        "27/07/2026 10:00:00,Bob,Male,9811111111,261090050002,1st Year,School",
        "27/07/2026 10:00:00,Bobbie,Female,9811111111,261090050003,1st Year,School",
    )
    rows, report = parse_and_dedup(content)
    assert len(rows) == 2
    assert report.duplicates_dropped == 0


def test_short_phone_kept_via_registration_fallback():
    # A too-short phone is not dropped; the registration number keys the entry.
    content = _csv(
        "27/07/2026 10:00:00,No Phone,Male,,261090050099,1st Year,School",
    )
    rows, report = parse_and_dedup(content)
    assert len(rows) == 1
    assert rows[0].dedup_key.startswith("reg:")
    assert report.skipped_invalid == 0


def test_bad_gender_and_missing_name_skipped():
    content = _csv(
        "27/07/2026 10:00:00,,Male,9822222222,261090050004,1st Year,School",  # missing name
        "27/07/2026 10:00:00,Weird,Other,9833333333,261090050005,1st Year,School",  # bad gender
        "27/07/2026 10:00:00,Good,Male,9844444444,261090050006,1st Year,School",
    )
    rows, report = parse_and_dedup(content)
    assert len(rows) == 1
    assert report.skipped_invalid == 2


def test_whitespace_trimmed():
    content = _csv(
        "27/07/2026 10:00:00, Spacey Name  , Male ,  9855555555 , 261090050007 , 1st Year , School ",
    )
    rows, _ = parse_and_dedup(content)
    assert rows[0].full_name == "Spacey Name"
    assert rows[0].category == Category.men
    assert rows[0].phone_normalized == "9855555555"


def test_import_idempotent(db):
    with open(SAMPLE, encoding="utf-8") as f:
        content = f.read()
    r1 = import_csv(db, content)
    c1 = db.query(Player).count()
    r2 = import_csv(db, content)
    c2 = db.query(Player).count()
    assert c1 == c2
    assert r1.imported == r2.imported == c1


def test_sample_shape(db):
    with open(SAMPLE, encoding="utf-8") as f:
        report = import_csv(db, f.read())
    # 35 men + the whitespace man + the missing-phone man = 37; 20 women.
    assert report.per_category_counts["men"] == 37
    assert report.per_category_counts["women"] == 20
    assert report.duplicates_dropped == 3
    assert report.skipped_invalid == 1  # the 'Other' gender row


def test_headerless_google_form_export():
    """Women's sheet export sometimes omits the header row."""
    content = "17/08/2026 20:28:47,Manogna Bathula ,Female,8919462837,261090052658,1st Year,Casual\n"
    rows, report = parse_and_dedup(content)
    assert report.skipped_invalid == 0
    assert len(rows) == 1
    assert rows[0].full_name == "Manogna Bathula"
    assert rows[0].category == Category.women
    assert rows[0].phone_normalized == "8919462837"


def test_blank_lines_split_mens_csv_into_groups(db):
    content = _csv(
        "27/07/2026 10:00:00,Arjun,Male,9800000001,261090050001,1st Year,School",
        "27/07/2026 10:01:00,Bharat,Male,9800000002,261090050002,1st Year,School",
        "",
        "27/07/2026 10:02:00,Chirag,Male,9800000003,261090050003,1st Year,School",
        "27/07/2026 10:03:00,Dev,Male,9800000004,261090050004,1st Year,School",
        "",
        "27/07/2026 10:04:00,Esha,Female,9800000005,261090050005,1st Year,School",
    )

    rows, report = parse_and_dedup(content)
    men_groups = {r.full_name: r.group_label for r in rows if r.category == Category.men}

    assert men_groups == {"Arjun": "A", "Bharat": "A", "Chirag": "B", "Dev": "B"}
    assert report.explicit_men_groups == {"A": 2, "B": 2}

    import_csv(db, content)
    stored = {
        p.full_name: p.group_label
        for p in db.query(Player).filter(Player.category == Category.men).all()
    }
    assert stored == men_groups


def test_category_override_imports_men_without_gender_column(db):
    content = (
        "Timestamp,Name,Phone Number,Registration Number,Year of Study,Level of Experience\n"
        "27/07/2026 10:00:00,Arjun,9800000001,261090050001,1st Year,School\n"
        "27/07/2026 10:01:00,Bharat,9800000002,261090050002,1st Year,School\n"
        "\n"
        "27/07/2026 10:02:00,Chirag,9800000003,261090050003,1st Year,School\n"
        "27/07/2026 10:03:00,Dev,9800000004,261090050004,1st Year,School\n"
    )

    rows, report = parse_and_dedup(content, Category.men)
    assert report.skipped_invalid == 0
    assert report.explicit_men_groups == {"A": 2, "B": 2}
    assert {r.full_name: r.category for r in rows} == {
        "Arjun": Category.men,
        "Bharat": Category.men,
        "Chirag": Category.men,
        "Dev": Category.men,
    }

    import_csv(db, content, Category.men)
    assert db.query(Player).filter(Player.category == Category.men).count() == 4


def test_category_override_imports_women_without_gender_column():
    content = (
        "Timestamp,Name,Phone Number,Registration Number,Year of Study,Level of Experience\n"
        "27/07/2026 10:00:00,Asha,9800000001,261090050001,1st Year,School\n"
        "27/07/2026 10:01:00,Diya,9800000002,261090050002,1st Year,School\n"
    )

    rows, report = parse_and_dedup(content, Category.women)
    assert report.skipped_invalid == 0
    assert report.explicit_men_groups == {}
    assert {r.full_name: r.category for r in rows} == {
        "Asha": Category.women,
        "Diya": Category.women,
    }
