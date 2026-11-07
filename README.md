# Price Compare — v0.39

> **Greek price & rating comparison across eshops, supermarkets and fuel
> stations** — a desktop (Tkinter/pywebview) & Docker web app. Sources:
> BestPrice, Skroutz, Public, e-shop.gr, Amazon EU, the state supermarket API
> (posokanei.gov.gr) and fuel prices. Features price history & intelligence,
> price alerts/watchlist, a supermarket basket optimizer, cross-country landed
> cost, ratings, photos and CSV export.

A modern HTML/CSS/JS front end (dark/neon) with a Python backend. Runs **as a
standalone-window app** (pywebview) or **in the browser**.

## Install (Windows, one click)
1. **Extract** the zip.
2. Double-click **`INSTALL.bat`** → it sets everything up (Python if missing,
   libraries, Chromium) and opens the app in **its own window**. It also
   creates a "Price Compare" shortcut on the Desktop.
- To open **in the browser**: double-click **`Browser.bat`**.

> If the Chromium download is blocked (antivirus/network), no problem — the app
> automatically uses the Windows **Edge** browser for Skroutz/Public/Politeia.

## Sources
- **BestPrice** (MCP, aggregator), **Skroutz** & **Public** (Playwright/Edge),
  **e-shop.gr** (HTTP), **Politeia** (books), **Supermarket** (posokanei.gov.gr).

## UI features
- Categories Technology / Supermarket / Books (segmented control).
- Search + "Exact name" (with ISBN), search history (autocomplete).
- Product cards with photo and animations; click → **side panel** with all the
  shops (sorting, price history, recommendation, **price alert**).
- Filters (price from–to, in stock, rating ≥).
- **Basket** (drawer) with quantities, total, CSV export — stored locally.

## Docker / web (optional)
```
docker compose up --build   →   http://localhost:8765
```

## Files
- `static/index.html` — the entire UI (HTML/CSS/JS).
- `core.py` — source logic.   `app.py` — Flask API.   `desktop.py` — window/browser.
- `requirements.txt`, `setup.ps1` + `INSTALL.bat` — installation.

## Standalone .exe (no Python on the target machine)
On a Windows PC that has already run `INSTALL.bat`, run `build_exe.bat` **once**
→ it produces `dist\GreekPriceCompare\GreekPriceCompare.exe`. Copy the whole
`dist\GreekPriceCompare` folder to any other computer.

### Changelog 0.39 — 🛒 Basket optimizer + 🌍 landed cost
- **🛒 Supermarket basket optimizer:** add supermarket products to the basket
  and the "Optimize" button computes **which chain is cheapest for the whole
  basket** — with per-chain coverage (which items were found), 🏆 cheapest with
  full coverage, and how much you save. (Per-chain prices are stored per
  product — all frontend, no extra calls.)
- **🌍 Cross-country comparison → LANDED cost:**
  - Added **Amazon.co.uk** with a **live GBP→€ exchange rate** (ECB/frankfurter).
  - Per country: shelf price (€), **net** (−local VAT, fair comparison) and
    **est. landed cost to Greece** = net × Greek VAT 24% + est. shipping.
  - 🇬🇧 outside the EU → flagged for possible duties/customs.
  - **Better matching**: picks the result with the highest token overlap (not
    just the cheapest).

### Changelog 0.38 — ⭐ Price intelligence (all-time low / deal / watchlist)
- **"Price intelligence" block on the product:** automatically on opening a card
  it shows **Low / Median / Now** + a sparkline, with badges **✅ All-time low**,
  **🔥 Deal** (price ≥7% below the median) or **⏳ Pricey now**.
  Source: BestPrice history (180 days) or, otherwise, the local SQLite log (≥5 points).
- **Watchlist:** the 🔔 panel now shows, per product, a mini-sparkline and **%
  change** (from the local history), on top of target/last price.

### Changelog 0.37 — 🌍 Cross-country comparison + alerts/history + UX
- **🌍 Compare with other countries:** on every product (technology/general), a
  button that runs a **real** search for the same product on eurozone Amazons
  (.de/.fr/.it/.es) + the Greek price — all in €, cheapest first, with a
  title/link per country for verification. (No conversions — eurozone only.)
- **🔔 Persistent price alerts (server-side):** stored in `alerts.json` and they
  survive a restart. New 🔔 button in the bar with a badge, list/delete and
  "Check now" (on-demand from BestPrice). Endpoints `/api/alerts*`.
