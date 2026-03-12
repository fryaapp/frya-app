FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip wheel --wheel-dir /wheels -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FRYA_HOST=0.0.0.0 \
    FRYA_PORT=8001 \
    FRYA_DATA_DIR=/app/data \
    FRYA_RULES_DIR=/app/data/rules \
    FRYA_VERFAHRENSDOKU_DIR=/app/data/verfahrensdoku

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY app ./app
# Defaults fuer First-Run-Bootstrap; persistente Wahrheit liegt im Volume /app/data.
COPY data /opt/frya-default-data

RUN addgroup --system --gid 10001 frya \
    && adduser --system --uid 10001 --ingroup frya --home /home/frya frya \
    && mkdir -p /app/data /app/data/rules /app/data/memory /app/data/verfahrensdoku /app/data/tasks /app/data/audit /app/data/system/proposals \
    && chown -R frya:frya /app /home/frya /opt/frya-default-data

EXPOSE 8001

CMD ["sh", "-ec", "\
required_paths='agent.md user.md soul.md memory.md dms-state.md rules/rule_registry.yaml'; \
for d in rules memory verfahrensdoku tasks audit system/proposals; do mkdir -p \"/app/data/$d\"; done; \
needs_bootstrap=0; \
for p in $required_paths; do if [ ! -f \"/app/data/$p\" ]; then needs_bootstrap=1; fi; done; \
if [ \"$needs_bootstrap\" -eq 1 ] && [ -d /opt/frya-default-data ]; then cp -an /opt/frya-default-data/. /app/data/ || true; fi; \
chown -R frya:frya /app/data || true; \
model=\"${FRYA_LLM_MODEL:-openai/gpt-4o-mini}\"; \
case \"$model\" in \
  openai/*) if [ -z \"${FRYA_OPENAI_API_KEY:-}\" ]; then echo 'ERROR: FRYA_OPENAI_API_KEY fehlt fuer OpenAI-Modell' >&2; exit 1; fi ;; \
  anthropic/*) if [ -z \"${FRYA_ANTHROPIC_API_KEY:-}\" ]; then echo 'ERROR: FRYA_ANTHROPIC_API_KEY fehlt fuer Anthropic-Modell' >&2; exit 1; fi ;; \
esac; \
exec gosu frya uvicorn app.main:app --host ${FRYA_HOST:-0.0.0.0} --port ${FRYA_PORT:-8001} \
"]