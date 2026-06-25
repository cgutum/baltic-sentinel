# Full deploy image: API + ingest + state_builder workers + the static console at /.
# Build from the REPO ROOT so BOTH backend/ and frontend/ are in the build context.
# (Railway: set Root Directory to blank. Fly: run from repo root.)
FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/start.sh .
COPY frontend ./frontend
RUN chmod +x start.sh

EXPOSE 8000

# One container runs uvicorn + ingest + state_builder, workers auto-restart (start.sh).
CMD ["bash", "start.sh"]
