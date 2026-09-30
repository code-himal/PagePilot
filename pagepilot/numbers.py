"""Conservative number detection for Excel export.

The goal is to turn "1,200.50" into a real number so accountants can sum it, while
NEVER damaging values that only *look* numeric: phone numbers, IDs with leading zeros,
long account numbers, dates, percentages, ranges...
"""
import re
from typing import Optional, Tuple

_CURRENCY = {"$": '"$"#,##0', "€": '"€"#,##0', "£": '"£"#,##0', "¥": '"¥"#,##0', "₹": '"₹"#,##0'}

# 1234  1234.56  1,234  1,234.56   (no leading zeros, except a lone 0 / 0.xx)
_PLAIN = r"(?:0|[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d*)(?:\.\d+)?|0?\.\d+"
_NUM_RE = re.compile(rf"^(?P<neg>-)?(?P<cur>[$€£¥₹])?\s?(?P<num>{_PLAIN})$")
_PAREN_RE = re.compile(rf"^\((?P<cur>[$€£¥₹])?\s?(?P<num>{_PLAIN})\)$")


def parse_number(text: str) -> Optional[Tuple[float, Optional[str]]]:
    """Return (value, excel_number_format) if text is unambiguously a number, else None."""
    if not isinstance(text, str):
        return None
    s = text.strip()
    if not s or len(s) > 24:
        return None

    neg = False
    m = _NUM_RE.match(s)
    if m:
        neg = bool(m.group("neg"))
    else:
        m = _PAREN_RE.match(s)          # accounting negative: (1,200.00)
        if not m:
            return None
        neg = True

    num = m.group("num")
    digits = re.sub(r"\D", "", num)
    if len(digits.lstrip("0")) > 15:     # Excel keeps only 15 significant digits
        return None

    value = float(num.replace(",", ""))
    if neg:
        value = -value

    decimals = len(num.split(".")[1]) if "." in num else 0
    has_commas = "," in num
    cur = m.group("cur")

    # Long bare digit strings are identifiers (phone / account / ID numbers), not amounts.
    # Excel would also display 12+ digit numbers in scientific notation, so keep them as text.
    if not has_commas and not decimals and not cur and len(digits) >= 10:
        return None

    if cur:
        fmt = _CURRENCY[cur]
        if decimals:
            fmt += "." + "0" * decimals
    elif has_commas:
        fmt = "#,##0" + ("." + "0" * decimals if decimals else "")
    elif decimals:
        fmt = "0." + "0" * decimals
    else:
        fmt = None

    if decimals == 0 and abs(value) < 2**53:
        return int(value), fmt
    return value, fmt
