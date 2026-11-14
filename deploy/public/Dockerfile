# Public Analog Twin: live engine search, AI crew replay-only (REPLAY_ONLY=1, never calls an LLM).
# Build context: a copy of the repo (git ls-files) plus web/dist built with VITE_AI_DEMO=1. Data is mounted at /app/data.
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*
COPY deploy/public/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY . /app
ENV ANALOG_ROOT=/app ANALOG_MAIN_ROOT=/app ANALOG_TWIN_DATA=/app/data SESSIONS_DIR=/app/sessions \
    REPLAY_ONLY=1 PYTHONUNBUFFERED=1
RUN useradd -u 1000 -M app && chown -R app /app/sessions
USER app
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
