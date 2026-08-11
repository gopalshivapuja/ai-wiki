# Stage 1: Build React frontend
FROM node:22-alpine AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm ci --ignore-scripts 2>/dev/null || npm install
COPY apps/web/ ./
RUN npm run build

# Stage 2: Python app
FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev gcc && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY packages/ packages/
COPY wiki/ wiki/
COPY sources/ sources/

RUN pip install --no-cache-dir .

COPY --from=web /web/dist /app/static

ENV STATIC_DIR=/app/static
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

EXPOSE 8000

CMD uvicorn wiki_api.app:app --host 0.0.0.0 --port ${PORT}
