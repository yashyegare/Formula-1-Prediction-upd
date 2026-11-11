#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y docker.io curl
systemctl enable --now docker

install -d -m 700 /var/lib/f1-postgres
if [ ! -s /var/lib/f1-postgres/postgres.env ]; then
  metadata=http://metadata.google.internal/computeMetadata/v1
  token=$(curl --fail --silent --show-error -H 'Metadata-Flavor: Google' \
    "$metadata/instance/service-accounts/default/token" | \
    python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
  project=$(curl --fail --silent --show-error -H 'Metadata-Flavor: Google' "$metadata/project/project-id")
  password=$(curl --fail --silent --show-error -H "Authorization: Bearer $token" \
    "https://secretmanager.googleapis.com/v1/projects/$project/secrets/f1-db-password/versions/latest:access" | \
    python3 -c 'import base64,json,sys; print(base64.b64decode(json.load(sys.stdin)["payload"]["data"]).decode())')
  umask 077
  printf 'POSTGRES_DB=f1\nPOSTGRES_USER=f1\nPOSTGRES_PASSWORD=%s\n' "$password" > /var/lib/f1-postgres/postgres.env
  unset password token
fi

# The database listens on its private VPC IP only, never its public IP.
private_ip=$(curl --fail --silent --show-error -H 'Metadata-Flavor: Google' \
  http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/ip)
if ! docker container inspect f1-postgres >/dev/null 2>&1; then
  docker run -d --name f1-postgres --restart unless-stopped \
    --env-file /var/lib/f1-postgres/postgres.env \
    -v /var/lib/f1-postgres/data:/var/lib/postgresql/data \
    -p "$private_ip:5432:5432" postgres:16-bookworm \
    -c max_connections=30 -c shared_buffers=128MB
else
  docker start f1-postgres
fi
