"""CSV ingestion: parse -> validate -> normalize -> dedup -> idempotent upsert.

Re-importing the same file changes nothing (upsert keyed on normalized phone,
scoped per category). Every bad row is collected into a report rather than
crashing the import.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .models import Category, Player

# ---- Header matching -------------------------------------------------------
# We match on header *names* (case/space tolerant), not column index, so extra
# columns or reordering in the Google Sheet export won't break the parser.
HEADER_ALIASES: dict[str, list[str]] = {
    "timestamp": ["timestamp"],
    "full_name": ["full name", "name"],
    "college_branch": ["college branch", "college / branch", "branch", "college"],
    "email": ["email", "email address", "e-mail"],
    "phone": ["phone number", "phone", "mobile", "mobile number"],
    "states_nationals": ["played states or nationals", "states or nationals", "level"],
    "applying_for": ["applying for", "team", "category"],
}

_APPLYING_MEN = {"men's team", "mens team", "men", "male", "boys"}
_APPLYING_WOMEN = {"women's team", "womens team", "women", "female", "girls"}


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower())


def _build_header_map(fieldnames: list[str]) -> dict[str, str]:
    """Map our canonical keys -> the actual header string present in the file."""
    normalized = {_norm_header(h): h for h in fieldnames if h is not None}
    mapping: dict[str, str] = {}
    for key, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[key] = normalized[alias]
                break
    return mapping


def normalize_phone(raw: str) -> str | None:
    """Canonical dedup key: digits only, drop +91 / 91 / leading 0, last 10 digits.

    Returns None if fewer than 10 digits remain (treated as missing/invalid).
    """
    if raw is None:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    # Strip common India country-code / trunk prefixes.
    if digits.startswith("91") and len(digits) > 10:
        digits = digits[2:]
    digits = digits.lstrip("0")
    if len(digits) < 10:
        return None
    return digits[-10:]


def classify_category(applying_for: str) -> Category | None:
    v = _norm_header(applying_for)
    if v in _APPLYING_MEN:
        return Category.men
    if v in _APPLYING_WOMEN:
        return Category.women
    return None


@dataclass
class SkippedRow:
    row_number: int
    reason: str
    raw: dict


@dataclass
class DroppedDuplicate:
    row_number: int
    kept_row_number: int
    phone_normalized: str
    category: str
    name: str


@dataclass
class ImportReport:
    imported: int = 0
    duplicates_dropped: int = 0
    skipped_invalid: int = 0
    per_category_counts: dict[str, int] = field(default_factory=lambda: {"men": 0, "women": 0})
    skipped: list[SkippedRow] = field(default_factory=list)
    dropped_duplicates: list[DroppedDuplicate] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "imported": self.imported,
            "duplicates_dropped": self.duplicates_dropped,
            "skipped_invalid": self.skipped_invalid,
            "per_category_counts": self.per_category_counts,
            "skipped": [
                {"row_number": s.row_number, "reason": s.reason, "raw": s.raw}
                for s in self.skipped
            ],
            "dropped_duplicates": [
                {
                    "row_number": d.row_number,
                    "kept_row_number": d.kept_row_number,
                    "phone_normalized": d.phone_normalized,
                    "category": d.category,
                    "name": d.name,
                }
                for d in self.dropped_duplicates
            ],
        }


@dataclass
class _ParsedRow:
    row_number: int
    full_name: str
    college_branch: str
    email: str
    phone_raw: str
    phone_normalized: str
    states_nationals: str
    category: Category
    timestamp: str


def parse_and_dedup(content: str) -> tuple[list[_ParsedRow], ImportReport]:
    """Pure function: parse + validate + dedup. No DB access, so it is unit-testable.

    Dedup keeps the earliest Timestamp on collision (falls back to earliest row
    order when timestamps are missing/unparseable), scoped per (category, phone).
    """
    report = ImportReport()
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return [], report
    hmap = _build_header_map(reader.fieldnames)

    def cell(row: dict, key: str) -> str:
        col = hmap.get(key)
        if col is None:
            return ""
        return (row.get(col) or "").strip()

    accepted: dict[tuple[str, str], _ParsedRow] = {}

    # Header row is line 1; DictReader's first data row is spreadsheet row 2.
    for idx, row in enumerate(reader, start=2):
        raw_snapshot = {k: (v or "").strip() for k, v in row.items() if k}
        name = cell(row, "full_name")
        phone_raw = cell(row, "phone")
        applying = cell(row, "applying_for")

        if not name:
            report.skipped.append(SkippedRow(idx, "missing name", raw_snapshot))
            continue
        category = classify_category(applying)
        if category is None:
            report.skipped.append(
                SkippedRow(idx, f"unrecognized Applying For: {applying!r}", raw_snapshot)
            )
            continue
        phone_norm = normalize_phone(phone_raw)
        if phone_norm is None:
            report.skipped.append(SkippedRow(idx, "missing/invalid phone", raw_snapshot))
            continue

        parsed = _ParsedRow(
            row_number=idx,
            full_name=name,
            college_branch=cell(row, "college_branch"),
            email=cell(row, "email"),
            phone_raw=phone_raw,
            phone_normalized=phone_norm,
            states_nationals=cell(row, "states_nationals"),
            category=category,
            timestamp=cell(row, "timestamp"),
        )

        key = (category.value, phone_norm)
        existing = accepted.get(key)
        if existing is None:
            accepted[key] = parsed
            continue

        # Collision: keep the earliest timestamp (string compare works for ISO
        # and Google's "YYYY/MM/DD HH:MM:SS"; on ties keep the earlier row).
        keep, drop = _pick_earliest(existing, parsed)
        accepted[key] = keep
        report.dropped_duplicates.append(
            DroppedDuplicate(
                row_number=drop.row_number,
                kept_row_number=keep.row_number,
                phone_normalized=phone_norm,
                category=category.value,
                name=drop.full_name,
            )
        )

    report.skipped_invalid = len(report.skipped)
    report.duplicates_dropped = len(report.dropped_duplicates)
    return list(accepted.values()), report


def _pick_earliest(a: _ParsedRow, b: _ParsedRow) -> tuple[_ParsedRow, _ParsedRow]:
    """Return (keep, drop) preferring the earliest timestamp, then earliest row."""
    ta, tb = a.timestamp or "", b.timestamp or ""
    if ta and tb and ta != tb:
        return (a, b) if ta < tb else (b, a)
    # Missing/equal timestamps: earliest row number wins.
    return (a, b) if a.row_number <= b.row_number else (b, a)


def import_csv(db: Session, content: str) -> ImportReport:
    """Full pipeline against the DB. Idempotent: upsert keyed on (category, phone)."""
    parsed_rows, report = parse_and_dedup(content)

    for pr in parsed_rows:
        existing = (
            db.query(Player)
            .filter(
                Player.phone_normalized == pr.phone_normalized,
                Player.category == pr.category,
            )
            .one_or_none()
        )
        if existing is None:
            db.add(
                Player(
                    full_name=pr.full_name,
                    college_branch=pr.college_branch or None,
                    email=pr.email or None,
                    phone_raw=pr.phone_raw,
                    phone_normalized=pr.phone_normalized,
                    states_nationals=pr.states_nationals or None,
                    category=pr.category,
                    entry_timestamp=pr.timestamp or None,
                )
            )
        else:
            # Idempotent refresh of mutable fields; the identity key is unchanged.
            existing.full_name = pr.full_name
            existing.college_branch = pr.college_branch or None
            existing.email = pr.email or None
            existing.phone_raw = pr.phone_raw
            existing.states_nationals = pr.states_nationals or None
            existing.entry_timestamp = pr.timestamp or None
        report.per_category_counts[pr.category.value] += 1

    report.imported = len(parsed_rows)
    db.commit()
    return report
