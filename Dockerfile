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

# ffmpeg is required by yt-dlp to extract audio for transcription.
# psycopg2-binary ships prebuilt wheels, so no gcc/libpq-dev/compiler in the final image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# README.md is referenced by pyproject's `readme` field; without it setuptools warns and
# ships a wheel with no description.
COPY pyproject.toml README.md ./
COPY packages/ packages/
COPY seed/ seed/

RUN pip install --no-cache-dir .

COPY --from=web /web/dist /app/static

ENV STATIC_DIR=/app/static
# Without this the seeder resolves relative to site-packages and imports nothing.
ENV WIKI_SEED_DIR=/app
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD uvicorn wiki_api.app:app --host 0.0.0.0 --port ${PORT} --workers 1
