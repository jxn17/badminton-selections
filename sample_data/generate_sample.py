"""Generate sample_data/entries_sample.csv (deterministic, FAKE data).

Mirrors the Trials Google Form export and embeds the messy cases the pipeline
must survive: duplicate form-fills (same phone, different formats), +91 / leading
0 numbers, a missing phone (kept via reg-number fallback), an unrecognized
gender (skipped), and trailing whitespace.

The REAL entries file is never committed (it contains students' phone numbers);
this fake sample is what the tests and demo use.

Run:  python sample_data/generate_sample.py
"""
from __future__ import annotations

import csv
import os

HEADERS = [
    "Timestamp",
    "Name",
    "Gender",
    "Phone Number",
    "Registration Number",
    "Year of Study (4th years not allowed)",
    "Level of Exprience",  # matches the form's real (misspelled) header
]

MEN = [
    "Aarav Sharma", "Vivaan Gupta", "Aditya Nair", "Vihaan Reddy", "Arjun Mehta",
    "Sai Krishnan", "Reyansh Iyer", "Krishna Rao", "Ishaan Verma", "Rohan Das",
    "Kabir Chauhan", "Ayaan Khan", "Dhruv Patel", "Ansh Malhotra", "Yuvraj Singh",
    "Aryan Bose", "Kian Joseph", "Neel Kulkarni", "Advait Menon", "Rudra Pillai",
    "Shaurya Sinha", "Atharv Jain", "Om Bhat", "Parth Agarwal", "Laksh Chaudhary",
    "Veer Saxena", "Devansh Kapoor", "Aarush Ghosh", "Nakul Naidu", "Tejas Banerjee",
    "Harsh Vardhan", "Manav Trivedi", "Rishab Shetty", "Yash Deshmukh", "Karan Dubey",
]
WOMEN = [
    "Aadhya Sharma", "Ananya Gupta", "Diya Nair", "Ira Reddy", "Myra Mehta",
    "Anika Krishnan", "Saanvi Iyer", "Kiara Rao", "Aarohi Verma", "Riya Das",
    "Navya Chauhan", "Prisha Khan", "Sara Patel", "Avni Malhotra", "Meera Singh",
    "Ishita Bose", "Zara Joseph", "Tara Kulkarni", "Kavya Menon", "Anvi Pillai",
]
LEVELS = [
    "Nationals or States", "District or Local Tournaments", "School",
    "Casual", "No experience or Beginner",
]
YEARS = ["1st Year", "2nd Year", "3rd Year"]


def phone(i: int) -> str:
    return f"9{800000000 + i * 137 % 199999999:09d}"[:10]


def reg(i: int) -> str:
    return f"2610900{50000 + i:05d}"


def main() -> None:
    rows: list[list[str]] = []
    ts = 1

    def add(name, gender, ph, r, year, level):
        nonlocal ts
        stamp = f"{(ts % 27) + 1:02d}/08/2026 10:{ts % 60:02d}:00"
        rows.append([stamp, name, gender, ph, r, year, level])
        ts += 1

    for i, name in enumerate(MEN):
        add(name, "Male", phone(i), reg(i), YEARS[i % 3], LEVELS[i % len(LEVELS)])
    for i, name in enumerate(WOMEN):
        add(name, "Female", phone(100 + i), reg(100 + i), YEARS[i % 3], LEVELS[i % len(LEVELS)])

    # ---- Messy cases ----
    add(MEN[0], "Male", "+91 " + phone(0), reg(0), "1st Year", LEVELS[2])  # dup of men[0]
    add(MEN[1], "Male", "0" + phone(1), reg(1), "1st Year", LEVELS[0])      # dup of men[1]
    add(WOMEN[0], "Female", f"{phone(100)[:5]}-{phone(100)[5:]}", reg(100), "1st Year", LEVELS[1])  # dup
    add("Rahul Nanda  ", " Male ", "  " + phone(60) + " ", reg(60), " 1st Year ", " Casual ")  # whitespace, new
    add("No Phone Guy", "Male", "", reg(70), "1st Year", "School")  # missing phone -> reg fallback keeps
    add("Confused Entry", "Other", phone(80), reg(80), "1st Year", "Casual")  # bad gender -> skipped

    out = os.path.join(os.path.dirname(__file__), "entries_sample.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADERS)
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
