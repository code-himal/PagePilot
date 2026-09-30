"""Entry point.  Development:  python app.py     Production:  gunicorn 'app:app'  (see README)."""
import os
import shutil
from pathlib import Path


def _ensure_toolchain() -> None:
    """Make Tesseract/Poppler discoverable on Windows when installed via winget."""
    if os.name != "nt":
        return

    tess = os.getenv("TESSERACT_CMD") or shutil.which("tesseract") or shutil.which("tesseract.exe")
    if not tess:
        for candidate in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ):
            if os.path.exists(candidate):
                tess = candidate
                break
    if tess:
        os.environ["TESSERACT_CMD"] = tess
        os.environ["PATH"] = os.pathsep.join([str(Path(tess).parent), *[p for p in os.environ.get("PATH", "").split(os.pathsep) if p]])

    poppler_bin = shutil.which("pdftoppm") or shutil.which("pdftoppm.exe")
    if not poppler_bin:
        for base in (
            Path(r"C:\Users\acer\AppData\Local\Microsoft\WinGet\Packages"),
            Path(r"C:\Program Files"),
            Path(r"C:\Program Files (x86)"),
        ):
            if not base.exists():
                continue
            for match in base.rglob("pdftoppm.exe"):
                poppler_bin = str(match)
                break
            if poppler_bin:
                break
    if poppler_bin:
        bin_dir = str(Path(poppler_bin).parent)
        entries = [e for e in os.environ.get("PATH", "").split(os.pathsep) if e]
        if bin_dir not in entries:
            os.environ["PATH"] = os.pathsep.join([bin_dir, *entries])


_ensure_toolchain()

from pagepilot.web import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    try:
        from waitress import serve                     # works on Windows, macOS and Linux
        print(f"PagePilot running on http://localhost:{port}")
        serve(app, host=os.getenv("HOST", "127.0.0.1"), port=port, threads=4, max_request_body_size=40 * 1024 * 1024)
    except ImportError:
        app.run(host=os.getenv("HOST", "127.0.0.1"), port=port)
