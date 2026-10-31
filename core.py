# -*- coding: utf-8 -*-
"""core.py — κοινή λογική (πηγές, Playwright) για την web/Docker έκδοση.
Ίδια λογική με το desktop greek_price_app.py, χωρίς GUI.
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
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zlib
from html import unescape



APP_NAME = "Ελληνική Σύγκριση Τιμών"
VERSION = "0.35"
BESTPRICE_MCP = "https://mcp.bestprice.gr/mcp"
HERE = os.path.dirname(os.path.abspath(__file__))
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


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
        path = os.path.join(HERE, "app_debug.log")
        # Rotation: αν ξεπεράσει ~500KB, κράτα μόνο τις τελευταίες 200 γραμμές.
        if os.path.exists(path) and os.path.getsize(path) > 500_000:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            with open(path, "w", encoding="utf-8") as fh:
                fh.writelines(lines[-200:])
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"\n--- {where} ---\n{traceback.format_exc()}\n")
    except OSError:
        pass


def http_get(url, timeout=25, extra_headers=None, encoding="utf-8", _retry=0):
    """HTTP GET με αυτόματο backoff σε 429/503 (έως 3 προσπάθειες)."""
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
        if encoding:  # σεβόμαστε το ρητό encoding (π.χ. e-shop.gr = iso-8859-7)
            resp.encoding = encoding
        return resp.text
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            enc = (response.headers.get("Content-Encoding") or "").lower()
    except urllib.error.HTTPError as exc:
        if exc.code in (429, 503) and _retry < 3:
            time.sleep(2 ** _retry * 1.5)
            return http_get(url, timeout, extra_headers, encoding, _retry + 1)
        raise
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
        # Το state (session/request id) είναι κοινό· τα /api/offers,/history,
        # /decision μπορεί να τρέξουν ταυτόχρονα με την αναζήτηση (Flask threaded).
        # RLock γιατί το _call κάνει αναδρομικό retry.
        self._lock = threading.RLock()

    def _reset_session(self):
        """Reset της MCP σύνδεσης ώστε να ξαναγίνει initialize στην επόμενη κλήση."""
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
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                sid = response.headers.get("Mcp-Session-Id")
                if sid:
                    self._session_id = sid
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410, 503):
                self._reset_session()  # το session έληξε — reset για retry
            raise
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

    def _call(self, tool, arguments, _retry=True):
        with self._lock:
            return self._call_locked(tool, arguments, _retry)

    def _call_locked(self, tool, arguments, _retry=True):
        try:
            self._ensure()
        except Exception:
            if _retry:
                self._reset_session()
                return self._call_locked(tool, arguments, _retry=False)
            raise
        self._request_id += 1
        try:
            result = self._post({"jsonrpc": "2.0", "id": self._request_id,
                                 "method": "tools/call",
                                 "params": {"name": tool, "arguments": arguments}})
        except Exception:
            if _retry and not self._initialized:  # session έληξε → ξαναπροσπάθησε μία φορά
                self._reset_session()
                return self._call_locked(tool, arguments, _retry=False)
            raise
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

    def search(self, query, limit=16):
        data = self._call("search_products", {"query": query, "limit": max(1, min(24, limit))})
        rows = records(data, ("products", "results", "items", "data"))
        out = []
        for p in rows:
            pid = str(first(p, "product_id", "id", "bp_product_id", default="")).strip()
            title = str(first(p, "title", "name", "product_name", "product_title", default="")).strip()
            if not pid or not title:
                continue
            img = first(p, "image", "image_url", "img", "thumbnail", "picture",
                        "main_image", "image_big", default="")
            if isinstance(img, dict):
                img = img.get("url") or img.get("src") or ""
            out.append({
                "source": self.name, "product_id": pid, "title": title,
                "price_from": to_float(first(p, "price_from", "price", "min_price", "lowest_price", default=None)),
                "offer_count": first(p, "offer_count", "offers_count", "shop_count", default=None),
                "rating": to_float(first(p, "rating", default=None)),
                "image": img or "",
                "url": first(p, "product_url", "url", "bestprice_url", default=""),
            })
        # Οι εικόνες που λείπουν φορτώνονται lazy από το frontend (/api/bp_image),
        # ώστε η αναζήτηση να μένει γρήγορη (δεν μπλοκάρει σε N page fetches).
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


_PRIVATE_HOST_RE = re.compile(
    r"^(localhost|127\.|10\.|192\.168\.|169\.254\.|0\.0\.0\.0|\[?::1\]?|"
    r"172\.(1[6-9]|2\d|3[01])\.)", re.IGNORECASE)


def _is_safe_fetch_url(url):
    """SSRF guard: επιτρέπει μόνο http/https σε δημόσιο host (όχι loopback/
    private/link-local/χωρίς τελεία), ώστε το /api/fetch_url να μην φτάνει
    εσωτερικές υπηρεσίες."""
    try:
        p = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").strip()
    if not host or "." not in host:
        return False
    return not _PRIVATE_HOST_RE.match(host)


def fetch_product_url(url):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if not _is_safe_fetch_url(url):
        raise RuntimeError("Μη έγκυρος ή μη επιτρεπτός σύνδεσμος "
                           "(επίτρεψε μόνο δημόσια eshop URLs).")
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


def _browser_exe_candidates():
    """Πιθανοί Chromium-based browsers ανά OS: Edge, Chrome, Brave, Vivaldi,
    Opera, Chromium. Όλοι οδηγούνται από τη μηχανή chromium του Playwright."""
    out = []
    if sys.platform.startswith("win"):
        bases = [os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.environ.get("LocalAppData", "")]
        rels = [r"Microsoft\Edge\Application\msedge.exe",
                r"Google\Chrome\Application\chrome.exe",
                r"BraveSoftware\Brave-Browser\Application\brave.exe",
                r"Vivaldi\Application\vivaldi.exe",
                r"Chromium\Application\chrome.exe"]
        for base in bases:
            if base:
                out += [os.path.join(base, r) for r in rels]
        la = os.environ.get("LocalAppData", "")
        # Opera / Opera GX: ο πραγματικός browser είναι σε υποφάκελο έκδοσης
        # (το top-level opera.exe είναι απλός launcher). Προτιμάμε τη νεότερη έκδοση.
        for brand in ("Opera", "Opera GX"):
            base = os.path.join(la, "Programs", brand) if la else ""
            if base and os.path.isdir(base):
                vers = []
                try:
                    for name in os.listdir(base):
                        exe = os.path.join(base, name, "opera.exe")
                        if re.match(r"^\d+\.", name) and os.path.isfile(exe):
                            vers.append((name, exe))
                except OSError:
                    pass
                vers.sort(reverse=True)  # νεότερη έκδοση πρώτη
                out += [exe for _, exe in vers]
                out.append(os.path.join(base, "opera.exe"))  # launcher ως fallback
    elif sys.platform == "darwin":
        out += ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                "/Applications/Vivaldi.app/Contents/MacOS/Vivaldi",
                "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    else:  # Linux
        import shutil
        for name in ("microsoft-edge", "microsoft-edge-stable", "google-chrome",
                     "google-chrome-stable", "chromium", "chromium-browser",
                     "brave-browser", "vivaldi-stable"):
            p = shutil.which(name)
            if p:
                out.append(p)
    seen, res = set(), []
    for c in out:
        if c and c not in seen and os.path.isfile(c):
            seen.add(c)
            res.append(c)
    return res


# Προτιμώμενος browser για τη ΜΗΧΑΝΗ scraping (αόρατος/headless). ΟΧΙ Opera: η
# Opera ΔΕΝ οδηγείται headless από το Playwright — ανοίγει ορατό παράθυρο και δεν
# ελέγχεται (έσπαγε Skroutz/eBay κ.λπ.). Default = αυτόματο (bundled Chromium →
# Edge/Chrome channel). Μπορείς να εξαναγκάσεις με GPC_BROWSER (π.χ. edge).
PREFERRED_BROWSER = os.environ.get("GPC_BROWSER", "").strip().lower()


_STEALTH_ARGS = ["--disable-blink-features=AutomationControlled",
                 "--disable-features=IsolateOrigins,site-per-process"]


def launch_chromium(pw, extra_args=None):
    """Εκκινεί ΑΟΡΑΤΟ (headless) Chromium-based browser. Σειρά:
    0) ρητός GPC_BROWSER (αν οριστεί),
    1) το Chromium του Playwright (αν κατέβηκε) — πιο αξιόπιστο headless,
    2) Edge/Chrome μέσω channel (πάντα headless στα Windows),
    3) άλλοι Chromium-based (Edge/Chrome/Brave/Vivaldi/Chromium) — ΟΧΙ Opera.
    Η Opera αποκλείεται γιατί δεν τρέχει headless (ανοίγει ορατό παράθυρο).
    extra_args: πρόσθετα Chromium flags (π.χ. stealth για anti-bot σελίδες)."""
    attempts = []
    cands = _browser_exe_candidates()
    pref = [c for c in cands if PREFERRED_BROWSER and PREFERRED_BROWSER in c.lower()]
    kw = {"args": list(extra_args)} if extra_args else {}

    # 0) Προτιμώμενος browser μέσω του exe του
    for exe in pref:
        try:
            return pw.chromium.launch(headless=True, executable_path=exe, **kw)
        except Exception as exc:
            attempts.append(f"{os.path.basename(exe)}: {str(exc)[:55]}")
    # 1) Chromium του Playwright
    try:
        return pw.chromium.launch(headless=True, **kw)
    except Exception as exc:
        attempts.append(f"chromium: {str(exc)[:70]}")
    # 2) Edge/Chrome μέσω channel
    for channel in ("msedge", "chrome"):
        try:
            return pw.chromium.launch(headless=True, channel=channel, **kw)
        except Exception as exc:
            attempts.append(f"{channel}: {str(exc)[:70]}")
    # 3) Υπόλοιποι Chromium-based browsers — ΕΚΤΟΣ Opera (ανοίγει ορατό παράθυρο
    #    και δεν οδηγείται headless· μπαίνει μόνο αν ζητηθεί ρητά με GPC_BROWSER).
    for exe in cands:
        if exe in pref or "opera" in exe.lower():
            continue
        try:
            return pw.chromium.launch(headless=True, executable_path=exe, **kw)
        except Exception as exc:
            attempts.append(f"{os.path.basename(exe)}: {str(exc)[:55]}")
    raise RuntimeError("Δεν βρέθηκε συμβατός browser — " + " | ".join(attempts[-4:]))


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
                browser = launch_chromium(pw, extra_args=_STEALTH_ARGS)
            except Exception as exc:
                msg = str(exc)
                if "Executable doesn't exist" in msg or "playwright install" in msg:
                    return [], ["Playwright: λείπει ο browser — τρέξε 'playwright install chromium'"]
                return [], [f"Playwright: σφάλμα εκκίνησης — {msg[:100]}"]
            try:
                ctx = browser.new_context(user_agent=_UA, locale="el-GR",
                                          timezone_id="Europe/Athens",
                                          viewport={"width": 1366, "height": 900})
                # stealth: κρύβουμε δείκτες αυτοματισμού (βοηθά με Cloudflare στο Skroutz)
                try:
                    ctx.add_init_script(
                        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                        "window.chrome={runtime:{}};"
                        "Object.defineProperty(navigator,'languages',{get:()=>['el-GR','el','en']});"
                        "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});")
                except Exception:
                    pass
                for label, tmpl in targets:
                    url = tmpl.format(q=q)
                    page = ctx.new_page()
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        # Το Skroutz έχει Cloudflare ("Just a moment") — δίνουμε χρόνο
                        # να λυθεί η JS πρόκληση και ξαναδοκιμάζουμε μία φορά με reload.
                        for attempt in range(2):
                            try:
                                page.wait_for_function(wait_js, timeout=12000)
                                break
                            except Exception:
                                page.wait_for_timeout(3500)
                                if attempt == 0:
                                    try:
                                        page.reload(wait_until="domcontentloaded", timeout=30000)
                                    except Exception:
                                        pass
                        html = page.content()
                        base = page.url
                        r = parse_search_listing(html, base, label, limit=20)
                        rows.extend(r)
                        if r:
                            diags.append(f"{label}: {len(r)} προϊόντα")
                        else:
                            cf = any(s in html for s in ("Just a moment", "cf-browser-verification",
                                                         "challenge-platform", "Attention Required"))
                            diags.append(f"{label}: {'μπλοκαρίστηκε από Cloudflare — δοκίμασε ξανά' if cf else 'δεν βρέθηκαν προϊόντα (ίσως άλλαξε η σελίδα)'}")
                    except Exception as exc:
                        diags.append(f"{label}: {str(exc)[:80]}")
                    finally:
                        try:
                            page.close()
                        except Exception:
                            pass
            finally:
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
            try:
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
            finally:
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
POLITEIA_LABEL = "Πολιτεία"


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
            data = None
            try:
                ctx = browser.new_context(user_agent=_UA, locale="el-GR")
                page = ctx.new_page()
                try:
                    page.goto("https://posokanei.gov.gr/", wait_until="domcontentloaded",
                              timeout=30000)
                    data = page.evaluate(_SM_API_JS, query)
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
            finally:
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
            try:
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
            finally:
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


EBAY_LABEL = "eBay"
_EBAY_SEARCH_URL = "https://www.ebay.de/sch/i.html?_nkw={q}&_ipg=60"
_EBAY_PARSE_JS = r"""
() => {
  const num = s => {
    if (!s) return null;
    s = s.replace(/[^\d.,]/g, '');
    if (s.includes('.') && s.includes(',')) s = s.replace(/\./g, '').replace(',', '.');
    else if (s.includes(',')) s = s.replace(',', '.');
    const n = parseFloat(s); return isFinite(n) ? n : null;
  };
  const out = [], seen = new Set();
  for (const it of document.querySelectorAll('li.s-card, li.s-item')) {
    const a = it.querySelector('a.s-card__link[href*="/itm/"], a.s-item__link[href*="/itm/"], a[href*="/itm/"]');
    if (!a) continue;
    const url = a.href.split('?')[0];
    if (!url || /\/itm\/123456/.test(url) || seen.has(url)) continue;
    const te = it.querySelector('.s-card__title, .s-item__title, [role=heading]');
    let title = te ? te.textContent.trim() : '';
    title = title.split(/Wird in neuem|Opens in|Neues Angebot/)[0].trim();
    if (!title || /^Shop on eBay/i.test(title)) continue;
    const pe = it.querySelector('.s-card__price, .s-item__price');
    const price = pe ? num(pe.textContent) : null;
    let shipping = null;
    for (const e of it.querySelectorAll('.su-styled-text.secondary, .s-item__shipping')) {
      if (/Lieferung|Versand/i.test(e.textContent)) { shipping = num(e.textContent); break; }
    }
    const img = it.querySelector('img');
    const image = img ? (img.getAttribute('src') || img.getAttribute('data-src') || '') : '';
    out.push({title: title.slice(0, 110), price, shipping, url, image});
  }
  return out;
};
"""


def _parse_ebay(html, limit=25):
    """Python parser του eBay.de SRP (server-rendered). Σπάει το HTML σε κάρτες
    (<li class="s-card…) και διαβάζει id/τίτλο/τιμή/εικόνα από κάθε κάρτα."""
    items, seen = [], set()
    for ch in re.split(r'<li\s+class="s-card', html)[1:]:
        m = re.search(r'/itm/(\d+)', ch)
        if not m:
            continue
        pid = m.group(1)
        if pid == "123456" or pid in seen:
            continue
        tm = re.search(r's-card__title[^>]*>(?:\s*<[^>]+>)*\s*([^<]{3,180})', ch)
        if not tm:
            continue
        title = unescape(tm.group(1)).strip()
        if not title or title.lower().startswith("shop on ebay"):
            continue
        pm = re.search(r's-card__price[^>]*>(?:\s*<[^>]+>)*\s*([^<]*?EUR[^<]*?)\s*<', ch)
        price = to_float(pm.group(1)) if pm else None
        im = re.search(r'https://i\.ebayimg\.com/[^"\'\s>)]+', ch)
        um = re.search(r'(https://www\.ebay\.de/itm/\d+)', ch)
        seen.add(pid)
        items.append({"title": title, "price": price,
                      "image": im.group(0) if im else "",
                      "url": um.group(1) if um else f"https://www.ebay.de/itm/{pid}",
                      "shipping": None})
        if len(items) >= limit:
            break
    return items


def _ebay_rows(items, limit):
    rows = []
    for it in (items or [])[:limit]:
        if not isinstance(it, dict):
            continue
        price = to_float(it.get("price"))
        ship = to_float(it.get("shipping"))
        purl = it.get("url") or ""
        avail = f"+{ship:.2f}€ μεταφορικά" if ship is not None else "eBay.de"
        rows.append({
            "source": EBAY_LABEL, "product_id": "",
            "title": it.get("title") or "", "image": it.get("image") or "",
            "price_from": price, "offer_count": 1, "rating": None,
            "product_url": purl,
            "_direct": {"source": EBAY_LABEL, "merchant_name": EBAY_LABEL,
                        "price": price, "url": purl, "availability": avail,
                        "rating": None, "currency": "EUR"}})
    return rows


def ebay_search(query, limit=25):
    """eBay.de (τιμές EUR). Το SRP είναι server-rendered & χωρίς cookies, οπότε
    δοκιμάζουμε ΠΡΩΤΑ απλό HTTP (γρήγορο, παρακάμπτει consent/headless)· αν
    αποτύχει/αδειάσει, πέφτουμε σε Playwright."""
    url = _EBAY_SEARCH_URL.format(q=urllib.parse.quote(query))
    # 1) HTTP πρώτα — πλήρη browser-like headers (το eBay κρύβει το SRP από
    #    "γυμνά" requests· με sec-ch-ua/Sec-Fetch σερβίρει κανονικά s-card).
    try:
        html = http_get(url, timeout=20, extra_headers={
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
            "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
            "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"',
            "Cache-Control": "max-age=0",
        })
        items = _parse_ebay(html, limit)
        if items:
            return _ebay_rows(items, limit), f"{EBAY_LABEL}: {len(items)} αγγελίες"
    except Exception:
        pass
    # 2) Playwright fallback
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return [], f"{EBAY_LABEL}: {PLAYWRIGHT_HINT}"
    raw = None
    try:
        with sync_playwright() as pw:
            try:
                browser = launch_chromium(pw, extra_args=_STEALTH_ARGS)
            except Exception as exc:
                return [], f"eBay: δεν ξεκίνησε browser — {str(exc)[:110]}"
            try:
                ctx = browser.new_context(user_agent=_UA, locale="de-DE",
                                          timezone_id="Europe/Berlin",
                                          viewport={"width": 1366, "height": 900})
                # stealth: κρύβουμε δείκτες αυτοματισμού (navigator.webdriver κ.λπ.)
                try:
                    ctx.add_init_script(
                        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                        "window.chrome={runtime:{}};"
                        "Object.defineProperty(navigator,'languages',{get:()=>['de-DE','de','en']});"
                        "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});")
                except Exception:
                    pass
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    # Αποδοχή του DSGVO consent banner (αλλιώς το SRP δεν φορτώνει
                    # κάρτες σε fresh/headless session).
                    for sel in ("button#gdpr-banner-accept", "#gdpr-banner-accept",
                                "button[aria-label*='akzeptier' i]",
                                "button:has-text('Alle akzeptieren')",
                                "button:has-text('Akzeptieren')"):
                        try:
                            el = page.query_selector(sel)
                            if el:
                                el.click(timeout=2500)
                                page.wait_for_timeout(600)
                                break
                        except Exception:
                            pass
                    try:
                        page.wait_for_selector("li.s-card, li.s-item", timeout=12000)
                        page.wait_for_timeout(700)
                    except Exception:
                        pass
                    raw = page.evaluate(_EBAY_PARSE_JS)
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
            finally:
                browser.close()
    except Exception as exc:
        return [], f"{EBAY_LABEL}: {str(exc)[:120]}"
    rows = _ebay_rows(raw, limit)
    return rows, (f"{EBAY_LABEL}: {len(rows)} αγγελίες" if rows
                  else f"{EBAY_LABEL}: δεν βρέθηκαν (ίσως άλλαξε η σελίδα)")


# ----------------------------------------------------------------------------
# Φάση 2 — απευθείας eshops μέσω JSON-LD ItemList (γενικός, εύκολα επεκτάσιμος).
# Αρκεί label + URL αναζήτησης· ό,τι eshop εκθέτει schema.org ItemList/Product
# στη σελίδα αποτελεσμάτων δουλεύει χωρίς CSS selectors (πιο ανθεκτικό).
# ----------------------------------------------------------------------------
PHARM24_LABEL = "Pharm24"
_PHARM24_SEARCH_URL = ("https://www.pharm24.gr/index.php?main_page="
                       "advanced_search_result&search_in_description=1&keyword={q}")

# Χάρτης url/όνομα → {rating,count} από ΟΛΟ το JSON-LD της σελίδας. Έτσι γεμίζουν
# βαθμολογίες και σε πηγές με site-specific parser (DOM) που δεν τις διαβάζει.
_JSONLD_RATING_MAP_JS = r"""
() => {
  const map = {};
  const one = v => Array.isArray(v) ? v[0] : v;
  const norm = u => { try { return new URL(u, location.href).href.split('?')[0]; } catch(e){ return (u||'').split('?')[0]; } };
  const add = p => {
    if (!p || typeof p !== 'object') return;
    const ty = p['@type']; const types = Array.isArray(ty) ? ty : [ty];
    if (!types.includes('Product')) return;
    const agg = one(p.aggregateRating); if (!agg) return;
    const rv = parseFloat(String(agg.ratingValue).replace(',', '.'));
    if (!isFinite(rv)) return;
    const cnt = agg.reviewCount || agg.ratingCount || null;
    let u = p.url || (p.offers && one(p.offers).url) || '';
    if (!u && p.mainEntityOfPage) u = typeof p.mainEntityOfPage === 'string' ? p.mainEntityOfPage : (p.mainEntityOfPage['@id'] || '');
    if (u) map[norm(u)] = { rating: rv, count: cnt };
    if (p.name) map['name:' + String(p.name).trim().toLowerCase().slice(0, 80)] = { rating: rv, count: cnt };
  };
  const walk = n => {
    if (!n) return;
    if (Array.isArray(n)) { n.forEach(walk); return; }
    if (typeof n !== 'object') return;
    add(n);
    if (n.itemListElement) walk(n.itemListElement);
    if (n.item) walk(n.item);
    if (n['@graph']) walk(n['@graph']);
  };
  document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
    try { walk(JSON.parse(s.textContent)); } catch(e){}
  });
  return map;
};
"""

_JSONLD_ITEMLIST_JS = r"""
() => {
  const items = [];
  const one = v => Array.isArray(v) ? v[0] : v;
  const push = p => {
    if (!p || !p.name) return;
    const off = one(p.offers) || {};
    let avail = (off.availability || '') + '';
    if (/InStock/i.test(avail)) avail = 'Διαθέσιμο';
    else if (/OutOfStock|SoldOut|Discontinued|BackOrder/i.test(avail)) avail = 'Εξαντλημένο';
    else avail = '';
    const rat = p.aggregateRating ? p.aggregateRating.ratingValue : null;
    const rcnt = p.aggregateRating ? (p.aggregateRating.reviewCount || p.aggregateRating.ratingCount || null) : null;
    items.push({
      title: (p.name || '').toString().slice(0, 160),
      price: off.price != null ? off.price : (off.lowPrice != null ? off.lowPrice : null),
      image: one(p.image) || '',
      url: p.url || '',
      rating: rat,
      rating_count: rcnt,
      availability: avail,
      currency: off.priceCurrency || 'EUR'
    });
  };
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    let j; try { j = JSON.parse(s.textContent); } catch (e) { continue; }
    const arr = Array.isArray(j) ? j : [j];
    for (const node of arr) {
      if (!node || typeof node !== 'object') continue;
      const graph = Array.isArray(node['@graph']) ? node['@graph'] : [node];
      for (const n of graph) {
        if (!n || typeof n !== 'object') continue;
        const t = n['@type'];
        if (t === 'ItemList' && Array.isArray(n.itemListElement)) {
          for (const li of n.itemListElement) {
            const it = (li && li.item) ? li.item : li;
            if (it && (it['@type'] === 'Product' || it.name)) push(it);
          }
        } else if (t === 'Product' || (Array.isArray(t) && t.includes('Product'))) {
          push(n);
        }
      }
    }
  }
  return items;
};
"""


# Pharm24: οι κανονικές αναζητήσεις δίνουν ItemList JSON-LD, αλλά όροι που
# ταιριάζουν ακριβώς σε brand/κατηγορία (π.χ. "avene") κάνουν redirect σε
# σελίδα brand ΧΩΡΙΣ ItemList → fallback στο grid (.msr-price + img alt).
_PHARM24_PARSE_JS = r"""
() => {
  const items = [], one = v => Array.isArray(v) ? v[0] : v;
  const mapAvail = a => { a = (a||'')+''; if (/InStock/i.test(a)) return 'Διαθέσιμο';
    if (/OutOfStock|SoldOut|Discontinued|BackOrder/i.test(a)) return 'Εξαντλημένο'; return ''; };
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    let j; try { j = JSON.parse(s.textContent); } catch (e) { continue; }
    const arr = Array.isArray(j) ? j : [j];
    for (const node of arr) {
      if (!node || typeof node !== 'object') continue;
      const graph = Array.isArray(node['@graph']) ? node['@graph'] : [node];
      for (const n of graph) {
        if (!n || typeof n !== 'object') continue;
        const t = n['@type'];
        const add = p => { if (!p || !p.name) return; const off = one(p.offers) || {};
          items.push({ title:(p.name||'').toString().slice(0,160),
            price: off.price!=null?off.price:(off.lowPrice!=null?off.lowPrice:null),
            image: one(p.image)||'', url: p.url||'',
            rating: p.aggregateRating?p.aggregateRating.ratingValue:null,
            availability: mapAvail(off.availability), currency: off.priceCurrency||'EUR' }); };
        if (t === 'ItemList' && Array.isArray(n.itemListElement)) {
          for (const li of n.itemListElement) { const it=(li&&li.item)?li.item:li;
            if (it&&(it['@type']==='Product'||it.name)) { if (!it.url && li && li.url) it.url=li.url; add(it); } }
        } else if (t === 'Product' || (Array.isArray(t) && t.includes('Product'))) add(n);
      }
    }
  }
  if (items.length) return items;
  // fallback: product grid on brand/category pages (no ItemList)
  const num = s => { if (!s) return null; s = s.replace(/[^\d.,]/g,'');
    if (s.includes('.') && s.includes(',')) s = s.replace(/\./g,'').replace(',','.');
    else if (s.includes(',')) s = s.replace(',','.'); const n = parseFloat(s); return isFinite(n)?n:null; };
  const seen = new Set();
  document.querySelectorAll('.msr-price').forEach(pe => {
    const price = num(pe.textContent); if (price == null) return;
    let card = pe, nameEl = null, link = null;
    for (let i=0;i<6;i++){ card=card.parentElement; if(!card)break;
      nameEl=card.querySelector('.product-name'); link=card.querySelector('a[href*="-p-"]'); if(nameEl&&link)break; }
    if (!nameEl || !link) return;
    let url; try { url = new URL(link.getAttribute('href'), location.origin).href; } catch (e) { return; }
    if (seen.has(url)) return;
    const img = card.querySelector('img');
    const image = img ? (img.getAttribute('src')||img.getAttribute('data-src')||'') : '';
    let name = (img && img.getAttribute('alt')) || (nameEl.textContent||'').replace(/\s*\.\.\.\s*i\s*/g,' ');
    name = name.trim(); if (name.length < 3) return;
    seen.add(url);
    items.push({ title:name.slice(0,160), price, image, url, rating:null, availability:'', currency:'EUR' });
  });
  return items;
};
"""


def jsonld_itemlist_search(label, search_url, query, limit=25,
                           wait_selector='script[type="application/ld+json"]',
                           parse_js=None, settle_ms=600):
    """Γενικός scraper για eshop που εκθέτει JSON-LD ItemList/Product στη σελίδα
    αποτελεσμάτων. Τρέχει μέσω Playwright (δουλεύει και σε server-rendered και σε
    sites που προσθέτουν το JSON-LD με JS). `parse_js` για site-specific parser,
    `settle_ms` για extra αναμονή σε AJAX/SPA sites."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return [], f"{label}: {PLAYWRIGHT_HINT}"
    url = search_url.format(q=urllib.parse.quote(query))
    raw = None
    rmap = {}
    try:
        with sync_playwright() as pw:
            try:
                browser = launch_chromium(pw)
            except Exception as exc:
                return [], f"{label}: δεν ξεκίνησε browser — {str(exc)[:110]}"
            try:
                ctx = browser.new_context(user_agent=_UA, locale="el-GR",
                                          viewport={"width": 1366, "height": 900})
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    try:
                        page.wait_for_selector(wait_selector, timeout=10000)
                        page.wait_for_timeout(settle_ms)
                    except Exception:
                        pass
                    raw = page.evaluate(parse_js or _JSONLD_ITEMLIST_JS)
                    try:
                        rmap = page.evaluate(_JSONLD_RATING_MAP_JS) or {}
                    except Exception:
                        rmap = {}
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
            finally:
                browser.close()
    except Exception as exc:
        return [], f"{label}: {str(exc)[:120]}"
    rows, seen = [], set()
    for it in (raw or []):
        if not isinstance(it, dict):
            continue
        title = (it.get("title") or "").strip()
        purl = it.get("url") or ""
        key = purl or title
        if not title or key in seen:
            continue
        seen.add(key)
        price = to_float(it.get("price"))
        rating = to_float(it.get("rating"))
        rcount = it.get("rating_count")
        # Συμπλήρωση βαθμολογίας από το JSON-LD της σελίδας (αν ο parser δεν την έδωσε)
        if not rating and rmap:
            info = rmap.get((purl or "").split("?")[0]) or rmap.get("name:" + title.strip().lower()[:80])
            if info:
                rating = to_float(info.get("rating"))
                rcount = rcount or info.get("count")
        avail = it.get("availability") or ""
        rows.append({
            "source": label, "product_id": "",
            "title": title, "image": it.get("image") or "",
            "price_from": price, "offer_count": 1,
            "rating": rating if rating else None,
            "rating_count": rcount or None,
            "product_url": purl,
            "_direct": {"source": label, "merchant_name": label,
                        "price": price, "url": purl, "availability": avail,
                        "rating": rating if rating else None,
                        "rating_count": rcount or None,
                        "currency": it.get("currency") or "EUR"}})
        if len(rows) >= limit:
            break
    if not rows:
        return rows, f"{label}: δεν βρέθηκαν (ίσως άλλαξε η σελίδα)"
    if len(rows) >= limit:
        return rows, f"{label}: {len(rows)}+ — πολλά αποτελέσματα, στένεψε την αναζήτηση"
    return rows, f"{label}: {len(rows)} προϊόντα"


def pharm24_search(query, limit=25):
    """Απευθείας αναζήτηση στο online φαρμακείο Pharm24. Κανονικές αναζητήσεις →
    JSON-LD ItemList· brand/κατηγορία (redirect) → fallback στο product grid."""
    return jsonld_itemlist_search(
        PHARM24_LABEL, _PHARM24_SEARCH_URL, query, limit,
        wait_selector='.msr-price, script[type="application/ld+json"]',
        parse_js=_PHARM24_PARSE_JS)


# ePapoutsia (παπούτσια/μόδα) — Nuxt SSR, καθαρές κάρτες .product-card-small.
EPAPOUTSIA_LABEL = "ePapoutsia"
_EPAPOUTSIA_SEARCH_URL = "https://epapoutsia.gr/s/{q}?q={q}"
_EPAPOUTSIA_PARSE_JS = r"""
() => {
  const items = [], seen = new Set();
  const num = s => { if (!s) return null; s = (s+'').replace(/[^\d.,]/g,'');
    if (s.includes('.') && s.includes(',')) s = s.replace(/\./g,'').replace(',','.');
    else if (s.includes(',')) s = s.replace(',','.'); const n = parseFloat(s); return isFinite(n)?n:null; };
  for (const c of document.querySelectorAll('.product-card-small, li.product-list-item')) {
    const a = c.querySelector('a.product-card-link, a[href^="/p/"], a[href]');
    if (!a) continue;
    let url; try { url = new URL(a.getAttribute('href'), location.origin).href; } catch (e) { continue; }
    if (!/\/p\//.test(url) || seen.has(url)) continue;
    const img = c.querySelector('img');
    const pe = c.querySelector('.product-price');
    const price = pe ? num(pe.textContent) : null;
    let name = (a.getAttribute('title') || a.getAttribute('aria-label') || (img && img.getAttribute('alt')) || '').trim();
    if (name.length < 2) continue;
    // ΠΡΟΣΟΧΗ: το eobuwie CDN URL περιέχει κόμματα (…SG_M.jpg,webp)/…) — ΔΕΝ
    // κάνουμε split(',') στο srcset (έσπαγε το URL). Προτιμάμε το πλήρες img src.
    let image = img ? (img.getAttribute('src') || img.getAttribute('data-src') || '') : '';
    if (!image || /^data:|placeholder|blank\.|\.svg([?#]|$)/i.test(image)) {
      const srcEl = c.querySelector('picture source[srcset], source[srcset]');
      if (srcEl) { const ss = srcEl.getAttribute('srcset') || '';
        image = (ss.split(/,\s+(?=https?:\/\/)/)[0] || '').trim().replace(/\s+\d+(?:w|x)$/, ''); }
    }
    seen.add(url);
    items.push({ title:name.slice(0,160), price, image, url, rating:null, availability:'', currency:'EUR' });
  }
  return items;
};
"""


def epapoutsia_search(query, limit=25):
    """Απευθείας αναζήτηση στο epapoutsia.gr (παπούτσια/μόδα — Nuxt SSR, CSS grid)."""
    return jsonld_itemlist_search(
        EPAPOUTSIA_LABEL, _EPAPOUTSIA_SEARCH_URL, query, limit,
        wait_selector='.product-card-small, .product-list-item',
        parse_js=_EPAPOUTSIA_PARSE_JS)


# Pharmacy295 (φαρμακείο) — Nuxt, αλλά η σελίδα αποτελεσμάτων έχει καθαρό JSON-LD
# ItemList → δουλεύει με τον γενικό parser (χωρίς CSS). ΔΕΝ κάνει brand redirect.
PHARMACY295_LABEL = "Pharmacy295"
_PHARMACY295_SEARCH_URL = "https://www.pharmacy295.gr/search?q={q}"


def pharmacy295_search(query, limit=25):
    """Απευθείας αναζήτηση στο online φαρμακείο Pharmacy295 (JSON-LD ItemList)."""
    return jsonld_itemlist_search(PHARMACY295_LABEL, _PHARMACY295_SEARCH_URL, query, limit)


# Cosmos Sport (αθλητικά) — PrestaThemed, αποτελέσματα με AJAX → render + CSS grid.
COSMOS_LABEL = "Cosmos Sport"
_COSMOS_SEARCH_URL = "https://www.cosmossport.gr/el/search?q={q}"
_COSMOS_PARSE_JS = r"""
() => {
  const items = [], seen = new Set();
  const num = s => { if (!s) return null; s = (s+'').replace(/[^\d.,]/g,'');
    if (s.includes('.') && s.includes(',')) s = s.replace(/\./g,'').replace(',','.');
    else if (s.includes(',')) s = s.replace(',','.'); const n = parseFloat(s); return isFinite(n)?n:null; };
  for (const c of document.querySelectorAll('.ajax_block_product')) {
    const a = c.querySelector('a.product_img_link, a[href*=".html"], a[href]'); if (!a) continue;
    let url; try { url = new URL(a.getAttribute('href'), location.origin).href; } catch (e) { continue; }
    if (seen.has(url)) continue;
    const img = c.querySelector('img');
    const pe = c.querySelector('.content_price, .price, [class*="price"]');
    const price = pe ? num(pe.textContent) : null;
    let name = (a.getAttribute('title') || (img && img.getAttribute('alt')) || '').trim();
    if (name.length < 2) continue;
    seen.add(url);
    items.push({ title:name.slice(0,160), price, image: img?(img.getAttribute('src')||img.getAttribute('data-src')||''):'',
                 url, rating:null, availability:'', currency:'EUR' });
  }
  return items;
};
"""


def cosmossport_search(query, limit=25):
    """Απευθείας αναζήτηση στο cosmossport.gr (αθλητικά — AJAX render, CSS grid)."""
    return jsonld_itemlist_search(
        COSMOS_LABEL, _COSMOS_SEARCH_URL, query, limit,
        wait_selector='.ajax_block_product', parse_js=_COSMOS_PARSE_JS, settle_ms=1500)


# Leroy Merlin (σπίτι/DIY) — server-rendered grid .product-miniature.
LEROY_LABEL = "Leroy Merlin"
_LEROY_SEARCH_URL = "https://www.leroymerlin.gr/gr/search?q={q}"
_LEROY_PARSE_JS = r"""
() => {
  const items = [], seen = new Set();
  const num = s => { if (!s) return null; s = (s+'').replace(/[^\d.,]/g,'');
    if (s.includes('.') && s.includes(',')) s = s.replace(/\./g,'').replace(',','.');
    else if (s.includes(',')) s = s.replace(',','.'); const n = parseFloat(s); return isFinite(n)?n:null; };
  for (const c of document.querySelectorAll('.product-miniature')) {
    const a = c.querySelector('a[href]'); if (!a) continue;
    let url; try { url = new URL(a.getAttribute('href'), location.origin).href; } catch (e) { continue; }
    if (seen.has(url)) continue;
    const te = c.querySelector('.artTitle, [class*="title"]');
    let name = (te ? te.textContent : (c.getAttribute('data-name') || '')).trim();
    if (name.length < 2) continue;
    const pe = c.querySelector('.artNormalPrice, .artPrice, [class*="price"]');
    const price = pe ? num(pe.textContent) : null;
    const img = c.querySelector('img');
    let image = img ? (img.getAttribute('src') || img.getAttribute('data-src') || '') : '';
    if (!image || /data:image|placeholder/.test(image)) { const n2 = c.querySelector('noscript img'); if (n2) image = n2.getAttribute('src') || image; }
    seen.add(url);
    items.push({ title:name.slice(0,160), price, image, url, rating:null, availability:'', currency:'EUR' });
  }
  return items;
};
"""


def leroymerlin_search(query, limit=25):
    """Απευθείας αναζήτηση στο leroymerlin.gr (σπίτι/DIY — SSR grid)."""
    return jsonld_itemlist_search(
        LEROY_LABEL, _LEROY_SEARCH_URL, query, limit,
        wait_selector='.product-miniature', parse_js=_LEROY_PARSE_JS)


# Moustakas Toys (παιχνίδια/παιδικά) — server-rendered grid .product.
MOUSTAKAS_LABEL = "Moustakas"
_MOUSTAKAS_SEARCH_URL = "https://www.moustakastoys.gr/apotelesmata-anazitisis/?q={q}"
_MOUSTAKAS_PARSE_JS = r"""
() => {
  const items = [], seen = new Set();
  const num = s => { if (!s) return null; s = (s+'').replace(/[^\d.,]/g,'');
    if (s.includes('.') && s.includes(',')) s = s.replace(/\./g,'').replace(',','.');
    else if (s.includes(',')) s = s.replace(',','.'); const n = parseFloat(s); return isFinite(n)?n:null; };
  for (const c of document.querySelectorAll('.product')) {
    const a = c.querySelector('a[href]'); if (!a) continue;
    let url; try { url = new URL(a.getAttribute('href'), location.origin).href; } catch (e) { continue; }
    if (seen.has(url)) continue;
    const img = c.querySelector('img');
    const pe = c.querySelector('.price, [class*="price"]');
    const price = pe ? num(pe.textContent) : null;
    let name = (a.getAttribute('title') || (img && img.getAttribute('alt')) || a.textContent || '').trim().replace(/\s+/g,' ');
    if (name.length < 3) continue;
    seen.add(url);
    items.push({ title:name.slice(0,160), price, image: img?(img.getAttribute('src')||img.getAttribute('data-src')||''):'',
                 url, rating:null, availability:'', currency:'EUR' });
  }
  return items;
};
"""


def moustakas_search(query, limit=25):
    """Απευθείας αναζήτηση στο moustakastoys.gr (παιχνίδια — SSR grid)."""
    return jsonld_itemlist_search(
        MOUSTAKAS_LABEL, _MOUSTAKAS_SEARCH_URL, query, limit,
        wait_selector='.product', parse_js=_MOUSTAKAS_PARSE_JS)


# Sephora (καλλυντικά/αρώματα) — server-rendered JSON-LD ItemList (url στο ListItem).
SEPHORA_LABEL = "Sephora"
_SEPHORA_SEARCH_URL = "https://www.sephora.gr/anazhthsh?q={q}"


def sephora_search(query, limit=25):
    """Απευθείας αναζήτηση στο sephora.gr (καλλυντικά — JSON-LD ItemList)."""
    return jsonld_itemlist_search(SEPHORA_LABEL, _SEPHORA_SEARCH_URL, query, limit)


# Hondos Center (καλλυντικά/αρώματα) — SPA, αποτελέσματα με JS → render + CSS grid.
HONDOS_LABEL = "Hondos Center"
_HONDOS_SEARCH_URL = "https://www.hondoscenter.com/el/all/f/search/{q}"
_HONDOS_PARSE_JS = r"""
() => {
  const items = [], seen = new Set();
  const num = s => { if (!s) return null; s = (s+'').replace(/[^\d.,]/g,'');
    if (s.includes('.') && s.includes(',')) s = s.replace(/\./g,'').replace(',','.');
    else if (s.includes(',')) s = s.replace(',','.'); const n = parseFloat(s); return isFinite(n)?n:null; };
  for (const c of document.querySelectorAll('[class*="ProductCard"]')) {
    const a = c.matches('a[href]') ? c : c.querySelector('a[href]'); if (!a) continue;
    let url; try { url = new URL(a.getAttribute('href'), location.origin).href; } catch (e) { continue; }
    if (seen.has(url)) continue;
    const img = c.querySelector('img');
    const pe = c.querySelector('.ProductPrice-PriceValue, [class*="PriceValue"], [class*="price" i]');
    const price = pe ? num(pe.textContent) : null;
    let name = (a.getAttribute('title') || a.getAttribute('aria-label') || (img && img.getAttribute('alt')) || '').trim();
    if (name.length < 3) continue;
    seen.add(url);
    items.push({ title:name.slice(0,160), price, image: img?(img.getAttribute('src')||img.getAttribute('data-src')||''):'',
                 url, rating:null, availability:'', currency:'EUR' });
  }
  return items;
};
"""


def hondos_search(query, limit=25):
    """Απευθείας αναζήτηση στο hondoscenter.com (καλλυντικά — SPA render, CSS grid)."""
    return jsonld_itemlist_search(
        HONDOS_LABEL, _HONDOS_SEARCH_URL, query, limit,
        wait_selector='[class*="ProductCard"]', parse_js=_HONDOS_PARSE_JS, settle_ms=2000)


# Amazon.de (τεχνολογία κ.ά., τιμές EUR) — SPA/anti-bot → Playwright + DOM parser.
# ΠΡΟΣΟΧΗ: το Amazon έχει anti-bot· σε headless μπορεί περιστασιακά να δείξει
# captcha και να γυρίσει 0 (graceful). Τα πιο αξιόπιστα παραμένουν τα aggregators.
AMAZON_LABEL = "Amazon"
_AMAZON_SEARCH_URL = "https://www.amazon.de/s?k={q}"
_AMAZON_PARSE_JS = r"""
() => {
  const items = [], seen = new Set();
  const num = s => { if (!s) return null; s = (s+'').replace(/[^\d.,]/g,'');
    if (s.includes('.') && s.includes(',')) s = s.replace(/\./g,'').replace(',','.');
    else if (s.includes(',')) s = s.replace(',','.'); const n = parseFloat(s); return isFinite(n)?n:null; };
  for (const c of document.querySelectorAll('div[data-component-type="s-search-result"]')) {
    const asin = c.getAttribute('data-asin'); if (!asin || seen.has(asin)) continue;
    const img = c.querySelector('img.s-image');
    const pe = c.querySelector('.a-price .a-offscreen');
    const price = pe ? num(pe.textContent) : null;
    let name = ''; const h2 = c.querySelector('h2'); if (h2) name = h2.textContent.trim();
    if ((!name || name.length < 3) && img) name = (img.getAttribute('alt') || '').trim();
    if (name.length < 3) continue;
    seen.add(asin);
    items.push({ title:name.slice(0,160), price, image: img?(img.getAttribute('src')||''):'',
                 url:'https://www.amazon.de/dp/'+asin, rating:null, availability:'', currency:'EUR' });
  }
  return items;
};
"""


def amazon_search(query, limit=25):
    """Απευθείας αναζήτηση στο amazon.de (Playwright + DOM· anti-bot = περιστασιακά 0)."""
    return jsonld_itemlist_search(
        AMAZON_LABEL, _AMAZON_SEARCH_URL, query, limit,
        wait_selector='div[data-component-type="s-search-result"]',
        parse_js=_AMAZON_PARSE_JS, settle_ms=1200)


# ─────────────────────────────────────────────────────────────────────────────
# ⛽ Καύσιμα — Παρατηρητήριο Τιμών Υγρών Καυσίμων (Υπ. Ανάπτυξης, fuelprices.gr).
# Καθημερινά PDF δελτία: μέσες τιμές λιανικής ανά Νομό + πανελλαδικά (σταθμισμένα).
# ─────────────────────────────────────────────────────────────────────────────
_FUEL_BASE = "https://www.fuelprices.gr/files/deltia/"
_FUEL_NOMOS_TMPL = "IMERISIO_DELTIO_ANA_NOMO_{dd}_{mm}_{yyyy}.pdf"
_FUEL_PAN_TMPL = "IMERISIO_DELTIO_PANELLINIO_{dd}_{mm}_{yyyy}.pdf"
_FUEL_LINE_RE = re.compile(
    r"^(ΝΟΜΟΣ\s+[Α-ΩΆΈΉΊΌΎΏΪΫ'\.\s]+?|ΠΑΝΕΛΛΗΝΙΟΣ[Α-ΩΆΈΉΊΌΎΏ\.\s]+?)"
    r"\s+(\d,\d{3})\s+(\d,\d{3})\s+(\d,\d{3})\s+(\d,\d{3})\s+(\d,\d{3})\s*$")
_FUEL_TYPES = [("u95", "Αμόλυβδη 95"), ("u100", "Αμόλυβδη 100"),
               ("diesel", "Diesel Κίνησης"), ("autogas", "Υγραέριο (Autogas)"),
               ("heating", "Πετρέλαιο Θέρμανσης")]
_FUEL_CACHE = {"ts": 0, "data": None}
_FUEL_TTL = 3600  # 1 ώρα


def _fuel_num(s):
    try:
        return float(str(s).strip().replace(".", "").replace(",", "."))
    except Exception:
        return None


def _fuel_fetch_pdf(tmpl, d):
    """Κατεβάζει το PDF δελτίο για ημ/νία d (δοκιμάζει zero-padded & μη)."""
    seen = set()
    for dd, mm in ((f"{d.day:02d}", f"{d.month:02d}"), (str(d.day), str(d.month))):
        url = _FUEL_BASE + tmpl.format(dd=dd, mm=mm, yyyy=d.year)
        if url in seen:
            continue
        seen.add(url)
        try:
            data = http_bytes(url, timeout=20)
            if data and data[:4] == b"%PDF":
                return data
        except Exception:
            continue
    return None


def fuel_prices():
    """Επιστρέφει {date, national[], prefectures[], fuels[]} από το πιο πρόσφατο
    δημοσιευμένο δελτίο (ψάχνει έως 10 ημέρες πίσω). Με cache 1 ώρας."""
    import io
    import datetime

    now = time.time()
    if _FUEL_CACHE["data"] and (now - _FUEL_CACHE["ts"]) < _FUEL_TTL:
        return _FUEL_CACHE["data"]

    try:
        import pdfplumber
    except Exception:
        return {"date": None, "national": [], "prefectures": [],
                "fuels": _FUEL_TYPES, "error": "Λείπει το pdfplumber."}

    nomos_pdf = pan_pdf = used = None
    today = datetime.date.today()
    for back in range(0, 11):
        d = today - datetime.timedelta(days=back)
        nomos_pdf = _fuel_fetch_pdf(_FUEL_NOMOS_TMPL, d)
        if nomos_pdf:
            used = d
            pan_pdf = _fuel_fetch_pdf(_FUEL_PAN_TMPL, d)
            break
    if not nomos_pdf:
        return {"date": None, "national": [], "prefectures": [],
                "fuels": _FUEL_TYPES, "error": "Δεν βρέθηκε πρόσφατο δελτίο."}

    # Ανά νομό (+ γραμμή πανελλήνιου σταθμισμένου Μ.Ο.)
    prefectures, weighted = [], None
    try:
        with pdfplumber.open(io.BytesIO(nomos_pdf)) as pdf:
            full = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
    except Exception as exc:
        return {"date": None, "national": [], "prefectures": [],
                "fuels": _FUEL_TYPES, "error": f"PDF: {str(exc)[:80]}"}
    for ln in full.split("\n"):
        m = _FUEL_LINE_RE.match(ln.strip())
        if not m:
            continue
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        rec = {"nomos": name.replace("ΝΟΜΟΣ ", "").strip(),
               "u95": _fuel_num(m.group(2)), "u100": _fuel_num(m.group(3)),
               "diesel": _fuel_num(m.group(4)), "autogas": _fuel_num(m.group(5)),
               "heating": _fuel_num(m.group(6))}
        if name.startswith("ΠΑΝΕΛΛΗΝ"):
            weighted = rec
        else:
            prefectures.append(rec)

    # Πανελλαδικά (αρ. πρατηρίων + σταθμισμένη μέση τιμή) + ημερομηνία
    national, date_text = [], None
    ptxt = ""
    if pan_pdf:
        try:
            with pdfplumber.open(io.BytesIO(pan_pdf)) as pdf:
                ptxt = pdf.pages[0].extract_text() or ""
        except Exception:
            ptxt = ""
    label_src = [("u95", "Αμόλυβδη 95"), ("u100", "Αμόλυβδη 100"),
                 ("diesel", "Diesel Κίνησης"), ("autogas", "Υγραέριο κίνησης"),
                 ("heating", "Diesel Θέρμανσης")]
    for (key, _lbl), (_, src) in zip(_FUEL_TYPES, label_src):
        m = re.search(re.escape(src) + r"[^\n]*?([\d\.]+)\s+(\d,\d{3})", ptxt)
        if m:
            national.append({"key": key, "label": dict(_FUEL_TYPES)[key],
                             "stations": int(m.group(1).replace(".", "")),
                             "price": _fuel_num(m.group(2))})
    dm = re.search(r"για\s+την\s*\n?\s*[Α-Ωα-ωΆ-ώ]+,\s*(\d{1,2})\s+([Α-Ωα-ωΆ-ώ]+)\s+(\d{4})", ptxt)
    if dm:
        date_text = f"{dm.group(1)} {dm.group(2)} {dm.group(3)}"
    # fallback πανελλαδικών από τη γραμμή Μ.Ο. του δελτίου νομών
    if not national and weighted:
        for key, lbl in _FUEL_TYPES:
            national.append({"key": key, "label": lbl, "stations": None,
                             "price": weighted.get(key)})
    if not date_text and used:
        date_text = used.strftime("%d/%m/%Y")

    data = {"date": date_text, "national": national, "prefectures": prefectures,
            "fuels": _FUEL_TYPES}
    _FUEL_CACHE["data"] = data
    _FUEL_CACHE["ts"] = now
    return data


# ── ΑΑΔΕ: πρόσφατες σφραγίσεις/νοθείες πρατηρίων (ενημερωτικό feed) ────────────
# Αδόμητα δελτία τύπου· φιλτράρουμε όσα αφορούν καύσιμα. ΔΕΝ είναι ιστορικό ανά
# συγκεκριμένο πρατήριο (τα ονόματα συνήθως δεν δημοσιεύονται) — αφορά περιοχές/
# υποθέσεις, με σύνδεσμο στο επίσημο δελτίο για ανάγνωση.
_AADE_LIST = "https://www.aade.gr/deltia-typoy-anakoinoseis"
_AADE_ITEM_RE = re.compile(
    r'href="(/deltia-typoy-anakoinoseis/[^"]*deltio-typoy-[^"]*)"[^>]*>\s*([\s\S]*?)</a>')
# Accent-insensitive (ο τόνος μετακινείται στις κλίσεις: Πρατηρίου/πρατήρια κ.λπ.)
_PEN_FUEL_RE = re.compile(r"πρατηρ|βενζιν|νοθ|καυσιμ", re.IGNORECASE)
_PEN_ENF_RE = re.compile(r"σφραγ|νοθ|λουκετο|παρεμβ|παραβ|προστιμ|λαθρεμπ|παρανομ", re.IGNORECASE)
# Αποκλεισμός διοικητικών/θετικών ανακοινώσεων (επιδοτήσεις, προθεσμίες κ.λπ.)
_PEN_EXCL_RE = re.compile(r"επιχορηγ|voucher|προθεσμ|καταβολ|επιστροφ|δικαιολογητ|ενισχυσ", re.IGNORECASE)
_PEN_CACHE = {"ts": 0, "data": None}
_PEN_TTL = 21600  # 6 ώρες


def _strip_accents(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn")


def _aade_list_page(n):
    url = _AADE_LIST + (f"?page={n}" if n else "")
    try:
        html = http_get(url, timeout=15)
    except Exception:
        return []
    out = []
    for m in _AADE_ITEM_RE.finditer(html):
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(2))).strip()
        out.append((m.group(1), text))
    return out


def fuel_penalties(pages=22):
    """Feed πρόσφατων σφραγίσεων/νοθειών πρατηρίων από τα δελτία τύπου της ΑΑΔΕ.
    Ενημερωτικό (ανά περιοχή/υπόθεση), ΟΧΙ ιστορικό ανά συγκεκριμένο πρατήριο."""
    from concurrent.futures import ThreadPoolExecutor
    now = time.time()
    if _PEN_CACHE["data"] and (now - _PEN_CACHE["ts"]) < _PEN_TTL:
        return _PEN_CACHE["data"]
    collected = []
    try:
        with ThreadPoolExecutor(max_workers=6) as ex:
            for res in ex.map(_aade_list_page, range(0, pages)):
                collected.extend(res)
    except Exception:
        pass
    seen, out = set(), []
    for href, text in collected:
        if href in seen:
            continue
        nt = _strip_accents(text)
        if not (_PEN_FUEL_RE.search(nt) and _PEN_ENF_RE.search(nt)):
            continue
        if _PEN_EXCL_RE.search(nt):
            continue
        seen.add(href)
        dm = re.search(r"(\d{2}/\d{2}/\d{4})", text)
        title = re.sub(r"^Δελτίο Τύπου\s*\d{2}/\d{2}/\d{4}\s*", "", text).strip()
        url = href if href.startswith("http") else "https://www.aade.gr" + href
        out.append({"date": dm.group(1) if dm else "", "title": title[:200], "url": url})

    def _dkey(x):
        try:
            d, m, y = x["date"].split("/")
            return (int(y), int(m), int(d))
        except Exception:
            return (0, 0, 0)
    out.sort(key=_dkey, reverse=True)
    data = {"items": out[:25], "source": "ΑΑΔΕ — Δελτία Τύπου"}
    _PEN_CACHE["data"] = data
    _PEN_CACHE["ts"] = now
    return data


# ── Μητρώο απευθείας πηγών: label → συνάρτηση (query) → (rows, diag). ──────────
# Προσθήκη νέας πηγής = ΜΙΑ γραμμή εδώ (+ chip στο UI). Το `known` και τα jobs
# παράγονται αυτόματα από αυτό — δεν χρειάζεται αλλαγή σε search_all/search_shops.
DIRECT_SOURCES = {
    "e-shop.gr": eshop_search,
    SUPERMARKET_LABEL: supermarket_search,
    POLITEIA_LABEL: politeia_search,
    EBAY_LABEL: ebay_search,
    AMAZON_LABEL: amazon_search,
    PHARM24_LABEL: pharm24_search,
    EPAPOUTSIA_LABEL: epapoutsia_search,
    PHARMACY295_LABEL: pharmacy295_search,
    COSMOS_LABEL: cosmossport_search,
    LEROY_LABEL: leroymerlin_search,
    MOUSTAKAS_LABEL: moustakas_search,
    SEPHORA_LABEL: sephora_search,
    HONDOS_LABEL: hondos_search,
}

# Μέγιστες ταυτόχρονες πηγές (κάθε Playwright πηγή = δικός της browser· περιορίζουμε
# για να μην ανοίγουν 5-6 headless browsers μαζί). Ρυθμίζεται με GPC_MAX_PARALLEL.
try:
    _MAX_PARALLEL = max(1, int(os.environ.get("GPC_MAX_PARALLEL", "4")))
except ValueError:
    _MAX_PARALLEL = 4


def search_shops(query, labels):
    """Επιστρέφει (rows, diagnostics). Skroutz/Public/Πολιτεία/eBay → Playwright·
    e-shop.gr & Σούπερ Μάρκετ → HTTP/API· τα υπόλοιπα → ειλικρινές μήνυμα."""
    results, diags = [], []
    pw = [l for l in labels if l in PLAYWRIGHT_SEARCH]
    if pw:
        if not playwright_available():
            diags.extend(f"{l}: {PLAYWRIGHT_HINT}" for l in pw)
        else:
            r, d = playwright_search_all(pw, query)
            results.extend(r)
            diags.extend(d)
    if "BestPrice" in labels:
        try:
            results.extend(BESTPRICE.search(query))
        except Exception as exc:
            diags.append(f"BestPrice: {exc}")
    for label, fn in DIRECT_SOURCES.items():
        if label in labels:
            try:
                r, diag = fn(query)
            except Exception as exc:
                r, diag = [], f"{label}: {exc}"
            results.extend(r)
            diags.append(diag)
    known = {"BestPrice"} | set(PLAYWRIGHT_SEARCH) | set(DIRECT_SOURCES)
    for l in labels:
        if l not in known:
            diags.append(f"{l}: {'ειδικό frontend — δεν υποστηρίζεται ακόμη' if l in UNSUPPORTED_SHOPS else 'μη υποστηριζόμενο'}")
    return results, diags


def search_all(query, labels):
    """Τρέχει ΟΛΕΣ τις πηγές ΠΑΡΑΛΛΗΛΑ (κάθε μία σε δικό της thread — κάθε
    Playwright κλήση φτιάχνει δικό της instance, οπότε είναι thread-safe).
    Επιστρέφει (rows, counts, diags)."""
    from concurrent.futures import ThreadPoolExecutor
    labels = list(labels)
    jobs = []  # (key, callable → (rows, diag_or_None))

    if "BestPrice" in labels:
        def _bp():
            try:
                return BESTPRICE.search(query), None
            except Exception as exc:
                return [], f"BestPrice: {exc}"
        jobs.append(("BestPrice", _bp))

    pwl = [l for l in labels if l in PLAYWRIGHT_SEARCH]
    if pwl:
        def _pw():
            if not playwright_available():
                return [], " | ".join(f"{l}: {PLAYWRIGHT_HINT}" for l in pwl)
            rows, d = playwright_search_all(pwl, query)
            return rows, (" | ".join(d) if d else None)
        jobs.append(("Playwright", _pw))

    for label, fn in DIRECT_SOURCES.items():
        if label in labels:
            jobs.append((label, (lambda f=fn: f(query))))

    known = {"BestPrice"} | set(PLAYWRIGHT_SEARCH) | set(DIRECT_SOURCES)
    rows_all, diags = [], []
    for l in labels:
        if l not in known:
            diags.append(f"{l}: {'ειδικό frontend — δεν υποστηρίζεται ακόμη' if l in UNSUPPORTED_SHOPS else 'μη υποστηριζόμενο'}")

    if jobs:
        with ThreadPoolExecutor(max_workers=min(len(jobs), _MAX_PARALLEL)) as ex:
            futs = [(k, ex.submit(fn)) for k, fn in jobs]
            for k, f in futs:
                try:
                    r, d = f.result()
                except Exception as exc:
                    r, d = [], f"{k}: {exc}"
                rows_all.extend(r or [])
                if d:
                    diags.append(d)

    counts = {}
    for r in rows_all:
        s = r.get("source")
        counts[s] = counts.get(s, 0) + 1
    return rows_all, counts, diags


def _build_jobs(query, labels):
    """Κοινή κατασκευή jobs για search_all / search_all_stream.
    Επιστρέφει (jobs, unsupported_diags) όπου κάθε job = (key, fn, members)."""
    labels = list(labels)
    jobs = []  # (key, callable → (rows, diag_or_None), members[list of source labels])

    if "BestPrice" in labels:
        def _bp():
            try:
                return BESTPRICE.search(query), None
            except Exception as exc:
                return [], f"BestPrice: {exc}"
        jobs.append(("BestPrice", _bp, ["BestPrice"]))

    pwl = [l for l in labels if l in PLAYWRIGHT_SEARCH]
    if pwl:
        def _pw():
            if not playwright_available():
                return [], " | ".join(f"{l}: {PLAYWRIGHT_HINT}" for l in pwl)
            rows, d = playwright_search_all(pwl, query)
            return rows, (" | ".join(d) if d else None)
        jobs.append(("Playwright", _pw, list(pwl)))

    for label, fn in DIRECT_SOURCES.items():
        if label in labels:
            jobs.append((label, (lambda f=fn: f(query)), [label]))

    known = {"BestPrice"} | set(PLAYWRIGHT_SEARCH) | set(DIRECT_SOURCES)
    unsupported = []
    for l in labels:
        if l not in known:
            unsupported.append(f"{l}: {'ειδικό frontend — δεν υποστηρίζεται ακόμη' if l in UNSUPPORTED_SHOPS else 'μη υποστηριζόμενο'}")
    return jobs, unsupported


def search_all_stream(query, labels):
    """Generator που τρέχει τις πηγές ΠΑΡΑΛΛΗΛΑ και παράγει αποτελέσματα ΑΝΑ ΠΗΓΗ
    μόλις ολοκληρώνεται η καθεμία (as_completed), ώστε το UI να τα δείχνει
    προοδευτικά. Παράγει dicts: {'type': 'meta'|'source'|'done', ...}."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    jobs, unsupported = _build_jobs(query, labels)
    yield {"type": "meta", "unsupported": unsupported}
    if jobs:
        with ThreadPoolExecutor(max_workers=min(len(jobs), _MAX_PARALLEL)) as ex:
            fut2meta = {ex.submit(fn): (key, members) for key, fn, members in jobs}
            for fut in as_completed(fut2meta):
                key, members = fut2meta[fut]
                try:
                    r, d = fut.result()
                except Exception as exc:
                    r, d = [], f"{key}: {exc}"
                r = r or []
                bylabel = {}
                for row in r:
                    s = row.get("source")
                    bylabel[s] = bylabel.get(s, 0) + 1
                yield {"type": "source", "key": key, "members": members,
                       "products": r, "count": len(r), "note": d, "bylabel": bylabel}
    yield {"type": "done"}


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


def history_series(data):
    """Βγάζει σειρά για γράφημα από το price history: διάμεσος ανά παράθυρο
    (μεγαλύτερο=παλιότερα) + τρέχουσα τιμή, με ζώνη min–max."""
    if not isinstance(data, dict):
        return {}
    cur = to_float(data.get("current_price"))
    low = to_float(data.get("lowest_ever") or data.get("all_time_low"))
    windows = data.get("window_stats") or data.get("windows") or []
    ws = []
    if isinstance(windows, list):
        for w in windows:
            if not isinstance(w, dict):
                continue
            md = to_float(w.get("median_price") or w.get("median"))
            mn = to_float(w.get("minimum_price") or w.get("min_price"))
            mx = to_float(w.get("maximum_price") or w.get("max_price"))
            if md is None and mn is None and mx is None:
                continue
            try:
                dd = int(w.get("days"))
            except (TypeError, ValueError):
                dd = 0
            ws.append((dd, mn, md, mx))
    ws.sort(key=lambda x: -x[0])  # παλιότερα (μεγάλο παράθυρο) → πρόσφατα
    pts = [{"label": (f"{dd}η" if dd else ""), "min": mn, "med": md, "max": mx}
           for dd, mn, md, mx in ws]
    if cur is not None:
        pts.append({"label": "τώρα", "min": None, "med": cur, "max": None})
    return {"series": pts, "current": cur, "low": low}


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




# ===================== Ευρωπαϊκές τιμές (Open Food Facts + Open Prices) ===== #
# Για προϊόντα σούπερ μάρκετ: όνομα → barcode (OFF text search) → crowdsourced
# τιμές ανά χώρα (Open Prices). ΕΝΔΕΙΚΤΙΚΕΣ/όχι live (αραιή κάλυψη, κυρίως
# δημοφιλή επώνυμα· δεν υπάρχει barcode από το posokanei, οπότε κάνουμε text match).
_OFF_SEARCH = ("https://world.openfoodfacts.org/cgi/search.pl?search_terms={q}"
               "&search_simple=1&action=process&json=1&page_size=6&sort_by=popularity")
_OPENPRICES = "https://prices.openfoodfacts.org/api/v1/prices?product_code={code}&size=100"
_SIZE_RE = re.compile(r"(\d+[.,]?\d*)\s*(kg|gr?|ml|cl|lt?|l)\b", re.IGNORECASE)


def _size_token(s):
    m = _SIZE_RE.search((s or "").lower())
    return (m.group(1).replace(",", ".") + m.group(2)) if m else ""


def off_barcode(name):
    """Barcode (EAN) για ένα προϊόν μέσω Open Food Facts (text search). Προτιμά
    αποτέλεσμα με ίδιο μέγεθος συσκευασίας· αλλιώς το πιο δημοφιλές."""
    try:
        d = json.loads(http_get(_OFF_SEARCH.format(q=urllib.parse.quote((name or "").strip())),
                                timeout=12))
    except Exception:
        return None
    want, best = _size_token(name), None
    for p in (d.get("products") or []):
        code = str(p.get("code") or "").strip()
        if not code or len(code) < 8:
            continue
        info = {"code": code, "name": (p.get("product_name") or "").strip(),
                "quantity": (p.get("quantity") or "").strip(),
                "brands": (p.get("brands") or "").strip()}
        if best is None:
            best = info
        if want and _size_token(info["quantity"]) == want:
            return info
    return best


def open_prices(barcode):
    """Τελευταία τιμή ανά χώρα (μόνο €) από το Open Prices για ένα barcode."""
    try:
        d = json.loads(http_get(_OPENPRICES.format(code=barcode), timeout=12))
    except Exception:
        return []
    latest = {}
    for it in (d.get("items") or []):
        if (it.get("currency") or "") != "EUR" or it.get("price") is None:
            continue
        loc = it.get("location") or {}
        cc = (loc.get("osm_address_country_code") or "").upper()
        if not cc:
            continue
        date = it.get("date") or ""
        if cc not in latest or date > latest[cc]["date"]:
            latest[cc] = {"country": cc, "price": to_float(it.get("price")),
                          "currency": "EUR", "date": date}
    rows = [v for v in latest.values() if v["price"] is not None]
    rows.sort(key=lambda r: r["price"])
    return rows


def eu_reference_prices(name):
    """Ευρωπαϊκές (ενδεικτικές) τιμές για προϊόν σούπερ μάρκετ, με barcode match."""
    m = off_barcode(name)
    if not m:
        return {"matched": None, "prices": []}
    return {"matched": {"barcode": m["code"], "name": m["name"],
                        "quantity": m.get("quantity", "")},
            "prices": open_prices(m["code"])}


# ============================ YouTube (παρουσιάσεις) ============================ #
_YT_VID_RE = re.compile(
    r'"videoRenderer":\{"videoId":"([\w-]{11})".*?"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"',
    re.S)
_YT_CH_RE = re.compile(r'"longBylineText":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"')
_YT_DUR_RE = re.compile(r'"simpleText":"(\d{1,2}:\d{2}(?::\d{2})?)"')


def _yt_decode(raw):
    try:
        return json.loads('"' + raw + '"')
    except Exception:
        return raw


def youtube_videos(query, limit=3):
    """Παρουσιάσεις/reviews από YouTube για ένα προϊόν (server-rendered search →
    ytInitialData). Επιστρέφει λίστα {id,title,channel,duration}."""
    q = urllib.parse.quote((query or "").strip() + " review")
    url = f"https://www.youtube.com/results?search_query={q}"
    try:
        # Το CONSENT cookie παρακάμπτει το EU consent wall ώστε να έρθει το
        # ytInitialData (αλλιώς το YouTube γυρίζει τη σελίδα συγκατάθεσης).
        html = http_get(url, timeout=12,
                        extra_headers={"Accept-Language": "en-US,en;q=0.8",
                                       "Cookie": "CONSENT=YES+1; SOCS=CAI"})
    except Exception:
        return []
    vids, seen = [], set()
    for m in _YT_VID_RE.finditer(html):
        vid = m.group(1)
        if vid in seen:
            continue
        seen.add(vid)
        win = html[m.start():m.start() + 1500]
        cm = _YT_CH_RE.search(win)
        dm = _YT_DUR_RE.search(win)
        vids.append({"id": vid, "title": _yt_decode(m.group(2)),
                     "channel": _yt_decode(cm.group(1)) if cm else "",
                     "duration": dm.group(1) if dm else ""})
        if len(vids) >= limit:
            break
    return vids


_BP_IMG_CACHE = {}


def bestprice_image(product_id):
    """og:image από τη σελίδα προϊόντος BestPrice (από το product_id), με cache."""
    m = re.search(r"\d+", str(product_id or ""))
    if not m:
        return ""
    key = m.group(0)
    if key in _BP_IMG_CACHE:
        return _BP_IMG_CACHE[key]
    try:
        html = http_get(f"https://www.bestprice.gr/item/{key}/x.html", timeout=15)
        img = _meta(html, "og:image") or ""
    except Exception:
        img = ""
    if len(_BP_IMG_CACHE) > 500:
        _BP_IMG_CACHE.clear()
    _BP_IMG_CACHE[key] = img
    return img
