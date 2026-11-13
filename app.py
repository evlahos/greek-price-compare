# -*- coding: utf-8 -*-
"""Web backend (Flask) για την Ελληνική Σύγκριση Τιμών — έκδοση Docker/web.

Ίδια λογική με το desktop (core.py). Σερβίρει σελίδα στο http://localhost:8765
και API endpoints. Το Playwright (Skroutz/Public) τρέχει server-side στο container.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid

from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

import core

app = Flask(__name__, static_folder="static", static_url_path="")
HERE = os.path.dirname(os.path.abspath(__file__))

# Το sync Playwright δεν είναι ασφαλές για ταυτόχρονες κλήσεις από πολλά threads·
# σειριοποιούμε τις κλήσεις που το χρησιμοποιούν.
_PW_LOCK = threading.Lock()

# ── SQLite ιστορικό τιμών (τοπικό, best-effort· max 5.000 εγγραφές) ───────────
_DB_FILE = os.path.join(HERE, "price_log.db")
_DB_LOCK = threading.Lock()
_DB_MAX = 5000


def _db():
    conn = sqlite3.connect(_DB_FILE, check_same_thread=False)
    conn.execute("""CREATE TABLE IF NOT EXISTS price_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, query TEXT,
        title TEXT, source TEXT, price REAL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_title ON price_log(title)")
    return conn


def _log_prices(query, rows):
    """Καταγράφει (best-effort) τιμές προϊόντων στο τοπικό SQLite για ιστορικό."""
    recs = []
    for r in rows or []:
        price = r.get("price_from")
        title = (r.get("title") or "").strip()
        if title and price is not None:
            recs.append((time.time(), query, title, r.get("source") or "", float(price)))
    if not recs:
        return
    try:
        with _DB_LOCK:
            conn = _db()
            conn.executemany(
                "INSERT INTO price_log(ts,query,title,source,price) VALUES(?,?,?,?,?)", recs)
            conn.execute("""DELETE FROM price_log WHERE id IN (
                SELECT id FROM price_log ORDER BY id DESC LIMIT -1 OFFSET ?)""", (_DB_MAX,))
            conn.commit()
            conn.close()
    except Exception as exc:  # το ιστορικό δεν πρέπει ποτέ να ρίξει αναζήτηση
        app.logger.warning("price_log: %s", exc)


# ── Persistent price alerts (server-side JSON· επιβιώνουν restart) ────────────
_ALERTS_FILE = os.path.join(HERE, "alerts.json")
_ALERTS_LOCK = threading.Lock()


def _load_alerts():
    with _ALERTS_LOCK:
        if not os.path.exists(_ALERTS_FILE):
            return []
        try:
            with open(_ALERTS_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []


def _save_alerts(alerts):
    with _ALERTS_LOCK:
        try:
            with open(_ALERTS_FILE, "w", encoding="utf-8") as fh:
                json.dump(alerts, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            app.logger.error("alerts save: %s", exc)


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
    _log_prices(q, rows)
    return jsonify({"query": q, "products": rows, "counts": counts, "diagnostics": diags})


@app.get("/api/search_stream")
def api_search_stream():
    """Προοδευτική αναζήτηση (SSE): στέλνει αποτελέσματα ανά πηγή μόλις έρχονται."""
    q = (request.args.get("q") or "").strip()
    sources = [s for s in (request.args.get("sources") or "").split(",") if s]

    def gen():
        if not q:
            yield "data: " + json.dumps({"type": "error", "error": "Λείπει το ερώτημα."}) + "\n\n"
            return
        # Το sync Playwright δεν είναι ασφαλές για ταυτόχρονες αναζητήσεις —
        # σειριοποιούμε ολόκληρο το stream (όπως και το /api/search).
        collected = []
        with _PW_LOCK:
            try:
                for ev in core.search_all_stream(q, sources):
                    if ev.get("type") == "source":
                        collected.extend(ev.get("products") or [])
                    yield "data: " + json.dumps(ev, ensure_ascii=False) + "\n\n"
            except Exception as exc:
                yield "data: " + json.dumps({"type": "error", "error": str(exc)}) + "\n\n"
        _log_prices(q, collected)

    return Response(stream_with_context(gen()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                             "Connection": "keep-alive"})


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


@app.get("/api/eu_price")
def api_eu_price():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"matched": None, "prices": []})
    try:
        return jsonify(core.eu_reference_prices(q))
    except Exception as exc:
        return jsonify({"matched": None, "prices": [], "error": str(exc)})


@app.get("/api/fuel")
def api_fuel():
    try:
        return jsonify(core.fuel_prices())
    except Exception as exc:
        return jsonify({"date": None, "national": [], "prefectures": [],
                        "fuels": [], "error": str(exc)})


@app.get("/api/fuel_penalties")
def api_fuel_penalties():
    try:
        return jsonify(core.fuel_penalties())
    except Exception as exc:
        return jsonify({"items": [], "error": str(exc)})