- **📊 Local price history:** every search is logged to SQLite
  (`price_log.db`, max 5,000). 📊 button on the product → sparkline + table.
  Endpoints `GET/DELETE /api/price_log`.
- **Results sorting:** dropdown in the filters (Price ↑/↓, Rating ↓).
- **📋 Copy price** to the clipboard; the "In stock" filter now works correctly
  for Supermarket (explicit `in_stock` flag).
- Standard library only (sqlite3/uuid) — no new dependencies.

### Changelog 0.36 — ⛽ PER-STATION prices (names, map, Google ratings)
- In the ⛽ Fuel category, a new view **"Stations (names & prices)"** next to the
  prefecture averages: pick a **prefecture** → a list of stations with **name,
  brand, area, prices per fuel (95/98/100/diesel/heating/LPG/CNG), Google ★ and a
  map link**. Name/area filter, fuel selection, sorting & 🟢 cheapest.
- Source: **fuelGR open dataset** (athanasso/fuelGR-scraper, GitHub Releases;
  data from deixto.gr/e-Katanalotis/Ministry of Development) — 4,500+ stations,
  ~2×/day, no Cloudflare, downloaded directly from GitHub. core.fuel_stations()
  + /api/fuel_stations (cache 2h). This covers the request for per-station prices
  (the official fuelprices.gr only gives prefecture averages; /CheckPrices is a
  stateful windows-1253 form).

### Changelog 0.35 — Ratings everywhere, AADE seals, fixes
- **Ratings on more sources:** central merge of ratings from the page's JSON-LD
  (covers Pharm24/Pharmacy295/Cosmos/Leroy/Moustakas/Sephora/Hondos where they
  expose them) + review count shown on the card (★ 4.5 (123)).
- **⚠️ Station seals/violations (AADE):** in the ⛽ Fuel category, a feed of
  recent AADE announcements about seals/adulteration (date + title + link).
  Clearly informational per area/case — NOT a per-station history (names are
  usually not published). /api/fuel_penalties, cache 6h.
- **ePapoutsia & other eshops:** when results are capped at the limit, an
  "N+ — narrow your search" indicator (e.g. "adidas" → 3,304 on the site, we show
  the first ones).
- **Skroutz/Cloudflare:** stealth (hiding navigator.webdriver) in the Playwright
  path for fewer blocks (best-effort; Cloudflare remains intermittent).
- Note: **per-station** fuel prices do not exist in a public source (the official
  Observatory only gives prefecture averages); the per-prefecture view remains.

### Changelog 0.34 — ⛽ New "Fuel" category (official Observatory)
- New **"⛽ Fuel"** category: average retail prices from the **Liquid Fuel Price
  Observatory** (Ministry of Development, fuelprices.gr) — daily PDF bulletins.
  - **National view** (tiles): Unleaded 95/100, road Diesel, LPG (Autogas),
    Heating Oil — average price + number of stations.
  - **Per-prefecture table** (51 prefectures): prefecture filter, sorting per
    fuel, 🟢 cheapest / 🔴 most expensive prefecture per column.
  - Backend: `core.fuel_prices()` (downloads the latest bulletin, parses with
    pdfplumber, 1h cache) + `/api/fuel`. New dependency: `pdfplumber`.
- **setup.ps1:** reinstalls libraries when requirements.txt changes (so new
  dependencies are installed on restart, with no manual flag cleanup).
- Live-verified on Sophia: downloaded & read the 29/10/2026 bulletin (51 prefectures).
- (Re-examined "per-station penalty history": there is no structured public
  source/API per station — only unstructured DIMEA announcements; not implemented.)

### Changelog 0.33 — eBay removed from Technology (anti-bot) + live verification
- **Live verification on Sophia** (real network): Skroutz ✅ (works, no
  Cloudflare), BestPrice/Public/e-shop.gr/Amazon.de ✅, streaming/filters/per-source
  status ✅, unit price ✅, best-price badges ✅, theme ✅.
- **eBay: removed from Technology.** Confirmed eBay.de has strong anti-bot
  protection: our parser is correct (extracts 25 products from the same HTML),
  but the server-side paths (HTTP + headless Playwright) are blocked. We tried
  browser-like headers (sec-ch-ua/Sec-Fetch), accepting the DSGVO consent, and
  stealth (hiding navigator.webdriver) — to no avail. **Amazon.de covers** the
  European technology prices. The eBay scraper stays in the code (for a possible
  future eBay Browse API). The consent/stealth improvements were kept (generally useful).

