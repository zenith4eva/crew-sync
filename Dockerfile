# Single image: builds the UI, serves it and the API from uvicorn on :8000.
# Run: docker run -p 8000:8000 -e META_API_KEY=... -e ALLOWED_ORIGIN=https://your.host -v crewsync-data:/app/data crew-sync
FROM node:20-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
# Node runs only Meta's mask decoder (backend/meta/decode_masks.mjs).
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/meta/package.json backend/meta/package-lock.json backend/meta/
RUN cd backend/meta && npm ci --omit=dev
COPY backend/ backend/
COPY --from=ui /ui/dist frontend/dist
RUN useradd -m app && mkdir -p data && chown app data
USER app
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "backend.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
