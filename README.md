# Σύγκριση Τιμών / Price Compare — v0.18 (δίγλωσσο UI)

Μοντέρνο HTML/CSS/JS περιβάλλον (dark/neon) με backend Python. Τρέχει **σαν
εφαρμογή σε δικό της παράθυρο** (pywebview) ή **στον browser**.

## Εγκατάσταση (Windows, με ένα κλικ)
1. Κάνε **εξαγωγή** του zip.
2. Διπλό κλικ στο **`ΕΓΚΑΤΑΣΤΑΣΗ.bat`** → στήνει τα πάντα (Python αν λείπει,
   βιβλιοθήκες, Chromium) και ανοίγει την εφαρμογή σε **δικό της παράθυρο**.
   Φτιάχνει και συντόμευση «Σύγκριση Τιμών» στην Επιφάνεια Εργασίας.
- Για άνοιγμα **στον browser**: διπλό κλικ στο **`Στον browser.bat`**.

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
- `requirements.txt`, `setup.ps1` + `ΕΓΚΑΤΑΣΤΑΣΗ.bat` — εγκατάσταση.

## Standalone .exe (χωρίς Python στον τελικό υπολογιστή)
Σε Windows PC που έχει ήδη τρέξει το `ΕΓΚΑΤΑΣΤΑΣΗ.bat`, τρέξε **μία φορά** το
`build_exe.bat` → παράγει `dist\GreekPriceCompare\GreekPriceCompare.exe`.
Αντίγραψε όλο τον φάκελο `dist\GreekPriceCompare` σε οποιονδήποτε άλλο υπολογιστή.

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
