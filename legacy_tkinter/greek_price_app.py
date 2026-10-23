# -*- coding: utf-8 -*-
"""Ελληνική Σύγκριση Τιμών 0.13 — desktop (Tkinter, μόνο standard library).

Πηγές:
  • BestPrice MCP — επίσημο δημόσιο MCP χωρίς κλειδί (aggregator). Τιμές,
    προσφορές καταστημάτων, ιστορικό τιμής, σύσταση αγοράς, rating καταστήματος.
  • Άμεσος σύνδεσμος προϊόντος — επικόλλησε URL από οποιοδήποτε ελληνικό eshop
    (Public, Πλαίσιο, Κωτσόβολος, Skroutz, SHOPFLIX, e-shop.gr…) και τραβάμε
    τιμή/διαθεσιμότητα/βαθμολογία μέσω JSON-LD (schema.org).
  • Skroutz αναζήτηση — best-effort (μπορεί να μπλοκάρει το Cloudflare).

Προαιρετικό: `pip install cloudscraper` βελτιώνει την πρόσβαση σε Skroutz/sites
πίσω από Cloudflare. Αν δεν υπάρχει, η εφαρμογή δουλεύει κανονικά με τα υπόλοιπα.
"""
from __future__ import annotations

import csv
import gzip
import json
import io
import os
import sys
import queue
import re
import threading
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zlib
from html import unescape

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    from PIL import Image, ImageTk  # Pillow (για φωτογραφίες προϊόντων)
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

APP_NAME = "Ελληνική Σύγκριση Τιμών"
VERSION = "0.14"
BESTPRICE_MCP = "https://mcp.bestprice.gr/mcp"
HERE = os.path.dirname(os.path.abspath(__file__))
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Σε αυτόνομο build (PyInstaller / .exe): δείξε στο Playwright το ενσωματωμένο Chromium.
if getattr(sys, "frozen", False):
    _bundled_browsers = os.path.join(getattr(sys, "_MEIPASS", HERE), "ms-playwright")
    if os.path.isdir(_bundled_browsers):
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", _bundled_browsers)
    # app_debug.log δίπλα στο .exe, όχι μέσα στο προσωρινό bundle
    HERE = os.path.dirname(sys.executable)

try:
    import cloudscraper  # type: ignore
    _SCRAPER = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False})
except Exception:
    _SCRAPER = None


# ============================ Βοηθητικά ============================ #
def first(item, *keys, default=""):
    for key in keys:
        value = item.get(key) if isinstance(item, dict) else None
        if value is not None and value != "":
            return value
    return default


def to_float(value):
    if value in (None, "", "—"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"[^\d,\.]", "", str(value))
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def rating_cell(value, count=None):
    """Εμφάνιση βαθμολογίας μόνο αν είναι έγκυρη κλίμακα 0–5· αλλιώς «—»."""
    r = to_float(value)
    if r is None or r <= 0 or r > 5:
        return "—"
    return f"{r:.1f}" + (f" ({count})" if count else "")


def price_text(value):
    v = to_float(value) if not isinstance(value, (int, float)) else value
    if v is None:
        return "—" if value in (None, "", "—") else str(value)
    return f"€{v:.2f}"


def log_error(where):
    try:
        with open(os.path.join(HERE, "app_debug.log"), "a", encoding="utf-8") as fh:
            fh.write(f"\n--- {where} ---\n{traceback.format_exc()}\n")
    except OSError:
        pass


def http_get(url, timeout=25, extra_headers=None, encoding="utf-8"):
    headers = {
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "el-GR,el;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
    }
    if extra_headers:
        headers.update(extra_headers)
    if _SCRAPER is not None:
        resp = _SCRAPER.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
        enc = (response.headers.get("Content-Encoding") or "").lower()
    if enc == "gzip":
        raw = gzip.decompress(raw)
    elif enc == "deflate":
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw.decode(encoding, "replace")


