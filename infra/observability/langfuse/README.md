# Local Langfuse

This pinned Langfuse v3 stack is for local Agent debugging only. All published
ports bind to `127.0.0.1`; named volumes survive a normal stop.

```bash
cd infra/observability/langfuse
cp .env.example .env
```

Replace every `replace-...`/`change-me...` value in `.env`. Generate the
encryption key with `openssl rand -hex 32`. Generate OTLP Basic Auth after the
project public and secret keys are final:

```bash
printf '%s' "${LANGFUSE_INIT_PROJECT_PUBLIC_KEY}:${LANGFUSE_INIT_PROJECT_SECRET_KEY}" | base64
```

Store that output as `LANGFUSE_OTLP_AUTH` in `.env`, then start and verify:

```bash
docker compose config
docker compose up -d
curl --fail http://127.0.0.1:3000/api/public/health
```

The UI is at <http://127.0.0.1:3000>. Stop without deleting data:

```bash
docker compose down
```

The following command permanently deletes the local Langfuse data volumes:

```bash
docker compose down -v
```

The Agent exporter uses OTLP/HTTP at
`http://127.0.0.1:3000/api/public/otel/v1/traces`. Langfuse is optional and the
Agent must remain functional while this stack is stopped.
