FROM python:3.12.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY owner_webhook/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY owner_webhook ./owner_webhook
RUN useradd --uid 10001 --create-home relay
USER relay
CMD ["sh", "-c", "exec uvicorn owner_webhook.app:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --limit-concurrency 8 --timeout-keep-alive 5 --no-access-log"]
