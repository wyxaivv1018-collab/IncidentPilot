# Hugging Face Spaces (Docker SDK) — IncidentPilot Nebius judge demo
# Secret: set NEBIUS_API_KEY in Space Settings → Secrets (never COPY a key file).
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    INCIDENTPILOT_PUBLIC_HOST=1 \
    PORT=7860

WORKDIR /app

# Build context must be the IncidentPilot repository root.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY scripts ./scripts
COPY ui ./ui
COPY docs/nebius/runtime-requirements.txt ./docs/nebius/runtime-requirements.txt
COPY deploy/hf-space/requirements.txt ./deploy/hf-space/requirements.txt
COPY deploy/hf-space/entrypoint.sh ./deploy/hf-space/entrypoint.sh

RUN pip install --upgrade pip \
    && pip install -e . \
    && pip install -r deploy/hf-space/requirements.txt \
    && chmod +x deploy/hf-space/entrypoint.sh

# Spaces expect the app to listen on 7860 (or $PORT).
EXPOSE 7860

CMD ["./deploy/hf-space/entrypoint.sh"]
