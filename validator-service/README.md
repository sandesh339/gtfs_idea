# GTFS Validator microservice (Google Cloud Run)

A tiny container that runs the official MobilityData GTFS validator and returns
its `report.json`. The main backend's `RemoteOfficialValidator` calls it when
`VALIDATOR_URL` is set.

Contract:
- `POST /validate` — multipart field **`file`** = a GTFS `.zip`, header
  **`X-Validator-Token`** = your secret. Returns the validator's `report.json`.
- `GET /health` — liveness.

## One-time Google Cloud setup
1. Create a GCP project; note the **Project ID**.
2. Enable **billing** (card required; free within limits).
3. Enable APIs: **Cloud Run**, **Cloud Build**, **Artifact Registry**:
   ```
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
   ```
4. Get a shell with `gcloud` (local CLI or the browser **Cloud Shell**), then:
   ```
   gcloud config set project <PROJECT_ID>
   ```

## Deploy (build + host in one command)
From inside this `validator-service/` folder:
```
gcloud run deploy gtfs-validator \
  --source . \
  --region us-east1 \
  --memory 2Gi --cpu 2 --timeout 120 --concurrency 4 \
  --allow-unauthenticated \
  --set-env-vars VALIDATOR_TOKEN=<a-long-secret>
```
It prints a service URL like `https://gtfs-validator-xxxx-uc.a.run.app`.

Test it:
```
curl -F "file=@your-feed.zip" -H "X-Validator-Token: <a-long-secret>" \
  https://gtfs-validator-xxxx-uc.a.run.app/validate | head
```

## Wire it to the backend (no code change)
On the Render backend set:
```
VALIDATOR_URL=https://gtfs-validator-xxxx-uc.a.run.app
VALIDATOR_TOKEN=<the-same-secret>
```
`make_validator()` then selects `RemoteOfficialValidator`; `/health` shows it.

## Notes
- Bump the validator version via `--build-arg VALIDATOR_VERSION=8.x.y` (or edit the Dockerfile ARG).
- `--concurrency 4` keeps one instance from running too many heavy validations at once.
- `--memory 2Gi` gives the JVM room for large feeds (`-XX:MaxRAMPercentage=75.0`).
- Scales to zero when idle (free); a cold start adds a few seconds to the first call.
