"""PriceScout — Flask app factory."""
import os
from dotenv import load_dotenv
from flask import Flask, render_template

from item_db import init_db
from suppliers import SUPPLIERS as SUPPLIERS_CONFIG
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


@app.route("/")
def index():
    return render_template("index.html", suppliers=SUPPLIERS_CONFIG)


if __name__ == "__main__":
    init_db()
    from core import ensure_exports_dir, ensure_debug_dir
    ensure_exports_dir()
    ensure_debug_dir()
    port     = int(os.getenv("PORT", 5000))
    parallel = int(os.getenv("MAX_PARALLEL_ITEMS", "5"))
    print("=" * 52)
    print("  PriceScout — Моніторинг цін будматеріалів")
    print(f"  http://localhost:{port}")
    print(f"  Паралельність: {parallel} матеріалів одночасно")
    print("=" * 52)
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)