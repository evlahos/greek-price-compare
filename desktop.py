# -*- coding: utf-8 -*-
"""Εκκίνηση της εφαρμογής ως native παράθυρο (pywebview) ή στον browser.

  python desktop.py            → ανοίγει σε δικό του παράθυρο (σαν εφαρμογή)
  python desktop.py --browser  → ανοίγει στον προεπιλεγμένο browser

Ο Flask server τρέχει τοπικά στο 127.0.0.1 και δεν εκτίθεται στο δίκτυο.
"""
from __future__ import annotations

import os
import sys
import time
import threading
import webbrowser
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from app import app  # noqa: E402

PORT = int(os.environ.get("PORT", "8765"))
URL = f"http://127.0.0.1:{PORT}/"


def _serve():
    app.run(host="127.0.0.1", port=PORT, threaded=True, use_reloader=False, debug=False)


def _wait_ready(timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(URL, timeout=0.6)
            return True
        except Exception:
            time.sleep(0.12)
    return False


def main():
    threading.Thread(target=_serve, daemon=True).start()
    _wait_ready()

    browser_mode = "--browser" in sys.argv
    if not browser_mode:
        try:
            import webview  # pywebview
            webview.create_window(
                "Σύγκριση Τιμών", URL,
                width=1280, height=840, min_size=(900, 600),
                background_color="#070b16")
            webview.start()  # μπλοκάρει μέχρι να κλείσει το παράθυρο
            return
        except Exception:
            browser_mode = True  # αν λείπει το pywebview → browser

    webbrowser.open(URL)
    print(f"Η εφαρμογή τρέχει στο {URL}")
    print("Κλείσε αυτό το παράθυρο για να σταματήσει.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
