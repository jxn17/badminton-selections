FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg2 wheels are already covered by the binary package.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# On boot: run migrations, then start the API. create_all in startup also covers
# a fresh DB, but we run Alembic so the migration history stays authoritative.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
