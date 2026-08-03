FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY support_desk ./support_desk
RUN pip install --no-cache-dir .

COPY index.html app.js styles.css ./
RUN useradd --create-home --uid 10001 support \
    && mkdir -p /app/data/runtime \
    && chown -R support:support /app

USER support
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

CMD ["uvicorn", "support_desk.main:app", "--host", "0.0.0.0", "--port", "8000"]
