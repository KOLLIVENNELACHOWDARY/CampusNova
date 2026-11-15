"""Input checks for complaint text, shared by the Streamlit form and the API."""
import re
from typing import Optional

MIN_CHARS = 10
MAX_CHARS = 2000


def validate_complaint(title: str, description: str = "") -> Optional[str]:
    """Return a human-readable error, or None when the text is acceptable."""
    text = f"{title or ''} {description or ''}".strip()
    if not text:
        return "Please describe the problem."
    if len(text) > MAX_CHARS:
        return f"The complaint is too long ({len(text)} characters). Please keep it under {MAX_CHARS}."
    compact = text.replace(" ", "")
    letters = sum(c.isalpha() for c in compact)
    if letters == 0 or letters / len(compact) < 0.5:
        return "The complaint is mostly numbers or symbols. Please describe the problem in words."
    if re.search(r"(.)\1{7,}", text):
        return "The text looks like random characters. Please describe the problem in words."
    if len(text) < MIN_CHARS or len(text.split()) < 2:
        return "Please add a little more detail, for example what is wrong and where."
    return None
