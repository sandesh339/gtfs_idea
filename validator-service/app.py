"""Tiny HTTP wrapper around the MobilityData GTFS validator jar, for Cloud Run.

POST /validate  (multipart field "file" = a GTFS .zip, header X-Validator-Token)
  -> runs the official validator and returns its report.json (the notices array),
     which is exactly what the app's RemoteOfficialValidator expects.

Listens on $PORT (Cloud Run sets it). Access is gated by VALIDATOR_TOKEN.
"""
import json
import os
import subprocess
import tempfile

from fastapi import FastAPI, UploadFile, File, Header, HTTPException

app = FastAPI(title="GTFS Validator Service")

JAR = os.getenv("VALIDATOR_JAR", "/app/gtfs-validator-cli.jar")
TOKEN = os.getenv("VALIDATOR_TOKEN", "")
TIMEOUT = int(os.getenv("VALIDATE_TIMEOUT", "110"))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/validate")
async def validate(file: UploadFile = File(...), x_validator_token: str = Header(default="")):
    if TOKEN and x_validator_token != TOKEN:
        raise HTTPException(status_code=403, detail="invalid or missing validator token")

    data = await file.read()
    with tempfile.TemporaryDirectory() as d:
        feed_path = os.path.join(d, "feed.zip")
        out_dir = os.path.join(d, "out")
        with open(feed_path, "wb") as fh:
            fh.write(data)

        cmd = ["java", "-XX:MaxRAMPercentage=75.0", "-jar", JAR,
               "-i", feed_path, "-o", out_dir, "-svu"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail=f"validation timed out after {TIMEOUT}s")

        report_path = os.path.join(out_dir, "report.json")
        if not os.path.exists(report_path):
            raise HTTPException(status_code=500,
                                detail=f"validator produced no report ({proc.stderr[:300]})")
        with open(report_path, encoding="utf-8") as fh:
            return json.load(fh)
