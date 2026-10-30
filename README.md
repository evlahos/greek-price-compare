# Σύγκριση Τιμών / Price Compare — v0.32

Μοντέρνο HTML/CSS/JS περιβάλλον (dark/neon) με backend Python. Τρέχει **σαν
εφαρμογή σε δικό της παράθυρο** (pywebview) ή **στον browser**.

## Εγκατάσταση (Windows, με ένα κλικ)
1. Κάνε **εξαγωγή** του zip.
2. Διπλό κλικ στο **`INSTALL.bat`** → στήνει τα πάντα (Python αν λείπει,
   βιβλιοθήκες, Chromium) και ανοίγει την εφαρμογή σε **δικό της παράθυρο**.
   Φτιάχνει και συντόμευση «Price Compare» στην Επιφάνεια Εργασίας.
- Για άνοιγμα **στον browser**: διπλό κλικ στο **`Browser.bat`**.

> Αν το κατέβασμα του Chromium μπλοκάρει (antivirus/δίκτυο), δεν πειράζει — η
> εφαρμογή χρησιμοποιεί αυτόματα τον **Edge** των Windows για Skroutz/Public/Πολιτεία.

## Πηγές
- **BestPrice** (MCP, aggregator), **Skroutz** & **Public** (Playwright/Edge),
  **e-shop.gr** (HTTP), **Πολιτεία** (βιβλία), **Σούπερ Μάρκετ** (posokanei.gov.gr).

## Χαρακτηριστικά UI
- Κατηγορίες Τεχνολογία / Σούπερ Μάρκετ / Βιβλία (segmented control).
- Αναζήτηση + «Ακριβές όνομα» (με ISBN), ιστορικό αναζητήσεων (autocomplete).
- Κάρτες προϊόντων με φωτογραφία, animations· κλικ → **πλαϊνή σελίδα** με όλα
  τα καταστήματα (ταξινόμηση, ιστορικό τιμής, σύσταση, **alert τιμής**).
- Φίλτρα (τιμή από–έως, διαθέσιμα, βαθμολογία ≥).
- **Καλάθι** (drawer) με ποσότητες, σύνολο, εξαγωγή CSV — αποθηκεύεται τοπικά.

## Docker / web (προαιρετικά)
```
docker compose up --build   →   http://localhost:8765
```

## Αρχεία
- `static/index.html` — όλο το UI (HTML/CSS/JS).
- `core.py` — λογική πηγών.   `app.py` — Flask API.   `desktop.py` — παράθυρο/browser.
- `requirements.txt`, `setup.ps1` + `INSTALL.bat` — εγκατάσταση.

## Standalone .exe (χωρίς Python στον τελικό υπολογιστή)
Σε Windows PC που έχει ήδη τρέξει το `INSTALL.bat`, τρέξε **μία φορά** το
`build_exe.bat` → παράγει `dist\GreekPriceCompare\GreekPriceCompare.exe`.
Αντίγραψε όλο τον φάκελο `dist\GreekPriceCompare` σε οποιονδήποτε άλλο υπολογιστή.

### Αλλαγές 0.32 — Skeletons ανά πηγή & Διακοπή/Ανανέωση
- **Trailing skeletons:** όσο κάποια πηγή ακόμη φορτώνει, εμφανίζονται γκρίζες
  placeholder κάρτες στο τέλος του grid — ξεκάθαρο ότι «έρχονται κι άλλα».
- **Κουμπί ⏹ Διακοπή:** σταματά αμέσως την προοδευτική αναζήτηση χωρίς να περιμένεις
  τις αργές πηγές (κρατά όσα βρέθηκαν). Μετά γίνεται **↻ Ανανέωση** για επανεκτέλεση.

### Αλλαγές 0.31 — Προοδευτική αναζήτηση & φίλτρα ανά πηγή
- **Streaming αποτελεσμάτων (SSE):** τα προϊόντα κάθε πηγής εμφανίζονται **μόλις
  έρθουν** αντί να περιμένεις να τελειώσουν όλες — η εφαρμογή νιώθει πολύ πιο
  γρήγορη. Νέο endpoint `/api/search_stream`, με αυτόματο fallback στο `/api/search`.
