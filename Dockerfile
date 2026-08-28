# All-in-one image for Railway (single origin): build the frontend, then serve
# it plus the API from FastAPI. This keeps the admin session cookie first-party.

# --- 1. Build the frontend ---
FROM node:20-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- 2. Backend + static frontend ---
FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
# FastAPI serves this directory as the SPA (see app/main.py).
COPY --from=frontend /fe/dist ./static

# Railway injects $PORT.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
