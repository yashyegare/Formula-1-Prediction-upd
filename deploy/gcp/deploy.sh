#!/bin/bash
set -euo pipefail
export CLOUDSDK_METRICS_ENVIRONMENT="${CLOUDSDK_METRICS_ENVIRONMENT:+$CLOUDSDK_METRICS_ENVIRONMENT }datacloud.codex"
project=mcp-memory-bridge
region=us-central1
tag=${1:?Pass a unique image tag, normally the Git commit SHA}
image="$region-docker.pkg.dev/$project/f1-backend/api:$tag"

gcloud builds submit . --project="$project" --region="$region" \
  --config=deploy/gcp/cloudbuild.yaml --ignore-file=deploy/gcp/.gcloudignore \
  --substitutions="_IMAGE=$image" \
  --service-account="projects/$project/serviceAccounts/f1-build@$project.iam.gserviceaccount.com" \
  --suppress-logs --quiet

gcloud run deploy f1-api --project="$project" --region="$region" --image="$image" \
  --service-account="f1-api@$project.iam.gserviceaccount.com" \
  --network=f1-vpc --subnet=f1-subnet --network-tags=f1-api \
  --vpc-egress=private-ranges-only \
  --set-secrets='DATABASE_URL=f1-database-url:1,SECRET_KEY=f1-session-key:1,SYNC_ADMIN_TOKEN=f1-sync-token:1' \
  --set-env-vars='^|^CORS_ORIGINS=https://nextjs-app-yashyegare.vercel.app,https://formula-1-prediction-upd-fxzg.vercel.app,https://formula-1-prediction-upd-5b99-yashyegares-projects.vercel.app' \
  --min-instances=0 --max-instances=1 --concurrency=8 --cpu=1 --memory=1Gi \
  --timeout=120 --execution-environment=gen2 --allow-unauthenticated --quiet

url=$(gcloud run services describe f1-api --project="$project" --region="$region" --format='value(status.url)')
for path in /health '/api/init?year=2026' /roster /api/race-intel/next-round; do
  curl --fail --show-error --silent --retry 3 --retry-all-errors --max-time 120 "$url$path" >/dev/null
done
echo "Verified deployment: $url"