- **Δείκτες κατάστασης ανά πηγή:** chips με ζωντανό status — 🟡 φόρτωση → 🟢 N
  αποτελέσματα / 🔴 μπλοκαρίστηκε (με tooltip, π.χ. Cloudflare). Ξεκαθαρίζει αμέσως
  ποια πηγή δούλεψε και ποια όχι.
- **Φίλτρα ανά πηγή:** κλικ σε ένα chip κρύβει/δείχνει τα προϊόντα εκείνου του
  καταστήματος μέσα στα αποτελέσματα.

### Αλλαγές 0.30 — Βελτιώσεις UI
- **Τιμή ανά μονάδα** (€/kg, €/lt, €/τεμ) στα σούπερ μάρκετ — υπολογισμός από το
  μέγεθος στον τίτλο (με υποστήριξη πολυσυσκευασίας π.χ. 6×1.5L), στην κάρτα & στο
  πλάι. Κάνει συγκρίσιμα προϊόντα διαφορετικού μεγέθους.
- **Σήμανση «💶 ΧΑΜΗΛΟΤΕΡΗ»** στο φθηνότερο προϊόν των αποτελεσμάτων, και στις
  προσφορές ενός προϊόντος **«κερδίζεις €X (−Y%)»** (φθηνότερο ↔ ακριβότερο).
- **Θέμα φωτεινό/σκοτεινό** — διακόπτης 🌙/☀ πάνω δεξιά, αποθηκεύεται τοπικά.
- **Keyboard shortcuts:** `/` εστίαση αναζήτησης, `Esc` κλείσιμο, `←/→` επόμενο/
  προηγούμενο προϊόν όταν είναι ανοιχτή η πλαϊνή σελίδα.

### Αλλαγές 0.29 — Σύνοψη ευρωπαϊκών τιμών
- Το παράθυρο **«🇪🇺 Ευρ. τιμή»** δείχνει πλέον, πάνω από τη λίστα ανά χώρα, μια
  **σύνοψη**: 🌍 πλήθος χωρών, **ελάχιστη**, **μέσος όρος**, **μέγιστη** τιμή.
- **Σύγκριση Ελλάδας ↔ ευρωπαϊκού μέσου όρου:** πράσινο «X% κάτω ✓» όταν η
  ελληνική είναι φθηνότερη, κόκκινο «X% πάνω» όταν ακριβότερη. Δίγλωσσο (ΕΛ/EN).

