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
VERSION = "0.21"
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
        try:
            self._ensure()
        except Exception:
            if _retry:
                self._reset_session()
                return self._call(tool, arguments, _retry=False)
            raise
        self._request_id += 1
        try:
            result = self._post({"jsonrpc": "2.0", "id": self._request_id,
                                 "method": "tools/call",
                                 "params": {"name": tool, "arguments": arguments}})
        except Exception:
            if _retry and not self._initialized:  # session έληξε → ξαναπροσπάθησε μία φορά
                self._reset_session()
                return self._call(tool, arguments, _retry=False)
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


# Προτιμώμενος browser (default: Opera). Παρακάμπτεται με env var GPC_BROWSER
# (π.χ. GPC_BROWSER=edge). Κενό = αυτόματη σειρά.
PREFERRED_BROWSER = os.environ.get("GPC_BROWSER", "opera").strip().lower()


def launch_chromium(pw):
    """Εκκινεί headless Chromium-based browser. Σειρά προσπαθειών:
    0) ο προτιμώμενος browser (PREFERRED_BROWSER, default Opera) από τη διαδρομή του,
    1) το Chromium του Playwright (αν κατέβηκε),
    2) Edge/Chrome μέσω channel,
    3) οποιοσδήποτε άλλος Chromium-based browser (Edge/Chrome/Brave/Vivaldi/Opera/Chromium).
    Έτσι, αν ο προτιμώμενος δεν οδηγείται από το Playwright, πέφτει αυτόματα
    σε Edge/Chrome — δεν μένεις ποτέ χωρίς αποτέλεσμα."""
    attempts = []
    cands = _browser_exe_candidates()
    pref = [c for c in cands if PREFERRED_BROWSER and PREFERRED_BROWSER in c.lower()]

    # 0) Προτιμώμενος browser μέσω του exe του
    for exe in pref:
        try:
            return pw.chromium.launch(headless=True, executable_path=exe)
        except Exception as exc:
            attempts.append(f"{os.path.basename(exe)}: {str(exc)[:55]}")
    # 1) Chromium του Playwright
    try:
        return pw.chromium.launch(headless=True)
    except Exception as exc:
        attempts.append(f"chromium: {str(exc)[:70]}")
    # 2) Edge/Chrome μέσω channel
    for channel in ("msedge", "chrome"):
        try:
            return pw.chromium.launch(headless=True, channel=channel)
        except Exception as exc:
            attempts.append(f"{channel}: {str(exc)[:70]}")
    # 3) Υπόλοιποι Chromium-based browsers
    for exe in cands:
        if exe in pref:
            continue
        try:
            return pw.chromium.launch(headless=True, executable_path=exe)
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


def ebay_search(query, limit=25):
    """Αναζήτηση στο eBay.de (τιμές σε EUR) μέσω Playwright/Edge."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return [], f"{EBAY_LABEL}: {PLAYWRIGHT_HINT}"
    url = _EBAY_SEARCH_URL.format(q=urllib.parse.quote(query))
    raw = None
    try:
        with sync_playwright() as pw:
            try:
                browser = launch_chromium(pw)
            except Exception as exc:
                return [], f"eBay: δεν ξεκίνησε browser — {str(exc)[:110]}"
            ctx = browser.new_context(user_agent=_UA, locale="de-DE",
                                      viewport={"width": 1366, "height": 900})
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
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
                browser.close()
    except Exception as exc:
        return [], f"{EBAY_LABEL}: {str(exc)[:120]}"
    rows = []
    for it in (raw or [])[:limit]:
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
    items.push({
      title: (p.name || '').toString().slice(0, 160),
      price: off.price != null ? off.price : (off.lowPrice != null ? off.lowPrice : null),
      image: one(p.image) || '',
      url: p.url || '',
      rating: rat,
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
          for (const li of n.itemListElement) { const it=(li&&li.item)?li.item:li; if (it&&(it['@type']==='Product'||it.name)) add(it); }
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
                           parse_js=None):
    """Γενικός scraper για eshop που εκθέτει JSON-LD ItemList/Product στη σελίδα
    αποτελεσμάτων. Τρέχει μέσω Playwright (δουλεύει και σε server-rendered και σε
    sites που προσθέτουν το JSON-LD με JS). `parse_js` για site-specific parser."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return [], f"{label}: {PLAYWRIGHT_HINT}"
    url = search_url.format(q=urllib.parse.quote(query))
    raw = None
    try:
        with sync_playwright() as pw:
            try:
                browser = launch_chromium(pw)
            except Exception as exc:
                return [], f"{label}: δεν ξεκίνησε browser — {str(exc)[:110]}"
            ctx = browser.new_context(user_agent=_UA, locale="el-GR",
                                      viewport={"width": 1366, "height": 900})
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_selector(wait_selector, timeout=10000)
                    page.wait_for_timeout(600)
                except Exception:
                    pass
                raw = page.evaluate(parse_js or _JSONLD_ITEMLIST_JS)
            finally:
                try:
                    page.close()
                except Exception:
                    pass
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
        avail = it.get("availability") or ""
        rows.append({
            "source": label, "product_id": "",
            "title": title, "image": it.get("image") or "",
            "price_from": price, "offer_count": 1,
            "rating": rating if rating else None,
            "product_url": purl,
            "_direct": {"source": label, "merchant_name": label,
                        "price": price, "url": purl, "availability": avail,
                        "rating": rating if rating else None,
                        "currency": it.get("currency") or "EUR"}})
        if len(rows) >= limit:
            break
    return rows, (f"{label}: {len(rows)} προϊόντα" if rows
                  else f"{label}: δεν βρέθηκαν (ίσως άλλαξε η σελίδα)")


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
    let image = '';
    const pic = c.querySelector('picture source[srcset], img[src], img[data-src]');
    if (pic) { const ss = pic.getAttribute('srcset');
      image = ss ? ss.split(',')[0].trim().split(' ')[0] : (pic.getAttribute('src') || pic.getAttribute('data-src') || ''); }
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
        wait_selector='.ajax_block_product', parse_js=_COSMOS_PARSE_JS)


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


