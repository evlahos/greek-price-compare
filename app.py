# -*- coding: utf-8 -*-
"""Web backend (Flask) για την Ελληνική Σύγκριση Τιμών — έκδοση Docker/web.

Ίδια λογική με το desktop (core.py). Σερβίρει σελίδα στο http://localhost:8765
και API endpoints. Το Playwright (Skroutz/Public) τρέχει server-side στο container.
"""
from __future__ import annotations

import os
import threading

from flask import Flask, jsonify, request, send_from_directory

import core

app = Flask(__name__, static_folder="static", static_url_path="")

# Το sync Playwright δεν είναι ασφαλές για ταυτόχρονες κλήσεις από πολλά threads·
# σειριοποιούμε τις κλήσεις που το χρησιμοποιούν.
_PW_LOCK = threading.Lock()


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"error": "Λείπει το ερώτημα."}), 400
    sources = [s for s in (request.args.get("sources") or "").split(",") if s]
    # Όλες οι πηγές τρέχουν ΠΑΡΑΛΛΗΛΑ (core.search_all). Το lock σειριοποιεί
    # μόνο ταυτόχρονες ΔΙΑΦΟΡΕΤΙΚΕΣ αναζητήσεις, όχι τις πηγές μεταξύ τους.
    try:
        with _PW_LOCK:
            rows, counts, diags = core.search_all(q, sources)
    except Exception as exc:
        return jsonify({"query": q, "products": [], "counts": {}, "diagnostics": [str(exc)]})
    return jsonify({"query": q, "products": rows, "counts": counts, "diagnostics": diags})


@app.get("/api/offers")
def api_offers():
    pid = (request.args.get("product_id") or "").strip()
    postal = (request.args.get("postal") or "").strip()
    if not pid:
        return jsonify({"error": "Λείπει το product_id."}), 400
    try:
        offers = core.BESTPRICE.offers(pid, postal)
        return jsonify({"offers": offers, "count": len(offers)})
    except Exception as exc:
        return jsonify({"offers": [], "error": str(exc)})


@app.get("/api/skroutz_offers")
def api_skroutz_offers():
    url = (request.args.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Λείπει το url."}), 400
    with _PW_LOCK:
        res = core.skroutz_offers(url)
    return jsonify(res)


@app.get("/api/history")
def api_history():
    pid = (request.args.get("product_id") or "").strip()
    if not pid:
        return jsonify({"error": "Λείπει το product_id."}), 400
    data = core.BESTPRICE.price_history(pid, 180)
    return jsonify({"text": core.format_history(data), "chart": core.history_series(data)})


@app.get("/api/decision")
def api_decision():
    q = (request.args.get("q") or "").strip()
    postal = (request.args.get("postal") or "").strip()
    if not q:
        return jsonify({"error": "Λείπει το ερώτημα."}), 400
    data = core.BESTPRICE.shopping_decision(q, postal)
    return jsonify({"text": core.format_decision(data)})


@app.get("/api/fetch_url")
def api_fetch_url():
    url = (request.args.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Λείπει το url."}), 400
    try:
        return jsonify({"product": core.fetch_product_url(url)})
    except Exception as exc:
        return jsonify({"product": None, "error": str(exc)})


@app.get("/api/bp_image")
def api_bp_image():
    pid = (request.args.get("product_id") or "").strip()
    return jsonify({"image": core.bestprice_image(pid)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    app.run(host="0.0.0.0", port=port, threaded=True)
