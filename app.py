"""PriceScout — Flask app factory."""
import os
import time
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, render_template

from core.item_db import init_db
from core.suppliers import SUPPLIERS as SUPPLIERS_CONFIG
from routes.scrape    import bp as scrape_bp
from routes.items     import bp as items_bp
from routes.exports   import bp as exports_bp
from routes.kostoris  import bp as kostoris_bp
from routes.projects  import bp as projects_bp

load_dotenv()

app = Flask(__name__)
app.register_blueprint(scrape_bp)
app.register_blueprint(items_bp)
app.register_blueprint(exports_bp)
app.register_blueprint(kostoris_bp)
app.register_blueprint(projects_bp)

# Initialize DB at import time so WSGI servers (gunicorn, waitress) also
# create tables — not just `python app.py` direct runs.
from core.core import ensure_exports_dir, ensure_debug_dir
init_db()
ensure_exports_dir()
ensure_debug_dir()


def _asset_version() -> str:
    """Bust the browser cache for static/js/app.js and static/css/app.css.

    Uses the newer of the two files' mtime so editing either CSS or JS
    forces a fresh fetch — otherwise users keep running the old JS until
    they hit Ctrl-Shift-R, and Result-tab features look broken.
    """
    static_dir = Path(app.root_path) / "static"
    candidates = [static_dir / "js" / "app.js", static_dir / "css" / "app.css"]
    mtimes = [p.stat().st_mtime for p in candidates if p.exists()]
    if not mtimes:
        return str(int(time.time()))
    return str(int(max(mtimes)))


@app.route("/")
def index():
    return render_template(
        "index.html",
        suppliers=SUPPLIERS_CONFIG,
        asset_version=_asset_version(),
    )


if __name__ == "__main__":
    port     = int(os.getenv("PORT", 5000))
    parallel = int(os.getenv("MAX_PARALLEL_ITEMS", "5"))
    print("=" * 52)
    print("  PriceScout — Моніторинг цін будматеріалів")
    print(f"  http://localhost:{port}")
    print(f"  Паралельність: {parallel} матер