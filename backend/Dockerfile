FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    RUN_DATABASE_SETUP=false

WORKDIR /app/backend

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app
COPY backend/start-container.sh ./start-container.sh
COPY database /app/database

RUN python -m pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app \
    && chmod 755 /app/backend/start-container.sh

USER appuser
EXPOSE 8000

CMD ["/app/backend/start-container.sh"]