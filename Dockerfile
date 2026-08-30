FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 swingdesk \
    && mkdir /data \
    && chown swingdesk:swingdesk /data

COPY --chown=swingdesk:swingdesk . .

USER swingdesk
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8080\")}/healthz', timeout=3)"

CMD ["sh", "-c", "waitress-serve --listen=0.0.0.0:${PORT} --call dashboard:create_app"]