def http_bytes(url, timeout=15):
    """Κατεβάζει δυαδικά δεδομένα (π.χ. εικόνα)."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "image/*,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def big_image_url(url):
    """Μεγαλύτερη έκδοση γνωστών εικόνων (για το παράθυρο μεγέθυνσης)."""
    if not url:
        return url
    u = re.sub(r"_SX\d+Y\d+", "_SX800Y800", url)               # BestPrice CDN
    u = re.sub(r"-\d{2,4}x\d{2,4}(\.[a-zA-Z]+)$", r"-800x800\1", u)  # Public webstorage
    u = u.replace("/images/PER/SMALL/", "/images/PER/BIG/")    # e-shop.gr
    u = re.sub(r"/(small|medium|large)_", "/xlarge_", u)        # Skroutz
    return u


# ============================ JSON-LD ============================ #
def extract_jsonld(html):
    blocks = []
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    ):
        text = match.group(1).strip().replace("\n", " ")
        data = None
        for candidate in (text, unescape(text)):
            try:
                data = json.loads(candidate)
                break
            except json.JSONDecodeError:
                continue
        if data is None:
            continue
        if isinstance(data, list):
            blocks.extend(d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            graph = data.get("@graph")
            if isinstance(graph, list):
                blocks.extend(d for d in graph if isinstance(d, dict))
            else:
                blocks.append(data)
    return blocks


def _is_type(node, wanted):
    t = node.get("@type")
    if isinstance(t, list):
        return any(str(x).lower() == wanted for x in t)
    return str(t).lower() == wanted


def product_from_jsonld(html, url=""):
    product_node = next((n for n in extract_jsonld(html) if _is_type(n, "product")), None)
    if product_node is None:
        return None
    title = product_node.get("name") or ""
    image = product_node.get("image")
    if isinstance(image, list):
        image = image[0] if image else ""
    if isinstance(image, dict):
        image = image.get("url", "")
    rating = rating_count = None
    agg = product_node.get("aggregateRating")
    if isinstance(agg, dict):
        rating = to_float(agg.get("ratingValue"))
        rating_count = agg.get("reviewCount") or agg.get("ratingCount")
    price = currency = availability = None
    offers = product_node.get("offers")
    offer_list = [offers] if isinstance(offers, dict) else (
        [o for o in offers if isinstance(o, dict)] if isinstance(offers, list) else [])
    prices = []
    for off in offer_list:
        p = to_float(off.get("price") or off.get("lowPrice"))
        if p is not None:
            prices.append(p)
        currency = currency or off.get("priceCurrency")
        if off.get("availability"):
            availability = str(off["availability"]).split("/")[-1]
    if prices:
        price = min(prices)
    return {
        "title": unescape(str(title)).strip(),
        "price": price, "currency": currency or "EUR",
        "availability": availability or "", "rating": rating,
        "rating_count": rating_count, "image": image or "",
        "url": url, "offer_count": len(offer_list),
    }


# ============================ BestPrice MCP ============================ #
class BestPriceSource:
    name = "BestPrice"

    def __init__(self):
        self._request_id = 10
        self._session_id = None
        self._initialized = False

    def _post(self, payload, timeout=35):
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",
                   "User-Agent": f"GreekPriceCompare/{VERSION}"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        req = urllib.request.Request(BESTPRICE_MCP, data=data, method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            sid = response.headers.get("Mcp-Session-Id")
            if sid:
                self._session_id = sid
            body = response.read().decode("utf-8", "replace")
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                try:
                    return json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Το BestPrice επέστρεψε μη αναγνωρίσιμη απάντηση.") from exc

    def _ensure(self):
        if self._initialized:
            return
        init = self._post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                      "clientInfo": {"name": "greek-price-compare", "version": VERSION}}})
        if isinstance(init, dict) and init.get("error"):
            raise RuntimeError(init["error"].get("message", "Αποτυχία σύνδεσης MCP"))
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=10)
        except Exception:
            pass
        self._initialized = True

    def _call(self, tool, arguments):
        self._ensure()
        self._request_id += 1
        result = self._post({"jsonrpc": "2.0", "id": self._request_id,
                             "method": "tools/call",
                             "params": {"name": tool, "arguments": arguments}})
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(result["error"].get("message", str(result["error"])))
        out = result.get("result", result) if isinstance(result, dict) else result
        if isinstance(out, dict) and out.get("isError"):
            content = out.get("content", [])
            raise RuntimeError(" ".join(x.get("text", "") for x in content if isinstance(x, dict))
                               or "Η αναζήτηση απέτυχε.")
        return self._unpack(out)

    @staticmethod
    def _unpack(out):
        if not isinstance(out, dict):
            return out
        if isinstance(out.get("structuredContent"), (dict, list)):
            return out["structuredContent"]
        for item in out.get("content", []) if isinstance(out.get("content"), list) else []:
            text = item.get("text", "") if isinstance(item, dict) else ""
            if text:
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"text": text}
        return out

    def search(self, query, limit=8):
        data = self._call("search_products", {"query": query, "limit": max(1, min(8, limit))})
        rows = records(data, ("products", "results", "items", "data"))
        out = []
        for p in rows:
            pid = str(first(p, "product_id", "id", "bp_product_id", default="")).strip()
            title = str(first(p, "title", "name", "product_name", "product_title", default="")).strip()
            if not pid or not title:
                continue
            out.append({
                "source": self.name, "product_id": pid, "title": title,
                "price_from": to_float(first(p, "price_from", "price", "min_price", "lowest_price", default=None)),
                "offer_count": first(p, "offer_count", "offers_count", "shop_count", default=None),
                "rating": to_float(first(p, "rating", default=None)),
                "url": first(p, "product_url", "url", "bestprice_url", default=""),
            })
        return out

    def offers(self, product_id, postal_code=""):
        plan = [("lowest_item_price", None), ("merchant_rating", None),
                ("lowest_item_price", 4.0), ("lowest_item_price", 3.0),
                ("lowest_item_price", 2.0), ("lowest_item_price", 1.0)]
        if postal_code.strip():
            plan.insert(1, ("lowest_total_cost", None))
        merged = {}
        for objective, min_rating in plan:
            args = {"product_id": product_id, "objective": objective,
                    "in_stock_only": False, "limit": 10}
            if min_rating is not None:
                args["minimum_merchant_rating"] = min_rating
            if postal_code.strip():
                args["postal_code"] = postal_code.strip()
            try:
                response = self._call("compare_offers", args)
            except Exception:
                continue
            for off in records(response, ("offers", "results", "items", "rows", "data")):
                if not isinstance(off, dict):
                    continue
                oid = first(off, "offer_id", default="") or "|".join(
                    str(first(off, k, default="")) for k in ("merchant_name", "item_price", "offer_title"))
                if oid not in merged:
                    merged[oid] = norm_offer(off, self.name)
        return list(merged.values())

    def price_history(self, product_id, period_days=180):
        try:
            data = self._call("get_price_history", {"product_id": product_id, "period_days": period_days})
        except Exception as exc:
            return {"error": str(exc)}
        return data if isinstance(data, dict) else {"text": str(data)}

    def shopping_decision(self, message, postal_code=""):
        args = {"message": message, "evidence_detail": "summary"}
        if postal_code.strip():
            args["postal_code"] = postal_code.strip()
        try:
            data = self._call("get_shopping_decision", args)
        except Exception as exc:
            return {"error": str(exc)}
        return data if isinstance(data, dict) else {"text": str(data)}


def norm_offer(off, source):
    price = to_float(first(off, "item_price", "price", "item_price_eur", default=None))
    shipping = to_float(first(off, "shipping_price", "shipping", "shipping_cost", default=None))
    total = to_float(first(off, "total_price", "price_with_shipping", "total", default=None))
    if total is None and price is not None and shipping is not None:
        total = price + shipping
    return {
        "source": source,
        "merchant_name": first(off, "merchant_name", "shop_name", "merchant", "shop", default="Άγνωστο κατάστημα"),
        "merchant_rating": to_float(first(off, "merchant_rating", "shop_rating", "rating", default=None)),
        "merchant_rating_count": first(off, "merchant_rating_count", "rating_count", default=None),
        "item_price": price, "shipping_price": shipping, "total_price": total,
        "availability": first(off, "availability", "stock_status", "stock", default=""),
        "delivery_estimate": first(off, "delivery_estimate", "delivery", "delivery_time", default=""),
        "offer_url": first(off, "offer_url", "url", "bestprice_url", "product_url", "link", default=""),
        "currency": first(off, "currency", default="EUR"),
    }


def records(data, keys):
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if not isinstance(data, dict):
        return []
    for key in keys:
        val = data.get(key)
        if isinstance(val, list):
            rows = [d for d in val if isinstance(d, dict)]
            if rows:
                return rows
        elif isinstance(val, dict):
            rows = records(val, keys)
            if rows:
                return rows
    content = data.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                try:
                    return records(json.loads(item["text"]), keys)
                except json.JSONDecodeError:
                    pass
    return []


# ============================ Scraper καταστημάτων ============================ #
SHOP_LABELS = {
    "skroutz.gr": "Skroutz", "www.skroutz.gr": "Skroutz",
    "public.gr": "Public", "www.public.gr": "Public",
    "plaisio.gr": "Πλαίσιο", "www.plaisio.gr": "Πλαίσιο",
    "kotsovolos.gr": "Κωτσόβολος", "www.kotsovolos.gr": "Κωτσόβολος",
    "shopflix.gr": "SHOPFLIX", "www.shopflix.gr": "SHOPFLIX",
    "e-shop.gr": "e-shop.gr", "www.e-shop.gr": "e-shop.gr",
    "mediamarkt.gr": "MediaMarkt", "www.mediamarkt.gr": "MediaMarkt",
}


def shop_label(url):
    host = urllib.parse.urlparse(url).netloc.lower()
    return SHOP_LABELS.get(host, host or "Κατάστημα")


def _meta(html, prop):
    for pattern in (
        r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']%s["\']',
    ):
        m = re.search(pattern % re.escape(prop), html, re.IGNORECASE)
        if m:
            return unescape(m.group(1)).strip()
    return ""


def fetch_product_url(url):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        html = http_get(url, timeout=25)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429, 503):
            extra = " (πιθανό Cloudflare — δες README για cloudscraper)" if exc.code in (403, 503) else ""
            raise RuntimeError(f"{shop_label(url)}: μπλοκαρίστηκε (HTTP {exc.code}){extra}.") from exc
        raise RuntimeError(f"{shop_label(url)}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{shop_label(url)}: δεν συνδέθηκε — {exc.reason}") from exc
    prod = product_from_jsonld(html, url)
    if not prod or not prod.get("title"):
        title = _meta(html, "og:title") or _meta(html, "twitter:title")
        if title:
            prod = {
                "title": title,
                "price": to_float(_meta(html, "product:price:amount") or _meta(html, "og:price:amount")),
                "currency": _meta(html, "product:price:currency") or "EUR",
                "availability": _meta(html, "product:availability") or "",
                "rating": None, "rating_count": None,
                "image": _meta(html, "og:image"), "url": url, "offer_count": 1,
            }
    if not prod or not prod.get("title"):
        raise RuntimeError(f"{shop_label(url)}: δεν βρέθηκαν δομημένα δεδομένα προϊόντος "
                           f"στη σελίδα. Ίσως δεν είναι σελίδα προϊόντος.")
    prod["merchant_name"] = shop_label(url)
    prod["source"] = "Άμεσος σύνδεσμος"
    return prod


def _mk_listing_row(item, label, base_url):
    name = item.get("name") or item.get("title")
    if not name:
        return None
    url = item.get("url") or item.get("@id") or ""
    if url and not str(url).startswith("http"):
        url = urllib.parse.urljoin(base_url, str(url))
    price = None
    offers = item.get("offers")
    if isinstance(offers, dict):
        price = to_float(offers.get("price") or offers.get("lowPrice"))
    elif isinstance(offers, list):
        ps = [to_float(o.get("price") or o.get("lowPrice")) for o in offers if isinstance(o, dict)]
        ps = [x for x in ps if x is not None]
        price = min(ps) if ps else None
    if price is None:
        price = to_float(item.get("price"))
    rating = rating_count = None
    agg = item.get("aggregateRating")
    if isinstance(agg, dict):
        rating = to_float(agg.get("ratingValue"))
        rating_count = agg.get("reviewCount") or agg.get("ratingCount")
    image = item.get("image")
    if isinstance(image, list):
        image = image[0] if image else ""
    if isinstance(image, dict):
        image = image.get("url", "")
    title = unescape(str(name)).strip()
    return {"source": label, "product_id": "", "title": title, "image": image or "",
            "price_from": price, "offer_count": 1, "rating": rating, "product_url": url,
            "_direct": {"merchant_name": label, "title": title, "price": price, "url": url,
                        "availability": "", "currency": "EUR", "image": image or "",
                        "rating": rating, "rating_count": rating_count, "source": label}}


def parse_search_listing(html, base_url, label, limit=15):
    """Βγάζει προϊόντα από σελίδα αναζήτησης μέσω JSON-LD (ItemList/Product)."""
    rows, seen = [], set()
    for node in extract_jsonld(html):
        items = []
        if _is_type(node, "itemlist"):
            for el in node.get("itemListElement", []):
                if isinstance(el, dict):
                    items.append(el.get("item", el))
        elif _is_type(node, "product"):
            items.append(node)
        for item in items:
            if not isinstance(item, dict):
                continue
            row = _mk_listing_row(item, label, base_url)
            if not row:
                continue
            key = (row["title"].casefold(), row.get("product_url", ""))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows[:limit]


# ----------------------- Μηχανή Playwright (headless browser) ------------- #
# Καταστήματα που επιβεβαιωμένα δίνουν JSON-LD ItemList μετά το render.
# (Ελέγχθηκαν ζωντανά: Skroutz & Public.) Το Skroutz χρειάζεται πραγματικό browser
# γιατί μπλοκάρει τη σκέτη Python με Cloudflare (403).
PLAYWRIGHT_SEARCH = {
    "Skroutz": "https://www.skroutz.gr/search?keyphrase={q}",
    "Public":  "https://www.public.gr/search?q={q}",
}
# Καταστήματα με ειδικό frontend (χωρίς JSON-LD/καθαρό URL): δεν υποστηρίζονται ακόμη.
UNSUPPORTED_SHOPS = {"Πλαίσιο", "Κωτσόβολος", "SHOPFLIX", "MediaMarkt"}

PLAYWRIGHT_HINT = ("χρειάζεται Playwright — τρέξε 'pip install playwright' και "
                   "μετά 'playwright install chromium'")


def playwright_available():
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def _find_browser_exe():
    """Βρίσκει τον Edge ή τον Chrome στις τυπικές διαδρομές των Windows."""
    for c in (
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ):
        if c and os.path.isfile(c):
            return c
    return None


def launch_chromium(pw):
    """Εκκινεί headless browser. Σειρά προσπαθειών:
    1) το Chromium του Playwright (αν κατέβηκε),
    2) ο Edge/Chrome μέσω channel,
    3) ο Edge/Chrome απευθείας από τη διαδρομή του στα Windows (πιο σίγουρο).
    Έτσι δεν χρειάζεται καθόλου το κατέβασμα του Chromium."""
    attempts = []
    try:
        return pw.chromium.launch(headless=True)
    except Exception as exc:
        attempts.append(f"chromium: {str(exc)[:80]}")
    for channel in ("msedge", "chrome"):
        try:
            return pw.chromium.launch(headless=True, channel=channel)
        except Exception as exc:
            attempts.append(f"{channel}: {str(exc)[:80]}")
    exe = _find_browser_exe()
    if exe:
        try:
            return pw.chromium.launch(headless=True, executable_path=exe)
        except Exception as exc:
            attempts.append(f"exe: {str(exc)[:80]}")
    raise RuntimeError("Δεν ξεκίνησε browser — " + " | ".join(attempts[-3:]))


def playwright_search_all(labels, query):
    """Αναζήτηση με headless Chromium (Playwright). Ένας browser για όλα τα
    καταστήματα. Επιστρέφει (rows, diagnostics)."""
    targets = [(lbl, PLAYWRIGHT_SEARCH[lbl]) for lbl in labels if lbl in PLAYWRIGHT_SEARCH]
    if not targets:
        return [], []
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return [], [f"{lbl}: {PLAYWRIGHT_HINT}" for lbl, _ in targets]

    rows, diags = [], []
    q = urllib.parse.quote(query)
    wait_js = ("() => [...document.querySelectorAll('script[type=\"application/ld+json\"]')]"
               ".some(s => (s.textContent||'').includes('ItemList'))")
    try:
        with sync_playwright() as pw:
            try:
                browser = launch_chromium(pw)
            except Exception as exc:
                msg = str(exc)
                if "Executable doesn't exist" in msg or "playwright install" in msg:
                    return [], ["Playwright: λείπει ο browser — τρέξε 'playwright install chromium'"]
                return [], [f"Playwright: σφάλμα εκκίνησης — {msg[:100]}"]
            ctx = browser.new_context(user_agent=_UA, locale="el-GR",
                                      viewport={"width": 1366, "height": 900})
            for label, tmpl in targets:
                url = tmpl.format(q=q)
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    try:
                        page.wait_for_function(wait_js, timeout=9000)
                    except Exception:
                        page.wait_for_timeout(2500)
                    html = page.content()
                    base = page.url
                    r = parse_search_listing(html, base, label, limit=20)
                    rows.extend(r)
                    diags.append(f"{label}: {len(r)} προϊόντα" if r
                                 else f"{label}: δεν βρέθηκαν προϊόντα (ίσως άλλαξε η σελίδα)")
                except Exception as exc:
                    diags.append(f"{label}: {str(exc)[:80]}")
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
            browser.close()
    except Exception as exc:
        diags.append(f"Playwright: {str(exc)[:120]}")
    return rows, diags


_SKROUTZ_OFFERS_JS = r"""async (sku) => {
  const r = await fetch('/s/' + sku + '/shops_list',
      {headers: {'Accept': 'text/html', 'Turbo-Frame': 'shops-list-frame'}});
  const t = await r.text();
  const doc = new DOMParser().parseFromString(t, 'text/html');
  const dec = s => { try { return decodeURIComponent(s); } catch (e) { return s; } };
  return [...doc.querySelectorAll('[data-shop-id]')].map(el => {
    const a = el.querySelector('a[href*="/shop/"]');
    let shop = null;
    if (a) { const m = (a.getAttribute('href') || '').match(/\/shop\/\d+\/([^\/#?]+)/); if (m) shop = dec(m[1]).replace(/-/g, ' '); }
    const rt = (a ? a.textContent : '').replace(/\s+/g, ' ').trim();
    const rm = rt.match(/([\d,]+)\s*\((\d+)/);
    const url = el.getAttribute('data-product-url');
    const av = (el.querySelector('[class*="availability" i],[class*="delivery" i]') || {}).textContent || '';
    return {shop: shop, price: parseFloat(el.getAttribute('data-raw-price')),
            rating: rm ? rm[1] : null, rating_count: rm ? rm[2] : null,
            url: url ? ('https://www.skroutz.gr' + url) : null,
            delivery: av.replace(/\s+/g, ' ').trim()};
  });
}"""


def skroutz_offers(product_url):
    """Λίστα όλων των καταστημάτων ενός προϊόντος Skroutz (μέσω Playwright).
    Χρησιμοποιεί το endpoint /s/<id>/shops_list που δίνει όλα τα καταστήματα."""
    m = re.search(r"/s/(\d+)/", product_url or "")
    if not m:
        return {"offers": [], "error": "Μη έγκυρος σύνδεσμος Skroutz."}
    sku = m.group(1)
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {"offers": [], "error": PLAYWRIGHT_HINT}
    raw = None
    try:
        with sync_playwright() as pw:
            try:
                browser = launch_chromium(pw)
            except Exception as exc:
                msg = str(exc)
                if "Executable doesn't exist" in msg or "playwright install" in msg:
                    return {"offers": [], "error": "Playwright: τρέξε 'playwright install chromium'"}
                return {"offers": [], "error": f"Playwright: {msg[:100]}"}
            ctx = browser.new_context(user_agent=_UA, locale="el-GR")
            page = ctx.new_page()
            try:
                page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
                raw = page.evaluate(_SKROUTZ_OFFERS_JS, sku)
            finally:
                try:
                    page.close()
                except Exception:
                    pass
                browser.close()
    except Exception as exc:
        return {"offers": [], "error": f"Skroutz: {str(exc)[:120]}"}

    offers = []
    for o in raw or []:
        if not isinstance(o, dict):
            continue
        price = to_float(o.get("price"))
        delivery = (o.get("delivery") or "").strip()
        shipping = total = None
        if "δωρεάν μεταφορικ" in delivery.lower():
            shipping = 0.0
            total = price
            delivery = re.sub(r"\s*Δωρεάν μεταφορικά\s*", "", delivery).strip()
        offers.append({
            "source": "Skroutz",
            "merchant_name": o.get("shop") or "Κατάστημα",
            "merchant_rating": to_float((o.get("rating") or "").replace(",", ".")),
            "merchant_rating_count": o.get("rating_count"),
            "item_price": price, "shipping_price": shipping, "total_price": total,
            "availability": "", "delivery_estimate": delivery,
            "offer_url": o.get("url") or "", "currency": "EUR",
        })
    offers.sort(key=lambda x: (x["item_price"] is None, x["item_price"] or 9e9))
    return {"offers": offers, "count": len(offers)}


# --- e-shop.gr: server-rendered (χωρίς browser). Κωδικοποίηση iso-8859-7. --- #
_ESHOP_TITLE_RE = re.compile(
    r"<a href='(https://www\.e-shop\.gr/[^']*?-p-(PER\.\d+))'[^>]*>([^<]{6,})</a>")
_ESHOP_PRICE_RE = re.compile(r"<b>\s*([\d.,]+)\s*&euro;")


def _parse_eshop(html, limit=20):
    rows, seen = [], set()
    for m in _ESHOP_TITLE_RE.finditer(html):
        url, pid, title = m.group(1), m.group(2), m.group(3)
        if pid in seen:
            continue
        seen.add(pid)
        pm = _ESHOP_PRICE_RE.search(html, m.end(), m.end() + 500)
        price = to_float(pm.group(1)) if pm else None
        title = unescape(title).strip()
        img = f"https://www.e-shop.gr/images/PER/SMALL/{pid}.jpg"
        rows.append({
            "source": "e-shop.gr", "product_id": "", "title": title, "image": img,
            "price_from": price, "offer_count": 1, "rating": None, "product_url": url,
            "_direct": {"merchant_name": "e-shop.gr", "title": title, "price": price,
                        "url": url, "availability": "", "currency": "EUR", "image": img,
                        "rating": None, "rating_count": None, "source": "e-shop.gr"}})
        if len(rows) >= limit:
            break
    return rows


def eshop_search(query):
    url = "https://www.e-shop.gr/search?" + urllib.parse.urlencode({"q": query})
    try:
        html = http_get(url, timeout=20, encoding="iso-8859-7")
    except urllib.error.HTTPError as exc:
        return [], f"e-shop.gr: HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return [], f"e-shop.gr: δεν συνδέθηκε ({exc.reason})"
    except Exception as exc:
        return [], f"e-shop.gr: {exc}"
    rows = _parse_eshop(html)
    if rows:
        return rows, f"e-shop.gr: {len(rows)} προϊόντα"
    return [], "e-shop.gr: δεν βρέθηκαν προϊόντα"


# --- Σούπερ Μάρκετ: επίσημο API posokanei.gov.gr (ex e-Katanalotis) --- #
SUPERMARKET_API = "https://api.posokanei.gov.gr/products/search"
SUPERMARKET_LABEL = "Σούπερ Μάρκετ"

def _norm_txt(s):
    """Πεζά + αφαίρεση τόνων/διακριτικών, για σύγκριση ονομάτων."""
    s = unicodedata.normalize("NFD", str(s or "").casefold())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def title_matches_exact(title, query):
    """True αν ο τίτλος περιέχει ΟΛΕΣ τις λέξεις του ερωτήματος (π.χ. 'milko'
    κρατά τα MILKO, κόβει τα MISKO)."""
    nt = _norm_txt(title)
    toks = [t for t in _norm_txt(query).split() if t]
    return bool(toks) and all(t in nt for t in toks)


POLITEIA_LABEL = "Πολιτεία"

# Κατηγορίες αναζήτησης: ξεχωρίζουν τεχνολογία / τρόφιμα / βιβλία.
MODE_SOURCES = {
    "tech": ["BestPrice", "Skroutz", "Public", "e-shop.gr"],
    "super": [SUPERMARKET_LABEL],
    "books": ["BestPrice", "Skroutz", "Public", POLITEIA_LABEL],
}
MODE_LABELS = {"tech": "🖥 Τεχνολογία / Ηλεκτρονικά", "super": "🛒 Σούπερ Μάρκετ",
               "books": "📚 Βιβλία"}


def http_post_json(url, payload, timeout=20, extra_headers=None):
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "User-Agent": _UA}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _sm_unit_text(price_normalized, unit):
    pn = to_float(price_normalized)
    if pn is None:
        return ""
    return f"€{pn:.2f}/{unit}" if unit else f"€{pn:.2f}"


_SM_API_JS = """
async (title) => {
  const r = await fetch("https://api.posokanei.gov.gr/products/search", {
    method: "POST",
    headers: {"Content-Type": "application/json", "Accept": "application/json"},
    body: JSON.stringify({title})
  });
  if (!r.ok) return {__error: "HTTP " + r.status};
  try { return await r.json(); }
  catch (e) { return {__error: "parse " + e}; }
}
"""


def _supermarket_api_playwright(query):
    """Fallback: καλεί το κρατικό API μέσα από πραγματικό Chromium (Playwright),
    ώστε να περάσει τυχόν προστασία bot (Cloudflare). Επιστρέφει (data, error)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None, PLAYWRIGHT_HINT
    try:
        with sync_playwright() as pw:
            try:
                browser = launch_chromium(pw)
            except Exception as exc:
                msg = str(exc)
                if "Executable doesn't exist" in msg or "playwright install" in msg:
                    return None, "Playwright: τρέξε 'playwright install chromium'"
                return None, f"Playwright: {msg[:100]}"
            ctx = browser.new_context(user_agent=_UA, locale="el-GR")
            page = ctx.new_page()
            data = None
            try:
                page.goto("https://posokanei.gov.gr/", wait_until="domcontentloaded",
                          timeout=30000)
                data = page.evaluate(_SM_API_JS, query)
            finally:
                try:
                    page.close()
                except Exception:
                    pass
                browser.close()
    except Exception as exc:
        return None, f"Σούπερ Μάρκετ: {str(exc)[:120]}"
    if isinstance(data, dict) and data.get("__error"):
        return None, f"Σούπερ Μάρκετ: {data['__error']}"
    return data, None


def supermarket_search(query, limit=25):
    """Τιμές προϊόντων σε όλα τα σούπερ μάρκετ (επίσημο κρατικό API).

    Δοκιμάζει πρώτα απλό HTTP· αν το API μπλοκάρει (403/σύνδεση), ξαναδοκιμάζει
    μέσα από πραγματικό browser (Playwright), που περνά την προστασία bot."""
    data = None
    need_browser = False
    try:
        data = http_post_json(SUPERMARKET_API, {"title": query},
                              extra_headers={"Origin": "https://posokanei.gov.gr",
                                             "Referer": "https://posokanei.gov.gr/"})
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 429):
            need_browser = True
        else:
            return [], f"{SUPERMARKET_LABEL}: HTTP {exc.code}"
    except urllib.error.URLError:
        need_browser = True
    except Exception as exc:
        return [], f"{SUPERMARKET_LABEL}: {exc}"
    if need_browser:
        if not playwright_available():
            return [], (f"{SUPERMARKET_LABEL}: το API μπλοκάρει απευθείας κλήσεις — "
                        f"{PLAYWRIGHT_HINT}")
        data, err = _supermarket_api_playwright(query)
        if err:
            return [], err
    products = data.get("products") if isinstance(data, dict) else None
    if not isinstance(products, list):
        return [], f"{SUPERMARKET_LABEL}: μη αναγνωρίσιμη απάντηση"
    rows = []
    for p in products[:limit]:
        if not isinstance(p, dict):
            continue
        stats = p.get("price_stats") or {}
        unit = p.get("unit") or ""
        offers = []
        for o in p.get("retailer_prices") or []:
            if not isinstance(o, dict):
                continue
            price = to_float(o.get("price"))
            upd = str(o.get("last_updated") or "")[:10]
            disc = o.get("discount_percentage")
            if o.get("is_discount") and disc:
                extra = f"-{disc}%"
            elif len(upd) == 10:
                extra = f"ενημ. {upd[8:10]}/{upd[5:7]}"
            else:
                extra = ""
            offers.append({
                "source": SUPERMARKET_LABEL,
                "merchant_name": o.get("retailer_display_name") or o.get("retailer") or "Κατάστημα",
                "merchant_rating": None, "merchant_rating_count": None,
                "item_price": price, "shipping_price": None, "total_price": None,
                "availability": _sm_unit_text(o.get("price_normalized"), unit),
                "delivery_estimate": extra, "offer_url": "", "currency": "EUR"})
        offers.sort(key=lambda x: (x["item_price"] is None, x["item_price"] or 9e9))
        rows.append({
            "source": SUPERMARKET_LABEL, "product_id": "",
            "title": p.get("name") or "", "image": p.get("image_url") or "",
            "price_from": to_float(stats.get("min_price")),
            "offer_count": stats.get("retailer_count") or len(offers),
            "rating": None, "product_url": "", "_sm_offers": offers})
    return rows, f"{SUPERMARKET_LABEL}: {len(rows)} προϊόντα"


_POLITEIA_SEARCH_URL = "https://www.politeianet.gr/el/search-results?query={q}"
_POLITEIA_PARSE_JS = r"""
() => {
  const out = [], seen = new Set();
  for (const c of document.querySelectorAll('.product-card')) {
    const a = c.querySelector('a[href*="/products/"]');
    if (!a) continue;
    const url = a.href; if (seen.has(url)) continue; seen.add(url);
    const img = c.querySelector('img');
    let title = '';
    const te = c.querySelector('[class*="title"], [class*="Title"], h2, h3');
    if (te) title = te.textContent.trim();
    if (!title && img) title = (img.alt || '').trim();
    if (!title) title = a.textContent.trim();
    title = title.split(/Κωδ\.?\s*Πολιτείας/)[0].trim();
    const pr = [...c.querySelectorAll('*')]
      .filter(e => e.children.length === 0 && /\d+[\.,]\d{2}\s*€/.test(e.textContent))
      .map(e => parseFloat(e.textContent.replace(/[^\d,\.]/g, '').replace(',', '.')))
      .filter(n => isFinite(n));
    const price = pr.length ? Math.min(...pr) : null;
    let image = (img && (img.getAttribute('data-src') || img.src)) || '';
    if (/loading-puff|\.svg($|\?)/.test(image)) image = '';
    out.push({title: title.slice(0, 120), price, url, image});
  }
  return out;
};
"""


def politeia_search(query, limit=25):
    """Αναζήτηση βιβλίων στο politeianet.gr (React SPA → Playwright scraping)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return [], f"{POLITEIA_LABEL}: {PLAYWRIGHT_HINT}"
    url = _POLITEIA_SEARCH_URL.format(q=urllib.parse.quote(query))
    raw = None
    try:
        with sync_playwright() as pw:
            try:
                browser = launch_chromium(pw)
            except Exception as exc:
                msg = str(exc)
                if "Executable doesn't exist" in msg or "playwright install" in msg:
                    return [], "Πολιτεία: τρέξε 'playwright install chromium'"
                return [], f"Πολιτεία: {msg[:100]}"
            ctx = browser.new_context(user_agent=_UA, locale="el-GR",
                                      viewport={"width": 1366, "height": 900})
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_selector(".product-card", timeout=12000)
                    page.wait_for_timeout(1200)
                except Exception:
                    pass
                raw = page.evaluate(_POLITEIA_PARSE_JS)
            finally:
                try:
                    page.close()
                except Exception:
                    pass
                browser.close()
    except Exception as exc:
        return [], f"{POLITEIA_LABEL}: {str(exc)[:120]}"
    rows = []
    for it in (raw or [])[:limit]:
        if not isinstance(it, dict):
            continue
        price = to_float(it.get("price"))
        purl = it.get("url") or ""
        rows.append({
            "source": POLITEIA_LABEL, "product_id": "",
            "title": it.get("title") or "", "image": it.get("image") or "",
            "price_from": price, "offer_count": 1, "rating": None,
            "product_url": purl,
            "_direct": {"source": POLITEIA_LABEL, "merchant_name": POLITEIA_LABEL,
                        "price": price, "url": purl, "availability": "",
                        "rating": None, "currency": "EUR"}})
    return rows, (f"{POLITEIA_LABEL}: {len(rows)} βιβλία" if rows
                  else f"{POLITEIA_LABEL}: δεν βρέθηκαν (ίσως άλλαξε η σελίδα)")


def search_shops(query, labels):
    """Επιστρέφει (rows, diagnostics). Skroutz/Public/Πολιτεία → Playwright·
    e-shop.gr & Σούπερ Μάρκετ → HTTP/API· τα υπόλοιπα → ειλικρινές μήνυμα."""
    results, diags = [], []
    pw = [l for l in labels if l in PLAYWRIGHT_SEARCH]
    http_simple = {"e-shop.gr", SUPERMARKET_LABEL, POLITEIA_LABEL}
    others = [l for l in labels if l not in PLAYWRIGHT_SEARCH and l not in http_simple]
    if pw:
        if not playwright_available():
            diags.extend(f"{l}: {PLAYWRIGHT_HINT}" for l in pw)
        else:
            r, d = playwright_search_all(pw, query)
            results.extend(r)
            diags.extend(d)
    if "e-shop.gr" in labels:
        r, diag = eshop_search(query)
        results.extend(r)
        diags.append(diag)
    if SUPERMARKET_LABEL in labels:
        r, diag = supermarket_search(query)
        results.extend(r)
        diags.append(diag)
    if POLITEIA_LABEL in labels:
        r, diag = politeia_search(query)
        results.extend(r)
        diags.append(diag)
    for l in others:
        if l in UNSUPPORTED_SHOPS:
            diags.append(f"{l}: ειδικό frontend — δεν υποστηρίζεται ακόμη")
        else:
            diags.append(f"{l}: μη υποστηριζόμενο")
    return results, diags


BESTPRICE = BestPriceSource()


def format_history(data):
    """Μορφοποιεί το get_price_history του BestPrice σε αναγνώσιμο κείμενο."""
    if not isinstance(data, dict):
        return str(data)
    if "text" in data and isinstance(data["text"], str):
        return data["text"]
    lines = []
    title = data.get("product_title") or ""
    if title:
        lines.append(title)
    cur = to_float(data.get("current_price"))
    period = data.get("period_days")
    if cur is not None:
        lines.append(f"Τρέχουσα τιμή: {price_text(cur)}")
    if period:
        lines.append(f"Περίοδος ανάλυσης: {period} ημέρες")
    lines.append("")
    windows = data.get("window_stats") or data.get("windows") or []
    if isinstance(windows, list) and windows:
        lines.append("Ανά παράθυρο:")
        for w in windows:
            if not isinstance(w, dict):
                continue
            d = w.get("days", "?")
            mn = to_float(w.get("minimum_price") or w.get("min_price"))
            md = to_float(w.get("median_price") or w.get("median"))
            mx = to_float(w.get("maximum_price") or w.get("max_price"))
            parts = [f"  • {d} ημέρες:"]
            if mn is not None:
                parts.append(f"ελάχ. {price_text(mn)}")
            if md is not None:
                parts.append(f"διάμεσος {price_text(md)}")
            if mx is not None:
                parts.append(f"μέγ. {price_text(mx)}")
            lines.append(" ".join(parts))
            # Ετυμηγορία έναντι διαμέσου
            if cur is not None and md is not None:
                diff = cur - md
                pct = (diff / md * 100) if md else 0
                if diff <= -0.01:
                    verdict = f"καλή τιμή — {abs(pct):.0f}% κάτω από τη διάμεσο ✓"
                elif diff >= 0.01:
                    verdict = f"{pct:.0f}% πάνω από τη διάμεσο"
                else:
                    verdict = "στη διάμεσο"
                lines.append(f"      → {verdict}")
    low = to_float(data.get("lowest_ever") or data.get("all_time_low"))
    if low is not None:
        lines.append("")
        lines.append(f"Χαμηλότερη καταγεγραμμένη: {price_text(low)}")
    url = data.get("bestprice_url")
    if isinstance(url, str) and url.startswith("http"):
        lines.append("")
        lines.append("Σύνδεσμος BestPrice:")
        lines.append(url)
    return "\n".join(lines) if lines else json.dumps(data, ensure_ascii=False, indent=2)


def format_decision(data):
    """Μορφοποιεί το get_shopping_decision του BestPrice σε αναγνώσιμο κείμενο."""
    if not isinstance(data, dict):
        return str(data)
    if "text" in data and isinstance(data["text"], str):
        return data["text"]
    lines = []
    answer = (data.get("answer") or "").strip()
    message = (data.get("message") or "").strip()
    if answer:
        lines.append(answer)
    if message and message != answer:
        if lines:
            lines.append("")
        lines.append(message)
    # Προτεινόμενα / εναλλακτικά προϊόντα
    products = data.get("products") or data.get("alternatives") or []
    if isinstance(products, list) and products:
        lines.append("")
        lines.append("Προτάσεις:")
        for pr in products[:8]:
            if not isinstance(pr, dict):
                continue
            t = first(pr, "title", "name", "product_title", default="")
            pc = to_float(first(pr, "price", "price_from", "current_price", default=None))
            lines.append(f"  • {t}" + (f" — {price_text(pc)}" if pc is not None else ""))
    # Λόγος / beta περιορισμός — εμφανίζεται και όταν υπάρχει μήνυμα
    reason = data.get("reason") or (data.get("status") if data.get("status") in
                                    ("no_match", "unsupported_beta_category") else "")
    notes = {
        "unsupported_beta_category": "Σημείωση: η «Σύσταση αγοράς» του BestPrice είναι σε beta και "
                                     "υποστηρίζει περιορισμένες κατηγορίες. Δοκίμασε πιο συγκεκριμένη "
                                     "διατύπωση με κατηγορία και κριτήρια (π.χ. «SSD NVMe 1TB έως 220€»).",
        "catalog_family_mismatch": "Σημείωση: η διατύπωση δεν ταίριαξε σε κατηγορία καταλόγου. "
                                    "Ξαναδιατύπωσε με σαφή κατηγορία προϊόντος.",
    }
    if not lines and reason:
        lines.append(f"Το BestPrice δεν έδωσε σύσταση (λόγος: {reason}).")
    if reason in notes:
        if lines:
            lines.append("")
        lines.append(notes[reason])
    return "\n".join(lines) if lines else json.dumps(data, ensure_ascii=False, indent=2)


# ============================ GUI ============================ #
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {VERSION}")
        self.geometry("1200x780")
        self.minsize(1000, 640)
        self.products = []
        self.offers_data = []
        self.current_product = None
        self.cart = self._load_cart()
        self.cart_win = None
        self.COL = {
            "bg": "#eef2f8", "panel": "#ffffff", "ink": "#172033", "muted": "#64748b",
            "accent": "#2563eb", "accent_dark": "#1d4ed8", "stripe": "#f4f7fc",
            "head": "#e8eef8", "status": "#e3e9f3", "line": "#d7deea",
            "hdr": "#1e3a8a", "hdr_sub": "#c7d6f5",
        }
        self.configure(bg=self.COL["bg"])
        self.mode = "tech"
        self._setup_style()
        self._build()
        self._render_inline_cart()
        self._refresh_cart_btn()
        self.after(250, self._choose_mode)

    def report_callback_exception(self, exc, val, tb):
        """Κανένα σφάλμα σε κουμπί να μη χάνεται σιωπηλά: log + μήνυμα."""
        try:
            import traceback as _tb
            msg = "".join(_tb.format_exception(exc, val, tb))
            with open(os.path.join(HERE, "app_debug.log"), "a", encoding="utf-8") as fh:
                fh.write("\n--- callback error ---\n" + msg + "\n")
        except Exception:
            pass
        try:
            messagebox.showerror("Σφάλμα", str(val))
        except Exception:
            pass

    def _setup_style(self):
        c = self.COL
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure(".", font=("Segoe UI", 10), background=c["bg"], foreground=c["ink"])
        st.configure("TFrame", background=c["bg"])
        st.configure("TLabel", background=c["bg"], foreground=c["ink"])
        st.configure("Muted.TLabel", background=c["bg"], foreground=c["muted"])
        st.configure("Title.TLabel", background=c["bg"], foreground=c["ink"],
                     font=("Segoe UI Semibold", 20))
        st.configure("TLabelframe", background=c["bg"], borderwidth=0)
        st.configure("TLabelframe.Label", background=c["bg"], foreground=c["muted"],
                     font=("Segoe UI Semibold", 10))
        st.configure("TCheckbutton", background=c["bg"])
        st.map("TCheckbutton", background=[("active", c["bg"])])
        st.configure("TButton", padding=(10, 6), font=("Segoe UI", 10))
        st.map("TButton", background=[("active", "#dde3ee")])
        st.configure("Accent.TButton", padding=(16, 6), font=("Segoe UI Semibold", 10),
                     background=c["accent"], foreground="white", borderwidth=0)
        st.map("Accent.TButton",
               background=[("active", c["accent_dark"]), ("pressed", c["accent_dark"])],
               foreground=[("disabled", "#cdd9f0")])
        st.configure("TEntry", padding=5, fieldbackground="white")
        st.configure("TCombobox", padding=4, fieldbackground="white")
        st.configure("Treeview", rowheight=31, font=("Segoe UI", 10),
                     background="white", fieldbackground="white",
                     borderwidth=1, bordercolor=c["line"])
        st.configure("Treeview.Heading", font=("Segoe UI Semibold", 10),
                     background=c["head"], foreground="#334155", relief="flat",
                     padding=(8, 7), borderwidth=0)
        st.map("Treeview.Heading", background=[("active", c["line"])],
               foreground=[("active", c["accent_dark"])])
        st.map("Treeview", background=[("selected", c["accent"])],
               foreground=[("selected", "white")])
        st.configure("Status.TLabel", background=c["status"], foreground="#374151", padding=7)
        st.configure("Accent.Horizontal.TProgressbar", background=c["accent"],
                     troughcolor=c["head"], borderwidth=0, thickness=6)

    def _build(self):
        c = self.COL
        # --- Μπάρα τίτλου (header) --- #
        header = tk.Frame(self, bg=c["hdr"])
        header.pack(side="top", fill="x")
        hin = tk.Frame(header, bg=c["hdr"])
        hin.pack(fill="x", padx=18, pady=(10, 11))
        tk.Label(hin, text="⚡  " + APP_NAME, bg=c["hdr"], fg="white",
                 font=("Segoe UI Semibold", 18)).pack(anchor="w")
        note = ("Διάλεξε κατηγορία, γράψε προϊόν και πάτησε Αναζήτηση  ·  διπλό κλικ σε προϊόν "
                "→ όλα τα καταστήματα  ·  Τ.Κ. για μεταφορικά/σύνολο (BestPrice)")
        tk.Label(hin, text=note, bg=c["hdr"], fg=c["hdr_sub"],
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        outer = ttk.Frame(self, padding=(14, 12, 14, 10))
        outer.pack(fill="both", expand=True)

        # --- Σειρά αναζήτησης --- #
        row = ttk.Frame(outer)
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text="Προϊόν").pack(side="left")
        self.query = tk.StringVar(value="Samsung 990 PRO 1TB")
        entry = ttk.Entry(row, textvariable=self.query, font=("Segoe UI", 11))
        entry.pack(side="left", fill="x", expand=True, padx=8)
        entry.bind("<Return>", lambda _e: self.search())
        self.q_entry = entry
        self.clear_btn = ttk.Button(row, text="✕", width=3, command=self.clear_query)
        self.clear_btn.pack(side="left", padx=(0, 6))
        self.search_btn = ttk.Button(row, text="Αναζήτηση", command=self.search, style="Accent.TButton")
        self.search_btn.pack(side="left")
        self.exact_btn = ttk.Button(row, text="Ακριβές όνομα",
                                    command=lambda: self.search(exact=True))
        self.exact_btn.pack(side="left", padx=(6, 0))
        ttk.Label(row, text="Τ.Κ.").pack(side="left", padx=(16, 4))
        self.postal = tk.StringVar()
        ttk.Entry(row, textvariable=self.postal, width=8).pack(side="left")

        # --- Σειρά άμεσου συνδέσμου --- #
        urlrow = ttk.Frame(outer)
        urlrow.pack(fill="x", pady=(6, 6))
        ttk.Label(urlrow, text="Σύνδεσμος προϊόντος").pack(side="left")
        self.url_var = tk.StringVar()
        uentry = ttk.Entry(urlrow, textvariable=self.url_var, font=("Segoe UI", 10))
        uentry.pack(side="left", fill="x", expand=True, padx=8)
        uentry.bind("<Return>", lambda _e: self.fetch_url())
        ttk.Button(urlrow, text="Άντληση", command=self.fetch_url).pack(side="left")

        # --- Κατηγορία + πηγές (δυναμικά ανά κατηγορία) --- #
        self.srow = ttk.Frame(outer)
        self.srow.pack(fill="x", pady=(2, 10))
        self.source_vars = {}
        self._rebuild_sources()

        # --- Κεντρική περιοχή: αριστερά οι πίνακες, δεξιά (πλήρες ύψος) φωτο + καλάθι ---
        main = ttk.Frame(outer)
        main.pack(fill="both", expand=True)

        # Δεξιά στήλη: φωτογραφία πάνω, καλάθι κάτω — πιάνει ΟΛΟ το ύψος.
        side = ttk.Frame(main, width=265)
        side.pack(side="right", fill="y", padx=(10, 0))
        side.pack_propagate(False)
        imgtop = ttk.Frame(side, height=210)
        imgtop.pack(side="top", fill="x")
        imgtop.pack_propagate(False)
        self.img_label = ttk.Label(imgtop, anchor="center", justify="center",
                                   background="white", relief="solid", borderwidth=1,
                                   cursor=("hand2" if _HAS_PIL else ""),
                                   text=("Επίλεξε προϊόν\nγια φωτογραφία" if _HAS_PIL
                                         else "Φωτογραφίες:\nχρειάζεται Pillow\n(δες README)"))
        self.img_label.pack(fill="both", expand=True)
        self.img_label.bind("<Button-1>", lambda _e: self._open_image_window())
        self._cur_image_url = ""
        if _HAS_PIL:
            ttk.Label(side, text="κλικ για μεγέθυνση", style="Muted.TLabel",
                      anchor="center").pack(side="top", fill="x", pady=(2, 6))
        self._img_cache = {}
        self._img_ref = None
        # --- Καλάθι inline (κάτω από τη φωτογραφία, πλήρες ύψος) ---
        cartf = ttk.LabelFrame(side, text=" 🛒 Καλάθι ", padding=6)
        cartf.pack(side="top", fill="both", expand=True)
        self.cart_total_inline = ttk.Label(cartf, text="Άδειο",
                                            font=("Segoe UI", 9, "bold"), anchor="w")
        self.cart_total_inline.pack(fill="x")
        cb = ttk.Frame(cartf)
        cb.pack(side="bottom", fill="x", pady=(4, 0))
        ttk.Button(cb, text="＋", width=2, command=lambda: self._inline_qty(+1)).pack(side="left")
        ttk.Button(cb, text="－", width=2, command=lambda: self._inline_qty(-1)).pack(side="left", padx=(2, 6))
        ttk.Button(cb, text="🗑", width=3, command=self._inline_remove).pack(side="left")
        ttk.Button(cb, text="Καθάρ.", command=self._cart_clear).pack(side="right")
        cb2 = ttk.Frame(cartf)
        cb2.pack(side="bottom", fill="x", pady=(6, 2))
        ttk.Button(cb2, text="Παράθυρο", command=self.open_cart).pack(side="left")
        ttk.Button(cb2, text="CSV", width=5, command=self._cart_export).pack(side="right")
        lbf = ttk.Frame(cartf)
        lbf.pack(side="top", fill="both", expand=True, pady=(4, 4))
        self.cart_list = tk.Listbox(lbf, activestyle="none",
                                    font=("Segoe UI", 9), borderwidth=1, relief="solid",
                                    highlightthickness=0)
        csb = ttk.Scrollbar(lbf, orient="vertical", command=self.cart_list.yview)
        self.cart_list.configure(yscrollcommand=csb.set)
        self.cart_list.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")
        self.cart_list.bind("<Double-1>", lambda _e: self._inline_open_link())

        # Αριστερά: κάθετο paned με τους δύο πίνακες
        paned = ttk.Panedwindow(main, orient="vertical")
        paned.pack(side="left", fill="both", expand=True)
        pframe = ttk.LabelFrame(paned, text="  ΠΡΟΪΟΝΤΑ — διπλό κλικ για τα καταστήματα", padding=8)
        oframe = ttk.LabelFrame(paned, text="  ΚΑΤΑΣΤΗΜΑΤΑ / ΠΡΟΣΦΟΡΕΣ", padding=8)
        paned.add(pframe, weight=2)
        paned.add(oframe, weight=3)

        # Πίνακας προϊόντων
        self._pcols = [("source", "Πηγή", 100, "w"), ("title", "Προϊόν", 340, "w"),
                       ("price", "Από", 90, "e"), ("count", "Καταστήματα", 100, "center"),
                       ("rating", "Βαθμ.", 70, "center"), ("id", "Product ID", 140, "w")]
        self.ptree = self._tree(pframe, self._pcols)
        self.ptree.bind("<Double-1>", lambda _e: self.load_offers())
        self.ptree.bind("<<TreeviewSelect>>", self._on_product_select)
        # Ταξινόμηση ανά στήλη (κλικ στην κεφαλίδα)
        self._psort_col, self._psort_rev = None, False
        for key, label, _w, _a in self._pcols:
            self.ptree.heading(key, command=lambda c=key: self._sort_products(c))

        btnrow = ttk.Frame(oframe)
        btnrow.pack(fill="x", pady=(0, 6))
        ttk.Label(btnrow, text="Ταξινόμηση").pack(side="left")
        self.sort_choice = tk.StringVar(value="Τιμή ↑")
        box = ttk.Combobox(btnrow, textvariable=self.sort_choice, state="readonly", width=20,
                           values=("Τιμή ↑", "Συνολικό κόστος ↑", "Αξιολόγηση ↓",
                                   "Ταχύτερη παράδοση", "Κατάστημα Α–Ω"))
        box.pack(side="left", padx=6)
        box.bind("<<ComboboxSelected>>", lambda _e: self.render_offers())
        ttk.Button(btnrow, text="➕ Στο καλάθι", command=self.add_to_cart).pack(side="left", padx=(12, 2))
        ttk.Button(btnrow, text="📈 Ιστορικό τιμής", command=self.show_history).pack(side="left", padx=(12, 2))
        ttk.Button(btnrow, text="💡 Σύσταση αγοράς", command=self.show_decision).pack(side="left", padx=2)
        self.offer_count_label = ttk.Label(btnrow, text="", style="Muted.TLabel")
        self.offer_count_label.pack(side="right")
        self.otree = self._tree(oframe, [
            ("shop", "Κατάστημα", 200, "w"), ("price", "Τιμή", 95, "e"),
            ("stock", "Διαθεσιμότητα", 150, "w"), ("delivery", "Παράδοση", 150, "w"),
            ("rating", "Αξιολόγηση", 110, "center"), ("shipping", "Μεταφορικά", 100, "e"),
            ("total", "Σύνολο", 100, "e")])
        self.otree.bind("<Double-1>", lambda _e: self.open_offer())

        # Ρίγες (zebra) και στα δύο tables
        for t in (self.ptree, self.otree):
            t.tag_configure("odd", background=self.COL["stripe"])
            t.tag_configure("even", background="white")

        # --- Πόδι: γραμμή κατάστασης — καρφωμένη ΚΑΤΩ, πάντα ορατή --- #
        foot = ttk.Frame(outer)
        foot.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(foot, mode="indeterminate",
                                        style="Accent.Horizontal.TProgressbar")
        self.status = tk.StringVar(value="Έτοιμο. Γράψε προϊόν και πάτησε Αναζήτηση, ή επικόλλησε σύνδεσμο.")
        self.status_label = ttk.Label(foot, textvariable=self.status, style="Status.TLabel", anchor="w")
        self.status_label.pack(fill="x")

        # --- Κουμπιά ενεργειών — πάνω από τη γραμμή κατάστασης, πάντα ορατά --- #
        bottom = ttk.Frame(outer)
        bottom.pack(side="bottom", fill="x", pady=(10, 6))
        self.compare_btn = ttk.Button(bottom, text="Σύγκριση προσφορών", command=self.load_offers)
        self.compare_btn.pack(side="left")
        ttk.Button(bottom, text="Άνοιγμα συνδέσμου", command=self.open_offer).pack(side="left", padx=6)
        ttk.Button(bottom, text="Εξαγωγή CSV", command=self.export_csv).pack(side="left")
        self.cart_btn = ttk.Button(bottom, text="🛒 Καλάθι", command=self.open_cart,
                                   style="Accent.TButton")
        self.cart_btn.pack(side="right")

    # ---- κατηγορία (τεχνολογία / σούπερ μάρκετ) ---- #
    def _rebuild_sources(self):
        for w in self.srow.winfo_children():
            w.destroy()
        ttk.Label(self.srow, text="Κατηγορία:").pack(side="left")
        ttk.Button(self.srow, text=MODE_LABELS[self.mode] + "  ▾",
                   command=self._choose_mode).pack(side="left", padx=(6, 16))
        ttk.Label(self.srow, text="Πηγές:", style="Muted.TLabel").pack(side="left")
        for label in MODE_SOURCES[self.mode]:
            var = self.source_vars.get(label) or tk.BooleanVar(value=True)
            self.source_vars[label] = var
            ttk.Checkbutton(self.srow, text=label, variable=var).pack(side="left", padx=5)

    def _choose_mode(self):
        dlg = tk.Toplevel(self)
        dlg.title("Τι ψάχνεις;")
        dlg.configure(bg="white")
        dlg.resizable(False, False)
        dlg.transient(self)
        ttk.Label(dlg, text="Τι είδους προϊόντα ψάχνεις;",
                  font=("Segoe UI Semibold", 13), background="white").pack(padx=28, pady=(22, 6))
        ttk.Label(dlg, text="(για να μην μπλέκονται ηλεκτρονικά με τρόφιμα)",
                  style="Muted.TLabel", background="white").pack(padx=28)
        box = tk.Frame(dlg, bg="white")
        box.pack(padx=28, pady=20)

        def pick(m):
            self.mode = m
            self._rebuild_sources()
            try:
                dlg.grab_release()
            except Exception:
                pass
            dlg.destroy()

        ttk.Button(box, text=MODE_LABELS["tech"], style="Accent.TButton", width=30,
                   command=lambda: pick("tech")).pack(pady=6)
        ttk.Button(box, text=MODE_LABELS["super"], style="Accent.TButton", width=30,
                   command=lambda: pick("super")).pack(pady=6)
        ttk.Button(box, text=MODE_LABELS["books"], style="Accent.TButton", width=30,
                   command=lambda: pick("books")).pack(pady=6)
        dlg.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - dlg.winfo_width()) // 2)
        y = self.winfo_rooty() + 130
        dlg.geometry(f"+{x}+{y}")
        try:
            dlg.grab_set()
        except Exception:
            pass

    def _set_busy(self, busy):
        """Οπτική ένδειξη ότι τρέχει εργασία: μπάρα προόδου, κέρσορας, γκριζάρισμα."""
        self._busy = busy
        try:
            if busy:
                self.progress.pack(fill="x", pady=(0, 6), before=self.status_label)
                self.progress.start(12)
                self.configure(cursor="watch")
            else:
                self.progress.stop()
                self.progress.pack_forget()
                self.configure(cursor="")
            for b in (getattr(self, "search_btn", None), getattr(self, "exact_btn", None),
                      getattr(self, "compare_btn", None)):
                if b is not None:
                    b.configure(state=("disabled" if busy else "normal"))
        except Exception:
            pass

    def _tree(self, parent, columns):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        keys = [c[0] for c in columns]
        tree = ttk.Treeview(frame, columns=keys, show="headings", selectmode="browse")
        for key, label, width, anchor in columns:
            tree.heading(key, text=label, anchor=("center" if anchor == "center" else "w"))
            tree.column(key, width=width, minwidth=55, anchor=anchor,
                        stretch=(key in ("title", "shop", "stock")))
        y = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=y.set)
        x = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(xscrollcommand=x.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree

    # ---- πίνακας προϊόντων: render / ταξινόμηση / φωτογραφία ---- #
    def _render_product_rows(self):
        self.ptree.delete(*self.ptree.get_children())
        for idx, p in enumerate(self.products):
            self.ptree.insert("", "end", iid=str(idx), tags=("odd" if idx % 2 else "even",), values=(
                first(p, "source", default="—"),
                first(p, "title", default="Χωρίς τίτλο"),
                price_text(first(p, "price_from", default="")),
                first(p, "offer_count", default="—"),
                rating_cell(p.get("rating")),
                first(p, "product_id", default="")))

    def _sort_products(self, col):
        if not self.products:
            return
        keymap = {
            "source": lambda p: str(first(p, "source", default="")).casefold(),
            "title": lambda p: str(first(p, "title", default="")).casefold(),
            "price": lambda p: (to_float(p.get("price_from")) is None, to_float(p.get("price_from")) or 0),
            "count": lambda p: (to_float(p.get("offer_count")) is None, to_float(p.get("offer_count")) or 0),
            "rating": lambda p: (to_float(p.get("rating")) is None, to_float(p.get("rating")) or 0),
            "id": lambda p: str(first(p, "product_id", default="")).casefold(),
        }
        kf = keymap.get(col)
        if not kf:
            return
        self._psort_rev = (not self._psort_rev) if self._psort_col == col else False
        self._psort_col = col
        self.products.sort(key=kf, reverse=self._psort_rev)
        self._render_product_rows()
        arrow = " ▼" if self._psort_rev else " ▲"
        for key, label, _w, _a in self._pcols:
            self.ptree.heading(key, text=label + (arrow if key == col else ""))

    def _on_product_select(self, _e=None):
        sel = self.ptree.selection()
        if not sel:
            return
        try:
            p = self.products[int(sel[0])]
        except (ValueError, IndexError):
            return
        url = first(p, "image", "image_url", default="") or (p.get("_direct") or {}).get("image", "")
        if url:
            self._load_image(url)
            return
        # BestPrice: το search δεν δίνει εικόνα — την παίρνουμε από τη σελίδα προϊόντος.
        pid = first(p, "product_id", default="")
        m = re.search(r"\d+", str(pid))
        if first(p, "source", default="") == "BestPrice" and m and _HAS_PIL:
            self._resolve_bestprice_image(m.group(0), p)
        else:
            self._load_image("")

    def _resolve_bestprice_image(self, num, p):
        self.img_label.configure(image="", text="…")

        def work():
            og = ""
            try:
                html = http_get(f"https://www.bestprice.gr/item/{num}/x.html", timeout=15)
                og = _meta(html, "og:image")
            except Exception:
                og = ""

            def apply():
                p["image"] = og  # cache στο προϊόν
                # εμφάνισε μόνο αν είναι ακόμη επιλεγμένο το ίδιο προϊόν
                sel = self.ptree.selection()
                if sel:
                    try:
                        if self.products[int(sel[0])] is p:
                            self._load_image(og)
                            return
                    except (ValueError, IndexError):
                        pass
            self.after(0, apply)

        threading.Thread(target=work, daemon=True).start()

    def _trim_img_cache(self, cap=48):
        """Κρατάμε φραγμένο αριθμό εικόνων στη μνήμη (κάθε μία είναι Tk resource)."""
        while len(self._img_cache) > cap:
            try:
                del self._img_cache[next(iter(self._img_cache))]
            except (StopIteration, KeyError):
                break

    def _load_image(self, url):
        if not _HAS_PIL:
            return
        self._cur_image_url = url or ""
        # Μάρκα αιτήματος: αγνοεί εικόνες που αργούν ενώ άλλαξε η επιλογή.
        self._img_token = getattr(self, "_img_token", 0) + 1
        token = self._img_token
        if not url:
            self.img_label.configure(image="", text="(χωρίς φωτογραφία)")
            self._img_ref = None
            return
        if url in self._img_cache:
            self._img_ref = self._img_cache[url]
            self.img_label.configure(image=self._img_ref, text="")
            return
        self.img_label.configure(image="", text="…")

        def work():
            try:
                data = http_bytes(url)
                im = Image.open(io.BytesIO(data))
                im.load()
                im.thumbnail((190, 190))
                self.after(0, lambda: self._set_image(url, im, token))
            except Exception:
                self.after(0, lambda: token == self._img_token and
                           self.img_label.configure(image="", text="(φωτο μη διαθέσιμη)"))

        threading.Thread(target=work, daemon=True).start()

    def _set_image(self, url, im, token=None):
        try:
            photo = ImageTk.PhotoImage(im)
            self._img_cache[url] = photo
            self._trim_img_cache()
            if token is not None and token != self._img_token:
                return  # άλλαξε η επιλογή στο μεταξύ — μην εμφανίσεις παλιά εικόνα
            self._img_ref = photo
            self.img_label.configure(image=photo, text="")
        except Exception:
            self.img_label.configure(image="", text="(φωτο μη διαθέσιμη)")

    def _open_image_window(self):
        """Μεγέθυνση φωτογραφίας προϊόντος σε ξεχωριστό παράθυρο."""
        url = getattr(self, "_cur_image_url", "")
        if not url or not _HAS_PIL:
            return
        old = getattr(self, "_imgwin", None)
        if old is not None:
            try:
                old.destroy()
            except Exception:
                pass
        win = tk.Toplevel(self)
        self._imgwin = win
        win.title("Φωτογραφία προϊόντος")
        win.configure(bg="white")
        lbl = tk.Label(win, text="Φόρτωση…", bg="white", fg="#6b7280",
                       font=("Segoe UI", 11))
        lbl.pack(fill="both", expand=True, padx=12, pady=12)
        win.geometry("420x320")

        def work():
            mw = int(self.winfo_screenwidth() * 0.8)
            mh = int(self.winfo_screenheight() * 0.8)
            for u in (big_image_url(url), url):
                try:
                    data = http_bytes(u, timeout=20)
                    im = Image.open(io.BytesIO(data))
                    im.load()
                    im.thumbnail((min(mw, 1100), min(mh, 1100)))
                    self.after(0, lambda im=im: self._set_big_image(win, lbl, im))
                    return
                except Exception:
                    continue
            self.after(0, lambda: lbl.configure(text="(φωτο μη διαθέσιμη)"))

        threading.Thread(target=work, daemon=True).start()

    def _set_big_image(self, win, lbl, im):
        try:
            if not win.winfo_exists():
                return
            photo = ImageTk.PhotoImage(im)
            win._photo = photo  # κράτα αναφορά πάνω στο παράθυρο
            lbl.configure(image=photo, text="")
            win.geometry(f"{im.width + 24}x{im.height + 24}")
            win.bind("<Escape>", lambda _e: win.destroy())
        except Exception:
            lbl.configure(text="(φωτο μη διαθέσιμη)")

    # ---- background worker ---- #
    def run_bg(self, task, done, label):
        self.status.set(label)
        self._set_busy(True)
        result_queue = queue.Queue()

        def work():
            try:
                result_queue.put((True, task()))
            except Exception as exc:
                log_error("WORKER")
                result_queue.put((False, str(exc)))

        def poll():
            try:
                ok, payload = result_queue.get_nowait()
            except queue.Empty:
                self.after(120, poll)
                return
            self._set_busy(False)
            if ok:
                try:
                    done(payload)
                except Exception as exc:
                    log_error("UI CALLBACK")
                    self.status.set("Σφάλμα εμφάνισης: " + str(exc))
            else:
                self.status.set("Αποτυχία: " + payload)
                messagebox.showerror("Σφάλμα", payload + "\n\nΔες app_debug.log για λεπτομέρειες.")

        threading.Thread(target=work, daemon=True).start()
        self.after(120, poll)

    # ---- actions ---- #
    def clear_query(self):
        """Καθαρίζει το πεδίο προϊόντος."""
        self.query.set("")
        try:
            self.q_entry.focus_set()
        except Exception:
            pass

    def search(self, exact=False):
        if getattr(self, "_busy", False):
            return
        query = self.query.get().strip()
        if not query:
            messagebox.showinfo("Αναζήτηση", "Γράψε το προϊόν που θέλεις.")
            return
        self.ptree.delete(*self.ptree.get_children())
        self.otree.delete(*self.otree.get_children())
        selected = [l for l in MODE_SOURCES[self.mode]
                    if self.source_vars.get(l) and self.source_vars[l].get()]
        use_bp = "BestPrice" in selected
        shops = [l for l in selected if l != "BestPrice"]

        def task():
            combined, errors, counts, diags = [], [], {}, []
            if use_bp:
                try:
                    rows = BESTPRICE.search(query)
                    combined.extend(rows)
                    counts["BestPrice"] = len(rows)
                except Exception as exc:
                    errors.append("BestPrice: " + str(exc))
                    counts["BestPrice"] = 0
            if shops:
                shop_rows, shop_diags = search_shops(query, shops)
                combined.extend(shop_rows)
                diags.extend(shop_diags)
                for lbl in shops:
                    counts[lbl] = sum(1 for r in shop_rows if r.get("source") == lbl)
            filtered_out = 0
            if exact:
                before = len(combined)
                combined = [r for r in combined
                            if title_matches_exact(r.get("title", ""), query)
                            or title_matches_exact(r.get("product_url", ""), query)]
                filtered_out = before - len(combined)
                # ξαναμετρά ανά πηγή μετά το φιλτράρισμα
                for k in list(counts):
                    counts[k] = sum(1 for r in combined if r.get("source") == k)
            return combined, errors, counts, diags, filtered_out

        def done(result):
            self.products, errors, counts, diags, filtered_out = result
            self._psort_col, self._psort_rev = None, False
            for key, label, _w, _a in self._pcols:
                self.ptree.heading(key, text=label)
            self._render_product_rows()
            summary = ", ".join(f"{k}: {v}" for k, v in counts.items()) or "καμία πηγή"
            notes = [n for n in (diags + errors) if ":" in n and " 0 προϊόντα" not in n]
            if exact:
                notes.insert(0, f"ακριβές όνομα «{query}»"
                             + (f" (κόπηκαν {filtered_out})" if filtered_out else ""))
            tail = ("  ·  " + " | ".join(notes)) if notes else ""
            self.status.set(f"Αποτελέσματα — {summary}{tail}")
            if not self.products:
                extra = ("\n(Φίλτρο ακριβούς ονόματος — δοκίμασε απλή Αναζήτηση.)"
                         if exact else "")
                messagebox.showinfo("Χωρίς αποτελέσματα",
                                    "Δεν βρέθηκαν προϊόντα.\n"
                                    + "\n".join(diags + errors) + extra)

        label = "⏳ Αναζήτηση…"
        if any(s in PLAYWRIGHT_SEARCH or s == POLITEIA_LABEL for s in shops):
            label += "  (Skroutz/Public/Πολιτεία μέσω browser — μπορεί να αργήσει λίγο)"
        self.run_bg(task, done, label)

    def fetch_url(self):
        if getattr(self, "_busy", False):
            return
        url = self.url_var.get().strip()
        if not url:
            messagebox.showinfo("Σύνδεσμος", "Επικόλλησε έναν σύνδεσμο προϊόντος.")
            return

        def done(prod):
            self.products.append({
                "source": prod.get("merchant_name") or prod.get("source", "Άμεσος σύνδεσμος"),
                "title": prod.get("title", ""), "price_from": prod.get("price"),
                "offer_count": prod.get("offer_count", 1), "rating": prod.get("rating"),
                "image": prod.get("image", ""),
                "product_id": "", "product_url": prod.get("url", ""),
                "_direct": prod})
            self._render_product_rows()
            rc = prod.get("rating_count")
            _r = rating_cell(prod.get("rating"))
            rtxt = (f" · {_r}/5" + (f" ({rc} κριτικές)" if rc else "")) if _r != "—" else ""
            self.status.set(f"{prod.get('merchant_name','')}: {prod.get('title','')} — "
                            f"{price_text(prod.get('price'))}{rtxt}")

        self.run_bg(lambda: fetch_product_url(url), done, f"Άντληση από {shop_label(url)}…")

    def _selected_product(self):
        sel = self.ptree.selection()
        if not sel:
            return None
        return self.products[int(sel[0])]

    def load_offers(self):
        if getattr(self, "_busy", False):
            return
        p = self._selected_product()
        if not p:
            messagebox.showinfo("Προσφορές", "Επίλεξε πρώτα ένα προϊόν.")
            return
        self.current_product = p
        # Προϊόν σούπερ μάρκετ: οι τιμές όλων των αλυσίδων υπάρχουν ήδη.
        if p.get("_sm_offers") is not None:
            self.offers_data = list(p["_sm_offers"])
            self.offer_count_label.configure(
                text=f"{len(self.offers_data)} σούπερ μάρκετ")
            self.render_offers()
            return
        # Προϊόν Skroutz: φέρε ΟΛΑ τα καταστήματα (όπως το BestPrice).
        src = first(p, "source", default="")
        purl = first(p, "product_url", "url", default="")
        if src == "Skroutz" and re.search(r"/s/\d+/", str(purl)):
            def done_sk(res):
                if res.get("error") and not res.get("offers"):
                    messagebox.showinfo("Προσφορές Skroutz", res["error"])
                    return
                self.offers_data = res.get("offers", [])
                self.offer_count_label.configure(
                    text=f"{len(self.offers_data)} καταστήματα (Skroutz)")
                self.render_offers()
            self.run_bg(lambda: skroutz_offers(str(purl)), done_sk,
                        "Φόρτωση καταστημάτων Skroutz…")
            return
        # Αποτέλεσμα καταστήματος / άμεσος σύνδεσμος: μία προσφορά.
        if p.get("_direct"):
            d = dict(p["_direct"])
            # Αν λείπει τιμή αλλά υπάρχει URL, τράβα τη σελίδα προϊόντος για εμπλουτισμό.
            if d.get("price") is None and d.get("url"):
                def enriched(prod):
                    self._show_single_offer({**d, **(prod or {})})
                self.run_bg(lambda: fetch_product_url(d["url"]), enriched,
                            f"Άντληση λεπτομερειών από {d.get('merchant_name','κατάστημα')}…")
                return
            self._show_single_offer(d)
            return
        pid = first(p, "product_id", default="")
        if not pid:
            messagebox.showinfo("Προσφορές", "Αυτό το αποτέλεσμα δεν έχει product_id για σύγκριση. "
                                "Αν προέρχεται από Skroutz, άνοιξε τον σύνδεσμο.")
            return

        def done(offers):
            self.offers_data = offers
            self.offer_count_label.configure(text=f"{len(offers)} μοναδικές προσφορές (έως 10/κλήση)")
            self.render_offers()
            if not offers:
                messagebox.showinfo("Χωρίς προσφορές", "Δεν βρέθηκαν προσφορές για αυτό το προϊόν.")

        self.run_bg(lambda: BESTPRICE.offers(str(pid), self.postal.get()),
                    done, f"Φόρτωση προσφορών για {pid}…")

    def _show_single_offer(self, d):
        self.offers_data = [{
            "source": d.get("source"), "merchant_name": d.get("merchant_name", "Κατάστημα"),
            "merchant_rating": d.get("rating"), "merchant_rating_count": d.get("rating_count"),
            "item_price": d.get("price"), "shipping_price": None, "total_price": None,
            "availability": d.get("availability", ""), "delivery_estimate": "",
            "offer_url": d.get("url", ""), "currency": d.get("currency", "EUR")}]
        self.offer_count_label.configure(text="1 προσφορά (κατάστημα)")
        self.render_offers()

    @staticmethod
    def _delivery_days(value):
        nums = re.findall(r"\d+", str(value or ""))
        return int(nums[0]) if nums else 99999

    def render_offers(self):
        self.otree.delete(*self.otree.get_children())
        offers = list(self.offers_data)
        mode = self.sort_choice.get()
        if mode == "Συνολικό κόστος ↑":
            offers.sort(key=lambda o: (o.get("total_price") is None, o.get("total_price") or float("inf")))
        elif mode == "Αξιολόγηση ↓":
            offers.sort(key=lambda o: (o.get("merchant_rating") is None, -(o.get("merchant_rating") or 0)))
        elif mode == "Ταχύτερη παράδοση":
            offers.sort(key=lambda o: self._delivery_days(o.get("delivery_estimate")))
        elif mode == "Κατάστημα Α–Ω":
            offers.sort(key=lambda o: str(o.get("merchant_name", "")).casefold())
        else:
            offers.sort(key=lambda o: (o.get("item_price") is None, o.get("item_price") or float("inf")))
        self.offers_data = offers
        for idx, o in enumerate(offers):
            rc = o.get("merchant_rating_count")
            rating = (f"{o['merchant_rating']:.1f}" + (f" ({rc})" if rc else "")
                      if o.get("merchant_rating") else "—")
            self.otree.insert("", "end", iid=str(idx), tags=("odd" if idx % 2 else "even",), values=(
                o.get("merchant_name", "—"), price_text(o.get("item_price")),
                availability_text(o.get("availability")),
                availability_text(o.get("delivery_estimate")) if o.get("delivery_estimate") else "—",
                rating,
                price_text(o["shipping_price"]) if isinstance(o.get("shipping_price"), (int, float)) else "Άγνωστα",
                price_text(o["total_price"]) if isinstance(o.get("total_price"), (int, float)) else "—"))

    def open_offer(self):
        sel = self.otree.selection()
        if not sel:
            messagebox.showinfo("Σύνδεσμος", "Επίλεξε πρώτα μια προσφορά.")
            return
        o = self.offers_data[int(sel[0])]
        url = first(o, "offer_url", "url", default="")
        if not url and isinstance(self.current_product, dict):
            url = first(self.current_product, "product_url", "url", default="")
        if url and str(url).startswith(("http://", "https://")):
            webbrowser.open(str(url))
        else:
            messagebox.showinfo("Χωρίς σύνδεσμο", "Η πηγή δεν έδωσε άμεσο σύνδεσμο.")

    def show_history(self):
        p = self.current_product or self._selected_product()
        if not p or not first(p, "product_id", default=""):
            messagebox.showinfo("Ιστορικό τιμής", "Διάλεξε ένα προϊόν BestPrice (με product_id).")
            return
        pid = first(p, "product_id", default="")

        def done(data):
            if data.get("error"):
                messagebox.showinfo("Ιστορικό τιμής", "Δεν βρέθηκε ιστορικό: " + data["error"])
                return
            self._text_window("Ιστορικό τιμής — " + first(p, "title", default=""),
                              format_history(data))

        self.run_bg(lambda: BESTPRICE.price_history(str(pid)), done, "Λήψη ιστορικού τιμής…")

    def show_decision(self):
        query = self.query.get().strip()
        if not query:
            messagebox.showinfo("Σύσταση αγοράς", "Γράψε πρώτα τι ψάχνεις στο πεδίο Προϊόν.")
            return

        def done(data):
            if data.get("error"):
                messagebox.showinfo("Σύσταση αγοράς", "Δεν ήταν δυνατή: " + data["error"])
                return
            self._text_window("Σύσταση αγοράς — " + query, format_decision(data))

        self.run_bg(lambda: BESTPRICE.shopping_decision(query, self.postal.get()),
                    done, "Ανάλυση σύστασης αγοράς…")

    def _text_window(self, title, body):
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("620x440")
        txt = tk.Text(win, wrap="word", font=("Segoe UI", 11), padx=12, pady=12,
                      spacing1=2, spacing3=4)
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", body if isinstance(body, str) else str(body))
        txt.configure(state="disabled")

    # ---- καλάθι αγορών ---- #
    def _cart_path(self):
        return os.path.join(os.path.expanduser("~"), ".greek_price_cart.json")

    def _load_cart(self):
        try:
            with open(self._cart_path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_cart(self):
        try:
            with open(self._cart_path(), "w", encoding="utf-8") as fh:
                json.dump(self.cart, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _refresh_cart_btn(self):
        n = sum(int(it.get("qty", 1)) for it in self.cart)
        try:
            self.cart_btn.configure(text=(f"🛒 Καλάθι ({n})" if n else "🛒 Καλάθι"))
        except Exception:
            pass

    def add_to_cart(self):
        sel = self.otree.selection()
        if not sel:
            messagebox.showinfo("Καλάθι", "Επίλεξε πρώτα μια προσφορά/κατάστημα.")
            return
        o = self.offers_data[int(sel[0])]
        title = self.current_product.get("title", "") if isinstance(self.current_product, dict) else ""
        shop = o.get("merchant_name") or o.get("source") or "Κατάστημα"
        price = o.get("item_price")
        if price is None:
            price = o.get("total_price")
        url = first(o, "offer_url", "url", default="")
        if not url and isinstance(self.current_product, dict):
            url = first(self.current_product, "product_url", "url", default="")
        for it in self.cart:
            if it.get("title") == title and it.get("shop") == shop and it.get("url") == url:
                it["qty"] = int(it.get("qty", 1)) + 1
                break
        else:
            self.cart.append({"title": title, "shop": shop, "price": price,
                              "qty": 1, "url": url})
        self._save_cart()
        self._render_cart()
        self.status.set(f"Προστέθηκε στο καλάθι: {title or shop}")

    def open_cart(self):
        if self.cart_win is not None:
            try:
                if self.cart_win.winfo_exists():
                    self.cart_win.lift()
                    self.cart_win.focus_force()
                    self._render_cart()
                    return
            except Exception:
                pass
        win = tk.Toplevel(self)
        self.cart_win = win
        win.title("🛒 Καλάθι αγορών")
        win.geometry("920x480")
        win.configure(bg=self.COL["bg"])
        win.protocol("WM_DELETE_WINDOW", self._close_cart)
        # Κάτω μπάρα κουμπιών ΠΡΩΤΑ (side=bottom), ώστε να φαίνεται πάντα.
        bar = ttk.Frame(win, padding=(10, 6, 10, 10))
        bar.pack(side="bottom", fill="x")
        ttk.Button(bar, text="＋", width=3, command=lambda: self._cart_qty(+1)).pack(side="left")
        ttk.Button(bar, text="－", width=3, command=lambda: self._cart_qty(-1)).pack(side="left", padx=(4, 12))
        ttk.Button(bar, text="Αφαίρεση", command=self._cart_remove).pack(side="left")
        ttk.Button(bar, text="Καθάρισμα", command=self._cart_clear).pack(side="left", padx=6)
        ttk.Button(bar, text="Άνοιγμα συνδέσμου", command=self._open_cart_link).pack(side="left")
        ttk.Button(bar, text="Εξαγωγή CSV", command=self._cart_export).pack(side="left", padx=6)
        self.cart_total_lbl = ttk.Label(bar, text="", font=("Segoe UI", 11, "bold"))
        self.cart_total_lbl.pack(side="right")
        frame = ttk.Frame(win, padding=10)
        frame.pack(side="top", fill="both", expand=True)
        cols = [("title", "Προϊόν", 320, "w"), ("shop", "Κατάστημα", 150, "w"),
                ("qty", "Ποσ.", 55, "center"), ("price", "Τιμή", 90, "e"),
                ("line", "Σύνολο", 100, "e"), ("url", "Σύνδεσμος", 180, "w")]
        self.ctree = self._tree(frame, cols)
        self.ctree.tag_configure("odd", background=self.COL["stripe"])
        self.ctree.tag_configure("even", background="white")
        self.ctree.bind("<Double-1>", lambda _e: self._open_cart_link())
        self._render_cart()
        # Φέρε το παράθυρο ΜΠΡΟΣΤΑ (αλλιώς στα Windows ανοίγει πίσω από το κύριο).
        try:
            win.update_idletasks()
            x = self.winfo_rootx() + max(0, (self.winfo_width() - 920) // 2)
            y = self.winfo_rooty() + 80
            win.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass
        win.deiconify()
        win.lift()
        win.focus_force()
        try:
            win.attributes("-topmost", True)
            win.after(500, lambda: win.winfo_exists() and win.attributes("-topmost", False))
        except Exception:
            pass

    def _close_cart(self):
        try:
            self.cart_win.destroy()
        except Exception:
            pass
        self.cart_win = None

    def _cart_total(self):
        total = 0.0
        for it in self.cart:
            price = to_float(it.get("price"))
            if price is not None:
                total += price * int(it.get("qty", 1))
        return total

    def _render_cart(self):
        """Ενημερώνει ΚΑΙ το inline καλάθι (δεξιά) ΚΑΙ το παράθυρο (αν είναι ανοιχτό)."""
        self._render_inline_cart()
        try:
            if (getattr(self, "ctree", None) and self.cart_win is not None
                    and self.cart_win.winfo_exists()):
                self._render_cart_window()
        except Exception:
            pass
        self._refresh_cart_btn()

    def _render_inline_cart(self):
        lb = getattr(self, "cart_list", None)
        if lb is None:
            return
        try:
            lb.delete(0, "end")
            for it in self.cart:
                price = to_float(it.get("price"))
                qty = int(it.get("qty", 1))
                line = (price * qty) if price is not None else None
                shop = (it.get("shop") or "—")[:18]
                lb.insert("end", f"{qty}× {shop}  {price_text(line) if line is not None else '—'}")
            n = len(self.cart)
            self.cart_total_inline.configure(
                text=(f"Σύνολο: {price_text(self._cart_total())}  ({n})" if n else "Άδειο"))
        except Exception:
            pass

    def _render_cart_window(self):
        try:
            self.ctree.delete(*self.ctree.get_children())
        except Exception:
            return
        for idx, it in enumerate(self.cart):
            price = to_float(it.get("price"))
            qty = int(it.get("qty", 1))
            line = (price * qty) if price is not None else None
            self.ctree.insert("", "end", iid=str(idx), tags=("odd" if idx % 2 else "even",),
                              values=(it.get("title") or "—", it.get("shop") or "—", qty,
                                      price_text(price),
                                      price_text(line) if line is not None else "—",
                                      it.get("url") or "—"))
        self.cart_total_lbl.configure(
            text=f"Σύνολο: {price_text(self._cart_total())}   ·   {len(self.cart)} είδη")

    def _cart_sel(self):
        sel = self.ctree.selection()
        return int(sel[0]) if sel else None

    # --- χειρισμός inline καλαθιού (λίστα κάτω από τη φωτο) --- #
    def _inline_sel(self):
        sel = self.cart_list.curselection()
        return sel[0] if sel else None

    def _inline_qty(self, delta):
        i = self._inline_sel()
        if i is None or i >= len(self.cart):
            return
        self.cart[i]["qty"] = max(1, int(self.cart[i].get("qty", 1)) + delta)
        self._save_cart()
        self._render_cart()
        try:
            self.cart_list.selection_set(i)
        except Exception:
            pass

    def _inline_remove(self):
        i = self._inline_sel()
        if i is None or i >= len(self.cart):
            return
        del self.cart[i]
        self._save_cart()
        self._render_cart()

    def _inline_open_link(self):
        i = self._inline_sel()
        if i is None or i >= len(self.cart):
            return
        url = str(self.cart[i].get("url") or "")
        if url.startswith(("http://", "https://")):
            webbrowser.open(url)
        else:
            messagebox.showinfo("Σύνδεσμος", "Αυτό το είδος δεν έχει σύνδεσμο.")

    def _cart_qty(self, delta):
        i = self._cart_sel()
        if i is None:
            return
        self.cart[i]["qty"] = max(1, int(self.cart[i].get("qty", 1)) + delta)
        self._save_cart()
        self._render_cart()

    def _cart_remove(self):
        i = self._cart_sel()
        if i is None:
            return
        del self.cart[i]
        self._save_cart()
        self._render_cart()

    def _cart_clear(self):
        if not self.cart:
            return
        if messagebox.askyesno("Καλάθι", "Να αδειάσει όλο το καλάθι;"):
            self.cart = []
            self._save_cart()
            self._render_cart()

    def _open_cart_link(self):
        i = self._cart_sel()
        if i is None:
            return
        url = str(self.cart[i].get("url") or "")
        if url.startswith(("http://", "https://")):
            webbrowser.open(url)
        else:
            messagebox.showinfo("Σύνδεσμος", "Αυτό το είδος δεν έχει σύνδεσμο.")

    def _cart_export(self):
        if not self.cart:
            messagebox.showinfo("Εξαγωγή", "Το καλάθι είναι άδειο.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")],
                                            title="Αποθήκευση καλαθιού")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(["Προϊόν", "Κατάστημα", "Ποσότητα", "Τιμή", "Σύνολο", "Σύνδεσμος"])
                total = 0.0
                for it in self.cart:
                    price = to_float(it.get("price"))
                    qty = int(it.get("qty", 1))
                    line = (price * qty) if price is not None else None
                    if line is not None:
                        total += line
                    w.writerow([it.get("title", ""), it.get("shop", ""), qty,
                                "" if price is None else f"{price:.2f}",
                                "" if line is None else f"{line:.2f}", it.get("url", "")])
                w.writerow(["", "", "", "", "Σύνολο", f"{total:.2f}"])
            self.status.set("Καλάθι αποθηκεύτηκε: " + path)
        except OSError as exc:
            messagebox.showerror("Σφάλμα", str(exc))

    def export_csv(self):
        if not self.offers_data:
            messagebox.showinfo("Εξαγωγή", "Δεν υπάρχουν προσφορές για εξαγωγή.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV UTF-8", "*.csv")],
                                            initialfile="prosfores.csv")
        if not path:
            return
        fields = sorted({k for item in self.offers_data for k in item.keys()})
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                w.writerows(self.offers_data)
            self.status.set("Αποθηκεύτηκε: " + path)
        except OSError as exc:
            messagebox.showerror("Σφάλμα αποθήκευσης", str(exc))


def availability_text(value):
    raw = str(value or "").strip()
    key = raw.lower().replace("-", "_").replace(" ", "_")
    known = {
        "instock": "Άμεσα διαθέσιμο", "in_stock": "Άμεσα διαθέσιμο",
        "available": "Διαθέσιμο", "to_order": "Κατόπιν παραγγελίας",
        "on_order": "Κατόπιν παραγγελίας", "out_of_stock": "Μη διαθέσιμο",
        "outofstock": "Μη διαθέσιμο", "preorder": "Προπαραγγελία",
        "unknown": "Δεν επιβεβαιώθηκε", "": "—",
    }
    if key in known:
        return known[key]
    if raw.lower() == "none":
        return "—"
    return raw.replace("Available in ", "Διαθέσιμο σε ").replace(" days", " ημέρες")


if __name__ == "__main__":
    App().mainloop()
