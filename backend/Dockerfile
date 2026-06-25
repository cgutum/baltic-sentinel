FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY start.sh .
RUN chmod +x start.sh

EXPOSE 8000

# One container runs uvicorn + ingest + state_builder, workers auto-restart (start.sh).
CMD ["bash", "start.sh"]
