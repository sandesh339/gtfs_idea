# GTFS validator microservice for Google Cloud Run.
# Python base (clean pip) + a headless JRE + the official validator jar.
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jre-headless curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Download the official validator jar at build time (keeps the repo light).
ARG VALIDATOR_VERSION=8.0.1
RUN curl -sL -o gtfs-validator-cli.jar \
    "https://github.com/MobilityData/gtfs-validator/releases/download/v${VALIDATOR_VERSION}/gtfs-validator-${VALIDATOR_VERSION}-cli.jar"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

ENV PORT=8080
# Cloud Run provides $PORT; bind uvicorn to it.
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
