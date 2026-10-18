"""Read entity names from the bundled OWID source for explicit-scope checks."""
import csv
import re
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "electricity_mix.csv"


def entity_mentions(question):
    """Find exact, case-insensitive entity names explicitly present in a question."""
    if not DATA_PATH.is_file():
        return []
    with DATA_PATH.open(newline="", encoding="utf-8") as source:
        names = sorted({row["entity"] for row in csv.DictReader(source)}, key=len, reverse=True)
    text = question.casefold()
    return [name for name in names if re.search(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", text)]
