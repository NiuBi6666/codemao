import os

from flask import Flask

from . import db
from .web import bp


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "development-only"),
        DATABASE_PATH=os.environ.get("DATABASE_PATH", "/data/codemao.sqlite3"),
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME", "admin"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", ""),
        ADMIN_DISPLAY_NAME=os.environ.get("ADMIN_DISPLAY_NAME", "系统管理员"),
        INITIAL_ROSTER_FILE=os.environ.get("INITIAL_ROSTER_FILE", ""),
        COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
        MAX_CONTENT_LENGTH=int(os.environ.get("MAX_UPLOAD_MB", "10")) * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)

    app.config["SESSION_COOKIE_SECURE"] = app.config["COOKIE_SECURE"]
    app.register_blueprint(bp)
    db.init_app(app)

    with app.app_context():
        db.initialize()

    @app.after_request
    def secure_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store"
        return response

    return app
