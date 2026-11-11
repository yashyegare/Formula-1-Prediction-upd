#!/bin/bash
set -euo pipefail
metadata=http://metadata.google.internal/computeMetadata/v1
project=$(curl --fail --silent --show-error -H 'Metadata-Flavor: Google' "$metadata/project/project-id")
token=$(curl --fail --silent --show-error -H 'Metadata-Flavor: Google' \
  "$metadata/instance/service-accounts/default/token" | \
  python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
name="postgres/f1-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker exec f1-postgres pg_dump -U f1 -d f1 -Fc | \
  curl --fail --silent --show-error -X POST -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/octet-stream' --data-binary @- \
    "https://storage.googleapis.com/upload/storage/v1/b/$project-f1-backups/o?uploadType=media&name=$name" >/dev/null
echo "Backup uploaded: $name"
