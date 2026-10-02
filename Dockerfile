FROM python:3.12.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements*.txt ./
RUN python -m pip install --no-cache-dir -r requirements-frozen-plate.txt

COPY . .

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# The shared image starts the correct process only for the approved staging services.
CMD ["/bin/sh", "-c", "case \"$RENDER_SERVICE_NAME\" in oplates-pricing-api-staging) exec uvicorn api_app:app --host 0.0.0.0 --port ${PORT:-10000} ;; oplates-customer-ui-staging) exec streamlit run app.py --server.address 0.0.0.0 --server.port ${PORT:-10000} --server.headless true ;; *) echo 'Unrecognized staging service' >&2; exit 1 ;; esac"]
