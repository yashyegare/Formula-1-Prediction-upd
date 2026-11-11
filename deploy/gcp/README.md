# GCP backend

Project: `mcp-memory-bridge` (530426302059). Region: `us-central1`.

- API: https://f1-api-530426302059.us-central1.run.app
- Cloud Run service: `f1-api`, 1 CPU / 1 GiB, min 0 / max 1 instances.
- Database VM: `f1-postgres`, `us-central1-a`, e2-micro, 30 GB standard boot disk.
- PostgreSQL 16: private IP `10.42.0.10:5432`, database/user `f1`.
- Dedicated VPC/subnet: `f1-vpc` / `f1-subnet` (`10.42.0.0/24`).
- Artifact Registry: `us-central1-docker.pkg.dev/mcp-memory-bridge/f1-backend`.
- Backups: `gs://mcp-memory-bridge-f1-backups/postgres/`, daily at 03:30 UTC.

## Data and credentials

The user approved a fresh database. Only the six public season tables were
seeded from the committed SQLite file: 46 seasons. Old Render users and
predictions were not recovered. The developer's modified local SQLite file was
excluded from the initial build.

Database, session, and sync credentials are in Secret Manager. No credential
values belong in Git or Vercel. Runtime service account `f1-api` can access
only its three runtime secrets. VM account `f1-db-vm` can access the DB password
and create backup objects. PostgreSQL has no public listener; the firewall
permits it only from Cloud Run instances tagged `f1-api`. SSH uses IAP.

The VM's external IPv4 address is for outbound package/image downloads; it
does not expose PostgreSQL. Its IAP SSH firewall rule accepts Google's IAP
range only. Existing project resources, including `memory-server`, are separate.

## Deployment

GitHub CI tests all apps, then uses short-lived Workload Identity Federation
credentials restricted to this repository's main branch. It runs:

```bash
bash deploy/gcp/deploy.sh COMMIT_SHA
```

Cloud Build tests the backend image before pushing the production image.
The API uses Python 3.11, one Gunicorn process and four threads. Single-instance
scaling limits in-memory rate limiting to one process; it is not a hard spending
cap or an availability guarantee. Background live refresh is off because
Cloud Run's request-based CPU is not a reliable always-running scheduler.

`deploy/gcp/.gcloudignore` restricts uploaded files and excludes credentials.
The Dockerfile copies the entire model/data subtree needed by race-intelligence
endpoints. Do not deploy only `flask-app/`: that omits those runtime artifacts.

The first seed was a one-task, zero-retry Cloud Run job `f1-seed` running
`seed_empty_postgres.py`. It refuses nonempty season tables and must not be
used to overwrite a restored or live database. Future deployments never seed.

The nightly GitHub refresh builds derived data and uses a separate
`f1-refresh` identity to read the sync token. Its GITHUB_TOKEN push explicitly
dispatches CI because bot pushes do not trigger push workflows automatically.
Health checks run every six hours rather than keeping Cloud Run awake.

## Frontends

Both Vercel production projects point to this API:
- `nextjs-app`: `NEXT_PUBLIC_API_URL`.
- `formula-1-prediction-upd-5b99`: `PUBLIC_API_BASE_URL`.

The simulator's original domain `formula-1-prediction-upd-fxzg.vercel.app`
is attached to the recreated Astro project. Production domains are public;
preview deployments remain protected by Vercel authentication.

Password recovery returns HTTP 503 until verified email delivery is implemented;
it no longer returns a bearer reset token to an unauthenticated caller.
Signup, login, and existing valid reset-token redemption remain available.

## Operations

Inspect Cloud Run logs in the GCP console or run:

```bash
gcloud run services describe f1-api --region=us-central1 --project=mcp-memory-bridge
gcloud run services logs read f1-api --region=us-central1 --project=mcp-memory-bridge --limit=50
gcloud compute ssh f1-postgres --zone=us-central1-a --project=mcp-memory-bridge --tunnel-through-iap
```

On the VM, run `sudo docker logs f1-postgres` to inspect the DB, and
`sudo /usr/local/sbin/f1-backup` to create an immediate custom-format pg_dump
backup. The cron job is `/etc/cron.d/f1-backup`. Verify backup objects regularly
and test a restore into a separate empty database before relying on recovery.
The VM's boot disk contains the database: do not delete the VM/disk or the
PostgreSQL data directory. Backups are separate objects and contain user data.

## Trial expiry and costs

The user reported 21 days of trial credit remaining on November 11, 2026.
Verify the actual expiry and balance in Billing; the CLI billing-enabled flag
does not prove remaining trial credit. No billing-account upgrade was requested.

An existing e2-micro VM already uses the billing account's monthly free VM
allowance. The additional DB VM, external IPv4, disk, builds, image storage,
networking and any Cloud Run usage above allowances may consume trial credit
or incur charges if the account is paid. Max instances is not a budget cap.
Review or migrate before trial expiry. No resources are automatically deleted
or stopped, because doing so would interrupt service and may endanger data.

The repository's Python dependencies are still unpinned. Capture and validate
the model's training/serving versions before a future dependency update; retain
the previous image digest for rollback. Rollback does not roll back the DB.
