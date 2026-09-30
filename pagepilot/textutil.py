"""Small text helpers shared by the exporters and the layout engine."""
import re

# Characters that are illegal in XML 1.0 (and therefore in DOCX / XLSX).
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff\ud800-\udfff]")


def clean_text(value) -> str:
    """Return a string that is always safe to put into an XML-based file."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return _ILLEGAL_XML.sub("", value)


def safe_filename(name: str, default: str = "document") -> str:
    """Base name (without extension) that is safe to use in a download header."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name)          # drop extension
    name = clean_text(name)
    name = re.sub(r"[^\w\-. ()\u0900-\u097F]+", "_", name, flags=re.UNICODE)
    name = re.sub(r"\s+", " ", name).strip(" ._")
    return (name[:80] or default)
