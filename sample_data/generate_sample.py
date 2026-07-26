"""Generate sample_data/entries_sample.csv (deterministic).

Mirrors a Google Form -> Sheet export and deliberately embeds the messy cases
that exercise the ingestion pipeline:
  * duplicate phone numbers written in different formats
  * some numbers with +91, some with a leading 0
  * one row missing a phone number
  * a couple of rows with trailing whitespace

Run:  python sample_data/generate_sample.py
"""
from __future__ import annotations

import csv
import os

HEADERS = [
    "Timestamp",
    "Full Name",
    "College Branch",
    "Email",
    "Phone Number",
    "Played States or Nationals",
    "Applying For",
]

MEN_NAMES = [
    "Aarav Sharma", "Vivaan Gupta", "Aditya Nair", "Vihaan Reddy", "Arjun Mehta",
    "Sai Krishnan", "Reyansh Iyer", "Krishna Rao", "Ishaan Verma", "Rohan Das",
    "Kabir Chauhan", "Ayaan Khan", "Dhruv Patel", "Ansh Malhotra", "Yuvraj Singh",
    "Aryan Bose", "Kian Joseph", "Neel Kulkarni", "Advait Menon", "Rudra Pillai",
    "Shaurya Sinha", "Atharv Jain", "Om Bhat", "Parth Agarwal", "Laksh Chaudhary",
    "Veer Saxena", "Devansh Kapoor", "Aarush Ghosh", "Nakul Naidu", "Tejas Banerjee",
    "Harsh Vardhan", "Manav Trivedi", "Rishab Shetty", "Yash Deshmukh", "Karan Dubey",
]

WOMEN_NAMES = [
    "Aadhya Sharma", "Ananya Gupta", "Diya Nair", "Ira Reddy", "Myra Mehta",
    "Anika Krishnan", "Saanvi Iyer", "Kiara Rao", "Aarohi Verma", "Riya Das",
    "Navya Chauhan", "Prisha Khan", "Sara Patel", "Avni Malhotra", "Meera Singh",
    "Ishita Bose", "Zara Joseph", "Tara Kulkarni", "Kavya Menon", "Anvi Pillai",
    "Pari Sinha", "Nithya Jain", "Siya Bhat", "Riddhi Agarwal", "Aria Chaudhary",
    "Mahi Saxena", "Trisha Kapoor", "Niharika Ghosh",
]

BRANCHES = [
    "Computer Science", "Mechanical", "Electronics", "Civil", "Electrical",
    "Information Tech", "Chemical", "Biotech", "Aerospace", "Metallurgy",
]


def phone(i: int) -> str:
    # Base 10-digit number, unique per index.
    return f"9{800000000 + i * 137 % 199999999:09d}"[:10]


def main() -> None:
    rows: list[list[str]] = []
    ts = 1  # a simple increasing "timestamp" so dedup tie-breaks are testable

    def add(name, branch, email, ph, level, team):
        nonlocal ts
        stamp = f"2026/07/{(ts % 27) + 1:02d} 10:{ts % 60:02d}:00"
        rows.append([stamp, name, branch, email, ph, level, team])
        ts += 1

    levels = ["None", "States", "Nationals", "Both"]

    # ---- Men ----
    for i, name in enumerate(MEN_NAMES):
        branch = BRANCHES[i % len(BRANCHES)]
        email = name.lower().replace(" ", ".") + "@college.edu"
        add(name, branch, email, phone(i), levels[i % 4], "Men's Team")

    # ---- Women ----
    for i, name in enumerate(WOMEN_NAMES):
        branch = BRANCHES[i % len(BRANCHES)]
        email = name.lower().replace(" ", ".") + "@college.edu"
        add(name, branch, email, phone(100 + i), levels[i % 4], "Women's Team")

    # ---- Deliberate messy cases (appended so they collide with earlier rows) ----
    # Same person as men[0], phone with +91 -> duplicate, later timestamp (dropped).
    add(MEN_NAMES[0], BRANCHES[0], "dupe1@college.edu", "+91 " + phone(0), "States", "Men's Team")
    # Same as men[1], phone with leading 0 -> duplicate.
    add(MEN_NAMES[1], BRANCHES[1], "dupe2@college.edu", "0" + phone(1), "None", "Men's Team")
    # Same as women[0], phone with spaces/hyphens -> duplicate.
    add(WOMEN_NAMES[0], BRANCHES[0], "dupe3@college.edu",
        f"{phone(100)[:5]}-{phone(100)[5:]}", "Both", "Women's Team")
    # Trailing whitespace everywhere (new valid man).
    add("Rahul Nanda  ", "  Computer Science ", " rahul.nanda@college.edu ",
        "  " + phone(60) + " ", " States ", " Men's Team ")
    # Trailing whitespace (new valid woman).
    add("Sneha Rao  ", "Civil ", "sneha.rao@college.edu ", phone(160) + "  ",
        "Nationals", "Women's Team ")
    # Missing phone -> skipped.
    add("No Phone Guy", "Mechanical", "nophone@college.edu", "", "None", "Men's Team")
    # Unrecognized "Applying For" -> skipped.
    add("Confused Entry", "Civil", "confused@college.edu", phone(70), "None", "Mixed Doubles")
    # Missing name -> skipped.
    add("", "Electrical", "noname@college.edu", phone(80), "States", "Men's Team")

    out_path = os.path.join(os.path.dirname(__file__), "entries_sample.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADERS)
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    main()