### Changelog 0.32 — Per-source skeletons & Stop/Refresh
- **Trailing skeletons:** while a source is still loading, grey placeholder cards
  appear at the end of the grid — making it clear that "more is coming".
- **⏹ Stop button:** immediately stops the progressive search without waiting for
  the slow sources (keeps what was found). It then becomes **↻ Refresh** to re-run.

### Changelog 0.31 — Progressive search & per-source filters
- **Results streaming (SSE):** each source's products appear **as soon as they
  arrive** instead of waiting for all to finish — the app feels much faster. New
  endpoint `/api/search_stream`, with automatic fallback to `/api/search`.
- **Per-source status indicators:** chips with live status — 🟡 loading → 🟢 N
  results / 🔴 blocked (with a tooltip, e.g. Cloudflare). Makes it immediately
  clear which source worked and which didn't.
- **Per-source filters:** clicking a chip hides/shows that shop's products within
  the results.

### Changelog 0.30 — UI improvements
- **Unit price** (€/kg, €/lt, €/pc) for supermarkets — computed from the size in
  the title (with multi-pack support e.g. 6×1.5L), on the card & in the side
  panel. Makes products of different sizes comparable.
- **"💶 CHEAPEST" badge** on the cheapest product in the results, and in a
  product's offers **"you save €X (−Y%)"** (cheapest ↔ most expensive).
- **Light/dark theme** — 🌙/☀ toggle top-right, stored locally.
- **Keyboard shortcuts:** `/` focus search, `Esc` close, `←/→` next/previous
  product when the side panel is open.

### Changelog 0.29 — European price summary
- The **"🇪🇺 EU price"** panel now shows, above the per-country list, a
  **summary**: 🌍 number of countries, **min**, **average**, **max** price.
- **Greece ↔ European average comparison:** green "X% below ✓" when the Greek
  price is cheaper, red "X% above" when more expensive. Bilingual (EL/EN).

### Changelog 0.28 — Fixes from feedback
- **Browser engine (Opera out):** Opera does NOT run headless (it opened a
  visible window & couldn't be controlled — it broke Skroutz/eBay). Default is
  now bundled Chromium → Edge/Chrome channel (invisible, reliable). *(#1,2,3,5,6)*
- **Skroutz/Cloudflare:** Skroutz went behind Cloudflare — more time + reload +
  a clear message when blocked. Best-effort; BestPrice/Public cover the same
  ground. *(#2,3,6)*
- **ePapoutsia image:** fixed truncation (the CDN URL has commas). *(#4)*
- **Image zoom:** click a product photo → magnify (ESC/click closes). *(#7)*

### Changelog 0.27 — European supermarket prices (indicative)
- **"🇪🇺 EU price"** button on supermarket products: name → barcode
  (Open Food Facts) → **crowdsourced prices per country** (Open Prices), in €,
  compared with the Greek price. Clearly marked as **indicative/not live**.
- Investigated & rejected (documented): posokanei API (GR only, no barcode/foreign
  prices), Greek Lidl (online catalog = own-brands/non-food, not a supermarket —
  "coca cola" → chocolates), foreign portals (apps/no API, no common barcode for
  matching).
- Open Prices limitations: sparse coverage, mostly popular brands & France.

### Changelog 0.26
- **▶ Videos (YouTube):** a button on the product page with 2-3 embedded
  presentations/reviews (ideal for technology); fallback link if none are found.
- **English file names:** `INSTALL.bat`, `Browser.bat`, `READ_ME.txt`
  ("Price Compare" shortcut).
- **🇪🇺 badge** on European sources (eBay, Amazon) — GR↔Europe comparison for
  technology. *(Supermarket cross-Europe is not feasible — there is no common
  price/product-matching data across countries.)*

### Changelog 0.25
- **eBay parser fix** (split-per-card): verified live 60/60 products.
- **Amazon.de** (Technology) — Playwright + DOM parser, clean /dp/ASIN URLs.
  *(anti-bot: in headless it may occasionally return 0 — graceful.)*
- Verified live: eBay (60/60), BestPrice photo (`/item/{id}` og:image), Amazon (20).

### Changelog 0.24 — Code review fixes + bugfixes
- **eBay works again:** HTTP-first (the SRP is server-rendered & cookie-free →
  bypasses consent/headless) with a Playwright fallback.
- **BestPrice photo:** capture image from the MCP + lazy-load in the grid
  (`/api/bp_image`, with cache) — doesn't block the search.
- #1 Concurrent-browser limit (`GPC_MAX_PARALLEL`, default 4) — RAM/CPU protection.
- #2 Thread-lock on BestPrice (safe with concurrent /api/offers etc.).
- #3 `http_get` respects the encoding in the cloudscraper path too (iso-8859-7).
- #4 SSRF guard on `/api/fetch_url` (blocks loopback/private/internal).
- #5 Proper browser cleanup (try/finally) in all Playwright functions.
- #6 `DIRECT_SOURCES` registry — adding a source = 1 line (instead of 5 places).
- Polish: cleaner diagnostics, longer settle on AJAX/SPA (Cosmos/Hondos),
  BestPrice limit raised (8→16).

### Changelog 0.23 — Cosmetics (Health & Beauty)
- **Sephora** — server-rendered JSON-LD ItemList (generic engine; url in the ListItem).
- **Hondos Center** — SPA render + CSS grid (`[class*="ProductCard"]`, price
  `.ProductPrice-PriceValue`). Live test: ~40 products/search.
- (Beautyworld = parked domain; skipped.)

### Changelog 0.22
- **New "Toys" 🧸 category** with **Moustakas** (direct, SSR grid — live test:
  48 products with price+image) + BestPrice/Skroutz.
- Checked & NO: Zakcret (JS search), Protoporia (custom), Praktiker (JS),
  **Multirama → redirects to Public** (like MediaMarkt).

### Changelog 0.21 — More direct sources (live-checked)
- **Pharmacy295** (Health & Beauty) — JSON-LD ItemList, no brand redirect.
- **Cosmos Sport** (Sports) — PrestaShop grid (AJAX render).
- **Leroy Merlin** (Home) — server-rendered grid `.product-miniature`.
- Checked & NO (SPA/closed): You.gr, e-Jumbo, Factory Outlet, MyShoe(closed),
  Kotsovolos, Plaisio, MediaMarkt(→Public), Pharmacy4u. The aggregators catch them.

### Changelog 0.20
- **ePapoutsia** (direct) in the "Fashion" category — shoes/accessories (Nuxt SSR,
  eobuwie/MODIVO group). Tested live: ~72 products/search with price+image.
- Additional check of large chains: **e-jumbo** = AJAX-rendered results (hard),
  **Kotsovolos/Plaisio** = API SPAs, **MediaMarkt→Public**. The aggregators cover them.

### Changelog 0.19 — Phase 2 (direct sources)
- **Pharm24** (direct online pharmacy) in the "Health & Beauty" category — via a
  generic **JSON-LD ItemList engine** (`jsonld_itemlist_search`), which reads
  schema.org Product from the results page (no fragile CSS selectors). Adding a
  new eshop = just a label + a search URL.
- Electronics: the big retailers changed platform — **MediaMarkt.gr → redirects
  to Public.gr** (already integrated), **Kotsovolos/Plaisio** = API-driven SPAs
  (fragile). Electronics are already covered directly by **Public + e-shop.gr** +
  aggregators.

### Changelog 0.18
- **Bilingual UI (EL / EN)** — language toggle top-right; all interface text
  changes instantly (categories, buttons, filters, basket, comparison, chart,
  messages). The choice is stored locally; initial language from the browser.
  *(Product/shop names stay as they come from the sources.)*

### Changelog 0.16
- **Parallel search** — all sources run together (much faster).
- **Side-by-side comparison** of 2–3 products.
- **Price history chart** (sparkline) in the side panel.
- **Branding**: neon icon (app.ico) + favicon, standalone `.exe` (build_exe.bat).
- Wide browser net (Edge/Chrome/Brave/Vivaldi/Opera/Chromium, Win/mac/Linux).

### Changelog 0.15
- Brand-new dark/neon UI, native window (pywebview) or browser.
- Edge fallback (no Chromium download needed).
- From Kiro: BestPrice session reset+retry, HTTP backoff (429/503), log rotation,
  requirements.txt, search history, filters, price alerts.