def search_shops(query, labels):
    """Επιστρέφει (rows, diagnostics). Skroutz/Public/Πολιτεία/eBay → Playwright·
    e-shop.gr & Σούπερ Μάρκετ → HTTP/API· τα υπόλοιπα → ειλικρινές μήνυμα."""
    results, diags = [], []
    pw = [l for l in labels if l in PLAYWRIGHT_SEARCH]
    http_simple = {"e-shop.gr", SUPERMARKET_LABEL, POLITEIA_LABEL, EBAY_LABEL,
                   PHARM24_LABEL, EPAPOUTSIA_LABEL, PHARMACY295_LABEL,
                   COSMOS_LABEL, LEROY_LABEL}
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
    if EBAY_LABEL in labels:
        r, diag = ebay_search(query)
        results.extend(r)
        diags.append(diag)
    if PHARM24_LABEL in labels:
        r, diag = pharm24_search(query)
        results.extend(r)
        diags.append(diag)
    if EPAPOUTSIA_LABEL in labels:
        r, diag = epapoutsia_search(query)
        results.extend(r)
        diags.append(diag)
    if PHARMACY295_LABEL in labels:
        r, diag = pharmacy295_search(query)
        results.extend(r)
        diags.append(diag)
    if COSMOS_LABEL in labels:
        r, diag = cosmossport_search(query)
        results.extend(r)
        diags.append(diag)
    if LEROY_LABEL in labels:
        r, diag = leroymerlin_search(query)
        results.extend(r)
        diags.append(diag)
    for l in others:
        if l in UNSUPPORTED_SHOPS:
            diags.append(f"{l}: ειδικό frontend — δεν υποστηρίζεται ακόμη")
        else:
            diags.append(f"{l}: μη υποστηριζόμενο")
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

    if "e-shop.gr" in labels:
        jobs.append(("e-shop.gr", lambda: eshop_search(query)))
    if SUPERMARKET_LABEL in labels:
        jobs.append((SUPERMARKET_LABEL, lambda: supermarket_search(query)))
    if POLITEIA_LABEL in labels:
        jobs.append((POLITEIA_LABEL, lambda: politeia_search(query)))
    if EBAY_LABEL in labels:
        jobs.append((EBAY_LABEL, lambda: ebay_search(query)))
    if PHARM24_LABEL in labels:
        jobs.append((PHARM24_LABEL, lambda: pharm24_search(query)))
    if EPAPOUTSIA_LABEL in labels:
        jobs.append((EPAPOUTSIA_LABEL, lambda: epapoutsia_search(query)))
    if PHARMACY295_LABEL in labels:
        jobs.append((PHARMACY295_LABEL, lambda: pharmacy295_search(query)))
    if COSMOS_LABEL in labels:
        jobs.append((COSMOS_LABEL, lambda: cosmossport_search(query)))
    if LEROY_LABEL in labels:
        jobs.append((LEROY_LABEL, lambda: leroymerlin_search(query)))

    known = ({"BestPrice", "e-shop.gr", SUPERMARKET_LABEL, POLITEIA_LABEL,
              EBAY_LABEL, PHARM24_LABEL, EPAPOUTSIA_LABEL, PHARMACY295_LABEL,
              COSMOS_LABEL, LEROY_LABEL}
             | set(PLAYWRIGHT_SEARCH))
    rows_all, diags = [], []
    for l in labels:
        if l not in known:
            diags.append(f"{l}: {'ειδικό frontend — δεν υποστηρίζεται ακόμη' if l in UNSUPPORTED_SHOPS else 'μη υποστηριζόμενο'}")

    if jobs:
        with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
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




def bestprice_image(product_id):
    """og:image από τη σελίδα προϊόντος BestPrice (από το product_id)."""
    m = re.search(r"\d+", str(product_id or ""))
    if not m:
        return ""
    try:
        html = http_get(f"https://www.bestprice.gr/item/{m.group(0)}/x.html", timeout=15)
        return _meta(html, "og:image")
    except Exception:
        return ""
