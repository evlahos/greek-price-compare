# ⚡ Σύγκριση Τιμών — Greek Price Compare

Εφαρμογή σύγκρισης τιμών από μεγάλα ελληνικά e-shops, βιβλιοπωλεία και σούπερ
μάρκετ, με μοντέρνο (dark/neon) HTML περιβάλλον και backend σε Python.

Τρέχει **σαν εφαρμογή σε δικό της παράθυρο** (pywebview) ή **στον browser**, και
προαιρετικά με **Docker**.

## Πηγές
- **BestPrice** — δημόσιο MCP (aggregator δεκάδων καταστημάτων).
- **Skroutz** & **Public** — μέσω headless browser (Playwright ή ο Edge των Windows).
- **e-shop.gr** — απλό HTTP (server-rendered).
- **eBay.de** — αγγελίες σε EUR (μέσω browser).
- **Πολιτεία** — βιβλία (React SPA → browser).
- **Σούπερ Μάρκετ** — επίσημο κρατικό API `posokanei.gov.gr` (Σκλαβενίτης, ΑΒ,
  Μασούτης, My Market, Γαλαξίας…).

## Γρήγορη εκκίνηση (Windows)
1. Κατέβασε/κάνε clone το repo.
2. Διπλό κλικ στο **`ΕΓΚΑΤΑΣΤΑΣΗ.bat`** → στήνει τα πάντα (Python αν λείπει,
   βιβλιοθήκες, Chromium) και ανοίγει την εφαρμογή σε δικό της παράθυρο.
   - Άνοιγμα **στον browser**: **`Στον browser.bat`**.

> Αν το Chromium δεν κατέβει (antivirus/δίκτυο), χρησιμοποιείται αυτόματα ο
> **Edge** των Windows.

### Με Python (οποιοδήποτε OS)
```bash
pip install -r requirements.txt
python -m playwright install chromium   # ή χρησιμοποιείται ο Edge/Chrome
python desktop.py            # native παράθυρο
python desktop.py --browser  # στον browser
```

### Με Docker
```bash
docker compose up --build    # http://localhost:8765
```

## Χαρακτηριστικά
- Κατηγορίες Τεχνολογία / Σούπερ Μάρκετ / Βιβλία.
- Αναζήτηση + «Ακριβές όνομα» (ταιριάζει και ISBN), ιστορικό αναζητήσεων.
- Κάρτες προϊόντων με φωτογραφία & animations· κλικ → πλαϊνή σελίδα με όλα τα
  καταστήματα (ταξινόμηση, ιστορικό τιμής, σύσταση αγοράς, alert τιμής).
- Φίλτρα (τιμή από–έως, διαθέσιμα, βαθμολογία), καλάθι με εξαγωγή CSV.

## Δομή
```
app.py            Flask API
core.py           λογική όλων των πηγών
desktop.py        εκκίνηση ως παράθυρο (pywebview) ή browser
static/index.html όλο το UI (HTML/CSS/JS, dark/neon)
requirements.txt  εξαρτήσεις
Dockerfile, docker-compose.yml
ΕΓΚΑΤΑΣΤΑΣΗ.bat / setup.ps1 / Στον browser.bat   (εγκατάσταση Windows)
legacy_tkinter/   παλιά έκδοση σε Tkinter (ένα αρχείο)
```

## Νομική σημείωση
Για προσωπική χρήση. Επιβεβαίωσε πάντα τελική τιμή, μεταφορικά, διαθεσιμότητα και
παράδοση στο ίδιο το κατάστημα πριν αγοράσεις. Δεν χρησιμοποιεί πληρωμένα κλειδιά.

## License
MIT — δες [LICENSE](LICENSE).
