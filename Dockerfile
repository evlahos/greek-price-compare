# Επίσημο Playwright image — περιλαμβάνει Python + Playwright + Chromium έτοιμα.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

# Server-only deps (playwright+chromium ήδη στο base image· το pywebview είναι
# μόνο για την desktop έκδοση και ΔΕΝ χρειάζεται εδώ).
RUN pip install --no-cache-dir "flask>=3.0,<4" "pillow>=10.0"

COPY core.py app.py ./
COPY static ./static

ENV PORT=8765
EXPOSE 8765

CMD ["python", "app.py"]
