# frontend

Next.js (App Router) UI for submitting text + face, polling status, and
previewing/downloading the lip-synced result.

Talks only to the orchestrator via `/api/v1/*` (same-origin). `next.config.js`
rewrites that prefix to `${ORCHESTRATOR_URL}` for dev.

## Dev

```bash
cd frontend
npm install
ORCHESTRATOR_URL=http://localhost:8000 npm run dev
# → http://localhost:3000
```

## Prod build

```bash
npm run build
npm start
```

For production the orchestrator can serve the `out/` static build behind its
own `/` route (see Phase 5 / docker-compose).

## Env

| Var                 | Default                  | Purpose                   |
|---------------------|--------------------------|---------------------------|
| `ORCHESTRATOR_URL`  | `http://localhost:8000`  | Target for /api/v1 rewrites |
