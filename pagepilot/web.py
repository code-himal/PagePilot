"""Flask application: upload -> extract (JSON) -> export (file)."""
import io
import os
import tempfile
import threading

os.environ.setdefault("OMP_THREAD_LIMIT", "1")       # one Tesseract thread per request; scale with workers

from flask import Flask, jsonify, render_template, request, send_file, Response
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from . import __version__, exporters, ocr
from .config import Config
from .errors import ExtractError
from .pipeline import extract_document

_slots = threading.BoundedSemaphore(max(1, Config.MAX_CONCURRENT))

CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def create_app() -> Flask:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(__name__, static_folder=os.path.join(root, "static"),
                template_folder=os.path.join(root, "templates"))
    app.config["MAX_CONTENT_LENGTH"] = (max(Config.MAX_UPLOAD_MB, Config.MAX_EXPORT_MB) + 2) * 1024 * 1024
    app.json.ensure_ascii = False

    # ------------------------------------------------------------------ pages
    @app.get("/")
    def index():
        return render_template("index.html", max_mb=Config.MAX_UPLOAD_MB, max_pages=Config.MAX_PAGES,
                               version=__version__)

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok", ocr=ocr.tesseract_available(), version=__version__)

    @app.get("/robots.txt")
    def robots():
        return Response(f"User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {request.url_root}sitemap.xml\n",
                        mimetype="text/plain")

    @app.get("/sitemap.xml")
    def sitemap():
        xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               f"<url><loc>{request.url_root}</loc><changefreq>monthly</changefreq></url></urlset>")
        return Response(xml, mimetype="application/xml")

    # ------------------------------------------------------------------ API
    @app.get("/api/config")
    def api_config():
        return jsonify(max_mb=Config.MAX_UPLOAD_MB, max_pages=Config.MAX_PAGES,
                       languages=ocr.language_options(), ocr=ocr.tesseract_available(), version=__version__)

    @app.post("/api/extract")
    def api_extract():
        f = request.files.get("file")
        if f is None or not f.filename:
            raise ExtractError("no_file", "Choose a file to upload.")
        if not _slots.acquire(timeout=45):
            raise ExtractError("busy", "The server is busy right now. Please try again in a moment.", 503)
        try:
            with tempfile.TemporaryDirectory(prefix="docpixly-") as tmp:
                path = os.path.join(tmp, "upload.bin")           # never use the client's file name on disk
                f.save(path)
                size = os.path.getsize(path)
                if size == 0:
                    raise ExtractError("empty_file", "This file is empty.")
                if size > Config.MAX_UPLOAD_MB * 1024 * 1024:
                    raise ExtractError("too_large", f"This file is larger than {Config.MAX_UPLOAD_MB} MB.", 413)
                result = extract_document(
                    path, f.filename,
                    lang=request.form.get("lang", "eng"),
                    mode=request.form.get("mode", "auto"),
                    pages_spec=request.form.get("pages", ""))
        finally:
            _slots.release()
        resp = jsonify(result)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.post("/api/export")
    def api_export():
        if (request.content_length or 0) > Config.MAX_EXPORT_MB * 1024 * 1024:
            raise ExtractError("too_large", "This document is too large to export.", 413)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ExtractError("bad_request", "Invalid export request.")
        data, name, mime = exporters.export(
            body.get("documents"), str(body.get("format", "")), numbers=bool(body.get("numbers", True)),
            table_id=body.get("table") if isinstance(body.get("table"), str) else None,
            doc_index=body.get("doc_index") if isinstance(body.get("doc_index"), int) else 0)
        resp = send_file(io.BytesIO(data), mimetype=mime, as_attachment=True, download_name=name)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    # ------------------------------------------------------------------ errors
    def _json_error(code: str, message: str, status: int):
        resp = jsonify(error={"code": code, "message": message})
        resp.status_code = status
        return resp

    @app.errorhandler(ExtractError)
    def on_extract_error(e: ExtractError):
        return _json_error(e.code, e.message, e.status)

    @app.errorhandler(RequestEntityTooLarge)
    def on_too_large(e):
        return _json_error("too_large", f"This file is larger than {Config.MAX_UPLOAD_MB} MB.", 413)

    @app.errorhandler(HTTPException)
    def on_http(e: HTTPException):
        if request.path.startswith("/api/"):
            return _json_error("http_error", e.description or e.name, e.code or 500)
        return e

    @app.errorhandler(Exception)
    def on_unexpected(e: Exception):
        app.logger.exception("Unhandled error")
        if request.path.startswith("/api/"):
            return _json_error("server_error", "Something went wrong while reading this file. "
                                               "Try another file, or a clearer scan.", 500)
        return "Internal server error", 500

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Content-Security-Policy", CSP)
        resp.headers.setdefault("X-Frame-Options", "DENY")
        return resp

    return app