@app.get("/api/fuel_stations")
def api_fuel_stations():
    pref = (request.args.get("pref") or "").strip()
    q = (request.args.get("q") or "").strip()
    try:
        return jsonify(core.fuel_stations(pref or None, q or None))
    except Exception as exc:
        return jsonify({"stations": [], "prefectures": [], "fuels": [], "error": str(exc)})


@app.get("/api/videos")
def api_videos():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"videos": []})
    try:
        return jsonify({"videos": core.youtube_videos(q)})
    except Exception as exc:
        return jsonify({"videos": [], "error": str(exc)})


@app.get("/api/version")
def api_version():
    return jsonify({"version": getattr(core, "VERSION", "")})


@app.get("/api/compare_international")
def api_compare_international():
    """🌍 Διεθνής σύγκριση: πραγματική αναζήτηση σε Amazon ευρωζώνης + GR τιμή."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"error": "Λείπει το ερώτημα."}), 400
    gr_price = request.args.get("gr_price")
    gr_url = (request.args.get("gr_url") or "").strip()
    try:
        gp = float(gr_price) if gr_price not in (None, "") else None
    except ValueError:
        gp = None
    try:
        with _PW_LOCK:
            data = core.compare_international(q, gp, gr_url)
        return jsonify(data)
    except Exception as exc:
        return jsonify({"query": q, "results": [], "note": "", "diagnostics": [str(exc)]})


@app.get("/api/price_log")
def api_price_log_get():
    """Τοπικό ιστορικό τιμών για έναν τίτλο (+ sparkline series)."""
    title = (request.args.get("title") or "").strip()
    if not title:
        return jsonify({"series": [], "entries": []})
    try:
        days = int(request.args.get("days") or "90")
    except ValueError:
        days = 90
    since = time.time() - days * 86400
    try:
        with _DB_LOCK:
            conn = _db()
            cur = conn.execute(
                "SELECT ts,source,price FROM price_log WHERE title=? AND ts>=? ORDER BY ts",
                (title, since))
            rows = cur.fetchall()
            conn.close()
    except Exception as exc:
        return jsonify({"series": [], "entries": [], "error": str(exc)})
    entries = [{"ts": r[0], "source": r[1], "price": r[2]} for r in rows]
    series = [r[2] for r in rows]
    return jsonify({"title": title, "entries": entries, "series": series, "count": len(entries)})


@app.delete("/api/price_log")
def api_price_log_clear():
    try:
        with _DB_LOCK:
            conn = _db()
            conn.execute("DELETE FROM price_log")
            conn.commit()
            conn.close()
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@app.get("/api/alerts")
def api_alerts_list():
    return jsonify({"alerts": _load_alerts()})


@app.post("/api/alerts")
def api_alerts_create():
    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "").strip()
    target = body.get("target_price")
    if not title or target is None:
        return jsonify({"error": "Λείπει title ή target_price."}), 400
    try:
        target = float(target)
    except (TypeError, ValueError):
        return jsonify({"error": "Μη έγκυρη target_price."}), 400
    alerts = _load_alerts()
    alert = {"id": uuid.uuid4().hex[:12], "title": title, "target_price": target,
             "product_id": (body.get("product_id") or "").strip(),
             "product_url": (body.get("product_url") or "").strip(),
             "created": time.time(), "triggered": False, "last_price": None}
    alerts.append(alert)
    _save_alerts(alerts)
    return jsonify({"ok": True, "alert": alert})


@app.delete("/api/alerts/<alert_id>")
def api_alerts_delete(alert_id):
    alerts = [a for a in _load_alerts() if a.get("id") != alert_id]
    _save_alerts(alerts)
    return jsonify({"ok": True})


@app.patch("/api/alerts/<alert_id>")
def api_alerts_update(alert_id):
    body = request.get_json(silent=True) or {}
    alerts = _load_alerts()
    for a in alerts:
        if a.get("id") == alert_id:
            if "target_price" in body:
                try:
                    a["target_price"] = float(body["target_price"])
                except (TypeError, ValueError):
                    pass
            if body.get("reset"):
                a["triggered"] = False
            break
    _save_alerts(alerts)
    return jsonify({"ok": True, "alerts": alerts})


@app.post("/api/alerts/check")
def api_alerts_check():
    """On-demand έλεγχος: ενημερώνει τρέχουσα τιμή κάθε alert από το BestPrice."""
    alerts = _load_alerts()
    triggered = []
    for a in alerts:
        pid = a.get("product_id")
        price = None
        try:
            if pid:
                offers = core.BESTPRICE.offers(pid, "")
                prices = [o.get("item_price") for o in offers if o.get("item_price")]
                price = min(prices) if prices else None
        except Exception:
            price = None
        if price is not None:
            a["last_price"] = price
            if price <= a.get("target_price", 0):
                a["triggered"] = True
                triggered.append({"title": a.get("title"), "price": price,
                                  "target": a.get("target_price")})
    _save_alerts(alerts)
    return jsonify({"ok": True, "triggered": triggered, "alerts": alerts})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    # Desktop: μόνο localhost (ασφαλές). Docker: βάλε GPC_HOST=0.0.0.0 για έκθεση.
    host = os.environ.get("GPC_HOST", "127.0.0.1")
    app.run(host=host, port=port, threaded=True)