### Αλλαγές 0.28 — Διορθώσεις από παρατηρήσεις
- **Browser engine (Opera εκτός):** η Opera ΔΕΝ τρέχει headless (άνοιγε ορατό
  παράθυρο & δεν ελεγχόταν — έσπαγε Skroutz/eBay). Default πλέον bundled Chromium
  → Edge/Chrome channel (αόρατα, αξιόπιστα). *(#1,2,3,5,6)*
- **Skroutz/Cloudflare:** το Skroutz μπήκε πίσω από Cloudflare — περισσότερος
  χρόνος + reload + σαφές μήνυμα όταν μπλοκάρει. Best-effort· οι BestPrice/Public
  καλύπτουν το ίδιο έδαφος. *(#2,3,6)*
- **ePapoutsia εικόνα:** διόρθωση truncation (το CDN URL έχει κόμματα). *(#4)*
- **Zoom εικόνας:** κλικ στη φωτογραφία προϊόντος → μεγέθυνση (ESC/κλικ κλείνει). *(#7)*

### Αλλαγές 0.27 — Ευρωπαϊκές τιμές σούπερ μάρκετ (ενδεικτικές)
- Κουμπί **«🇪🇺 Ευρ. τιμή»** σε προϊόντα σούπερ μάρκετ: όνομα → barcode
  (Open Food Facts) → **crowdsourced τιμές ανά χώρα** (Open Prices), σε €, με
  σύγκριση με την ελληνική τιμή. Σαφώς σημασμένο ως **ενδεικτικό/όχι live**.
- Διερευνήθηκαν & απορρίφθηκαν (τεκμηριωμένα): posokanei API (μόνο GR, χωρίς
  barcode/ξένες τιμές), ελληνικό Lidl (online κατάλογος = own-brands/non-food,
  όχι σούπερ μάρκετ — «coca cola» → σοκολάτες), ξένα portals (apps/χωρίς API,
  χωρίς κοινό barcode για matching).
- Περιορισμοί Open Prices: αραιή κάλυψη, κυρίως δημοφιλή επώνυμα & Γαλλία.

### Αλλαγές 0.26
- **▶ Βίντεο (YouTube):** κουμπί στη σελίδα προϊόντος με 2-3 ενσωματωμένες
  παρουσιάσεις/reviews (ιδανικό για τεχνολογία)· fallback link αν δεν βρεθούν.
- **Αγγλικά ονόματα αρχείων:** `INSTALL.bat`, `Browser.bat`, `READ_ME.txt`
  (συντόμευση «Price Compare»).
- **Σήμανση 🇪🇺** σε ευρωπαϊκές πηγές (eBay, Amazon) — σύγκριση ΕΛ↔Ευρώπη
  για τεχνολογία. *(Σούπερ μάρκετ cross-Europe δεν είναι εφικτό — δεν υπάρχει
  κοινό δεδομένο τιμών/αντιστοίχισης προϊόντων μεταξύ χωρών.)*

### Αλλαγές 0.25
- **eBay parser διόρθωση** (split-ανά-κάρτα): επικυρώθηκε live 60/60 προϊόντα.
- **Amazon.de** (Τεχνολογία) — Playwright + DOM parser, καθαρά /dp/ASIN URLs.
  *(anti-bot: σε headless μπορεί περιστασιακά να γυρίσει 0 — graceful.)*
- Επικυρώθηκαν live: eBay (60/60), BestPrice φωτο (`/item/{id}` og:image), Amazon (20).

### Αλλαγές 0.24 — Code review fixes + bugfixes
- **eBay ξαναδουλεύει:** HTTP-first (το SRP είναι server-rendered & χωρίς cookies →
  παρακάμπτει consent/headless) με Playwright fallback.
- **BestPrice φωτο:** capture image από το MCP + lazy-load στο grid (`/api/bp_image`,
  με cache) — δεν μπλοκάρει την αναζήτηση.
- #1 Όριο ταυτόχρονων browsers (`GPC_MAX_PARALLEL`, default 4) — προστασία RAM/CPU.
- #2 Thread-lock στο BestPrice (ασφαλές με ταυτόχρονα /api/offers κ.λπ.).
- #3 `http_get` σέβεται το encoding και στο cloudscraper path (iso-8859-7).
- #4 SSRF guard στο `/api/fetch_url` (μπλοκάρει loopback/private/internal).
- #5 Σωστό browser cleanup (try/finally) σε όλες τις Playwright συναρτήσεις.
- #6 Μητρώο `DIRECT_SOURCES` — προσθήκη πηγής = 1 γραμμή (αντί για 5 σημεία).
- Polish: καθαρότερα diagnostics, μεγαλύτερο settle σε AJAX/SPA (Cosmos/Hondos),
  αύξηση BestPrice limit (8→16).

### Αλλαγές 0.23 — Καλλυντικά (Υγεία & Ομορφιά)
- **Sephora** — server-rendered JSON-LD ItemList (generic engine· url στο ListItem).
- **Hondos Center** — SPA render + CSS grid (`[class*="ProductCard"]`, τιμή
  `.ProductPrice-PriceValue`). Δοκιμή live: ~40 προϊόντα/αναζήτηση.
- (Beautyworld = parked domain· παραλείφθηκε.)

### Αλλαγές 0.22
- **Νέα κατηγορία «Παιχνίδια» 🧸** με **Moustakas** (απευθείας, SSR grid — δοκιμή
  live: 48 προϊόντα με τιμή+εικόνα) + BestPrice/Skroutz.
- Ελεγμένα & ΟΧΙ: Zakcret (JS search), Protoporia (custom), Praktiker (JS),
  **Multirama → redirect στο Public** (όπως MediaMarkt).

### Αλλαγές 0.21 — Περισσότερες απευθείας πηγές (live-checked)
- **Pharmacy295** (Υγεία & Ομορφιά) — JSON-LD ItemList, χωρίς brand redirect.
- **Cosmos Sport** (Αθλητικά) — PrestaShop grid (AJAX render).
- **Leroy Merlin** (Σπίτι) — server-rendered grid `.product-miniature`.
- Ελεγμένα & ΟΧΙ (SPA/κλειστά): You.gr, e-Jumbo, Factory Outlet, MyShoe(κλειστό),
  Κωτσόβολος, Πλαίσιο, MediaMarkt(→Public), Pharmacy4u. Τα πιάνουν οι aggregators.

### Αλλαγές 0.20
- **ePapoutsia** (απευθείας) στην κατηγορία «Μόδα» — παπούτσια/αξεσουάρ (Nuxt SSR,
  όμιλος eobuwie/MODIVO). Δοκιμασμένο live: ~72 προϊόντα/αναζήτηση με τιμή+εικόνα.
- Πρόσθετος έλεγχος μεγάλων αλυσίδων: **e-jumbo** = AJAX-rendered results (δύσκολο),
  **Κωτσόβολος/Πλαίσιο** = API SPAs, **MediaMarkt→Public**. Οι aggregators τις καλύπτουν.

### Αλλαγές 0.19 — Φάση 2 (απευθείας πηγές)
- **Pharm24** (απευθείας online φαρμακείο) στην κατηγορία «Υγεία & Ομορφιά» —
  μέσω γενικού **JSON-LD ItemList engine** (`jsonld_itemlist_search`), που διαβάζει
  schema.org Product από τη σελίδα αποτελεσμάτων (χωρίς εύθραυστα CSS selectors).
  Προσθήκη νέου eshop = απλώς label + URL αναζήτησης.
- Electronics: οι μεγάλοι retailers άλλαξαν πλατφόρμα — **MediaMarkt.gr → ανακατευθύνει
  στο Public.gr** (ήδη ενσωματωμένο), **Κωτσόβολος/Πλαίσιο** = API-driven SPAs (εύθραυστα).
  Τα electronics καλύπτονται ήδη απευθείας από **Public + e-shop.gr** + aggregators.

### Αλλαγές 0.18
- **Δίγλωσσο UI (ΕΛ / EN)** — διακόπτης γλώσσας πάνω δεξιά· όλα τα κείμενα του
  περιβάλλοντος αλλάζουν αμέσως (κατηγορίες, κουμπιά, φίλτρα, καλάθι, σύγκριση,
  γράφημα, μηνύματα). Η επιλογή αποθηκεύεται τοπικά· αρχική γλώσσα από τον browser.
  *(Τα ονόματα προϊόντων/καταστημάτων μένουν όπως έρχονται από τις πηγές.)*

### Αλλαγές 0.16
- **Παράλληλη αναζήτηση** — όλες οι πηγές τρέχουν μαζί (πολύ πιο γρήγορα).
- **Σύγκριση side-by-side** 2–3 προϊόντων.
- **Γράφημα ιστορικού τιμής** (sparkline) στην πλαϊνή σελίδα.
- **Branding**: neon εικονίδιο (app.ico) + favicon, standalone `.exe` (build_exe.bat).
- Ευρύ δίχτυ browsers (Edge/Chrome/Brave/Vivaldi/Opera/Chromium, Win/mac/Linux).

### Αλλαγές 0.15
- Ολοκαίνουργιο dark/neon UI, native παράθυρο (pywebview) ή browser.
- Edge fallback (δεν χρειάζεται το κατέβασμα Chromium).
- Από Kiro: BestPrice session reset+retry, HTTP backoff (429/503), log rotation,
  requirements.txt, ιστορικό αναζητήσεων, φίλτρα, price alerts.
