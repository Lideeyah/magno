FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so the layer caches across source edits.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Alpaca credentials are supplied per-session through the onboarding flow, not
# baked into the image. FEATHERLESS_API_KEY is the only value worth passing at
# runtime, and the agent degrades to its deterministic policy without it.
EXPOSE 8000

# Managed platforms inject the listen port rather than letting the image pick
# it: Render and Koyeb both set PORT, and a hardcoded 8000 fails their port
# scan, so the service never becomes healthy. Shell form is required here --
# exec form does not expand ${PORT}, it passes the literal string to uvicorn.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request,sys; p=os.environ.get('PORT','8000'); sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+p+'/health', timeout=4).status == 200 else 1)"

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
