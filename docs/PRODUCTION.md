# ForgeFlow Production Readiness

ForgeFlow can run as a local hackathon demo or as a guarded production automation runtime. Production mode is enabled with:

```bash
FORGEFLOW_ENV=production
```

In production mode, ForgeFlow fails closed:

- Cached demo endpoints are blocked unless `FORGEFLOW_ENABLE_DEMO_ENDPOINTS=1`.
- Live workflow execution still requires explicit approval.
- Dangerous unauthenticated execution must stay disabled.
- The readiness API reports blockers before you claim a launch is production-ready.

## Readiness Check

Start the backend, then run:

```bash
python scripts/production_smoke.py
```

The script checks:

- `/api/health`
- `/api/status`
- `/api/product/overview`
- `/api/production/readiness`

The readiness endpoint is the source of truth:

```bash
curl http://127.0.0.1:8000/api/production/readiness
```

## Required Production Settings

Use `.env.production.example` as the deployment template.

Minimum launch settings:

- `FORGEFLOW_ENV=production`
- `FORGEFLOW_ADMIN_TOKEN` set to a high-entropy secret
- `FORGEFLOW_ALLOW_UNAUTH_DANGEROUS=0`
- `FORGEFLOW_VAULT_KEY` set before storing connector secrets
- `FORGEFLOW_ENABLE_DEMO_ENDPOINTS=0`
- `FORGEFLOW_QUEUE_WORKER=1` for scheduled or webhook jobs
- `FORGEFLOW_RUNTIME_BASE_URL` for hosted webhook activation

Connector credentials can come from environment variables or the built-in credential vault. Missing credentials are reported as blockers or warnings before live execution.

## Deployment

For a hardened local production rehearsal:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up --build
```

Mount persistent volumes for:

- `forgeflow_platform.db`
- generated `workflows/`
- `chroma_db/`

For cloud production, use the same readiness contract. A deployment should not be promoted until `/api/production/readiness` returns no blockers and no warnings for your chosen target.

