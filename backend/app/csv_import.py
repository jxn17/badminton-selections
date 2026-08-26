"""CSV ingestion for the Trials form: parse -> validate -> dedup -> upsert.

Form columns: Timestamp, Name, Gender, Phone Number, Registration Number,
Year of Study, Level of Experience. Category comes from Gender. Idempotent:
re-importing the same file changes nothing.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .models import Category, Player

# Header matching is name-based (case/space/typo tolerant), not positional.
HEADER_ALIASES: dict[str, list[str]] = {
    "timestamp": ["timestamp"],
    "name": ["name", "full name"],
    "gender": ["gender", "sex"],
    "phone": ["phone number", "phone", "mobile", "mobile number", "contact"],
    "registration": ["registration number", "registration no", "reg no", "reg number", "registration"],
    "year": ["year of study (4th years not allowed)", "year of study", "year"],
    # note the form's real header misspells "Experience" as "Exprience"
    "experience": ["level of exprience", "level of experience", "experience", "level"],
}


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower())


def _build_header_map(fieldnames: list[str]) -> dict[str, str]:
    normalized = {_norm_header(h): h for h in fieldnames if h is not None}
    mapping: dict[str, str] = {}
    for key, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[key] = normalized[alias]
                break
    return mapping


def normalize_phone(raw: str | None) -> str | None:
    """Digits only, drop +91/91/leading 0, keep last 10. None if <10 remain."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if digits.startswith("91") and len(digits) > 10:
        digits = digits[2:]
    digits = digits.lstrip("0")
    if len(digits) < 10:
        return None
    return digits[-10:]


def classify_gender(value: str) -> Category | None:
    v = _norm_header(value)
    if v in {"male", "m", "boy", "men", "man"}:
        return Category.men
    if v in {"female", "f", "girl", "women", "woman"}:
        return Category.women
    return None


def dedup_key_for(phone_norm: str | None, registration: str, name: str) -> str:
    """Stable identity: phone if valid, else reg number digits, else lowercased name."""
    if phone_norm:
        return f"ph:{phone_norm}"
    reg = re.sub(r"\D", "", registration or "")
    if len(reg) >= 6:
        return f"reg:{reg}"
    return f"nm:{_norm_header(name)}"


@dataclass
class SkippedRow:
    row_number: int
    reason: str
    raw: dict


@dataclass
class DroppedDuplicate:
    row_number: int
    kept_row_number: int
    key: str
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
                {"row_number": s.row_number, "reason": s.reason, "raw": s.raw} for s in self.skipped
            ],
            "dropped_duplicates": [
                {
                    "row_number": d.row_number,
                    "kept_row_number": d.kept_row_number,
                    "key": d.key,
                    "category": d.category,
                    "name": d.name,
                }
                for d in self.dropped_duplicates
            ],
        }


@dataclass
class ParsedRow:
    row_number: int
    full_name: str
    phone_raw: str
    phone_normalized: str | None
    dedup_key: str
    registration_number: str
    year_of_study: str
    experience_level: str
    category: Category
    timestamp: str


def parse_and_dedup(content: str) -> tuple[list[ParsedRow], ImportReport]:
    report = ImportReport()
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return [], report
    hmap = _build_header_map(reader.fieldnames)

    def cell(row: dict, key: str) -> str:
        col = hmap.get(key)
        return (row.get(col) or "").strip() if col else ""

    accepted: dict[tuple[str, str], ParsedRow] = {}

    for idx, row in enumerate(reader, start=2):
        snapshot = {k: (v or "").strip() for k, v in row.items() if k}
        name = cell(row, "name")
        gender = cell(row, "gender")
        phone_raw = cell(row, "phone")

        if not name:
            report.skipped.append(SkippedRow(idx, "missing name", snapshot))
            continue
        category = classify_gender(gender)
        if category is None:
            report.skipped.append(SkippedRow(idx, f"unrecognized gender: {gender!r}", snapshot))
            continue

        phone_norm = normalize_phone(phone_raw)
        registration = cell(row, "registration")
        key = dedup_key_for(phone_norm, registration, name)

        parsed = ParsedRow(
            row_number=idx,
            full_name=re.sub(r"\s+", " ", name).strip(),
            phone_raw=phone_raw,
            phone_normalized=phone_norm,
            dedup_key=key,
            registration_number=registration,
            year_of_study=cell(row, "year"),
            experience_level=cell(row, "experience"),
            category=category,
            timestamp=cell(row, "timestamp"),
        )

        ck = (category.value, key)
        existing = accepted.get(ck)
        if existing is None:
            accepted[ck] = parsed
            continue
        keep, drop = _pick_earliest(existing, parsed)
        accepted[ck] = keep
        report.dropped_duplicates.append(
            DroppedDuplicate(drop.row_number, keep.row_number, key, category.value, drop.full_name)
        )

    report.skipped_invalid = len(report.skipped)
    report.duplicates_dropped = len(report.dropped_duplicates)
    return list(accepted.values()), report


def _pick_earliest(a: ParsedRow, b: ParsedRow) -> tuple[ParsedRow, ParsedRow]:
    ta, tb = _ts(a.timestamp), _ts(b.timestamp)
    if ta and tb and ta != tb:
        return (a, b) if ta < tb else (b, a)
    return (a, b) if a.row_number <= b.row_number else (b, a)


def _ts(s: str) -> tuple | None:
    """Parse 'DD/MM/YYYY HH:MM:SS' into a sortable tuple; None if unparseable."""
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2}):(\d{2})", s or "")
    if not m:
        return None
    d, mo, y, h, mi, se = (int(x) for x in m.groups())
    return (y, mo, d, h, mi, se)


def import_csv(db: Session, content: str) -> ImportReport:
    """Full pipeline. Idempotent upsert keyed on (category, dedup_key).

    Existing group assignments and walk-in flags are preserved on re-import.
    """
    parsed_rows, report = parse_and_dedup(content)

    for pr in parsed_rows:
        existing = (
            db.query(Player)
            .filter(Player.dedup_key == pr.dedup_key, Player.category == pr.category)
            .one_or_none()
        )
        if existing is None:
            db.add(
                Player(
                    full_name=pr.full_name,
                    phone_raw=pr.phone_raw or None,
                    phone_normalized=pr.phone_normalized,
                    dedup_key=pr.dedup_key,
                    registration_number=pr.registration_number or None,
                    year_of_study=pr.year_of_study or None,
                    experience_level=pr.experience_level or None,
                    category=pr.category,
                    entry_timestamp=pr.timestamp or None,
                )
            )
        else:
            existing.full_name = pr.full_name
            existing.phone_raw = pr.phone_raw or None
            existing.phone_normalized = pr.phone_normalized
            existing.registration_number = pr.registration_number or None
            existing.year_of_study = pr.year_of_study or None
            existing.experience_level = pr.experience_level or None
            existing.entry_timestamp = pr.timestamp or None
        report.per_category_counts[pr.category.value] += 1

    report.imported = len(parsed_rows)
    db.commit()
    return report
