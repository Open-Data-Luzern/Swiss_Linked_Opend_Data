# Portal «Swiss Open Linked Data». Build-Kontext: der Ordner portal/.
#   docker compose -f deploy/compose.yaml build
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --create-home --uid 1000 portal

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY swiss_portal/ swiss_portal/
COPY web/ web/
COPY daten/gemeindeverzeichnis_2026-01-01.csv daten/
COPY daten/extraktion/SCHEMA.md daten/extraktion/

USER portal
EXPOSE 8040
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8040/gesund', timeout=4)"
# Ein Worker: Anfragebegrenzung und Graph-Cache liegen im Prozess. Synchrone
# Endpunkte laufen ohnehin parallel im Threadpool.
CMD ["uvicorn", "swiss_portal.app:app", "--host", "0.0.0.0", "--port", "8040", "--proxy-headers", "--forwarded-allow-ips", "*"]
