# Root-level build for managed platforms.
#
# Render clones the repo and looks for ./Dockerfile at the top level. Pointing
# it at backend/ depends on the Root Directory dashboard field being set
# correctly, which is easy to miss and fails with a confusing "failed to read
# dockerfile" that looks like the file is absent rather than misaddressed.
# Building from the root removes that dependency: this works on a default
# configuration with no dashboard changes at all.
#
# backend/Dockerfile is kept for local builds, where the context is backend/.
# The two must stay in step; the only difference is the backend/ path prefix.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so the layer caches across source edits.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

# Alpaca credentials are supplied per-session through the onboarding flow, not
# baked into the image. FEATHERLESS_API_KEY is the only value worth passing at
# runtime, and the agent degrades to its deterministic policy without it.
EXPOSE 8000

# Render and Koyeb inject PORT and scan for a listener on it; a hardcoded port
# builds cleanly and then never goes healthy. Shell form is required for
# ${PORT} to expand -- exec form passes the literal string to uvicorn.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request,sys; p=os.environ.get('PORT','8000'); sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+p+'/health', timeout=4).status == 200 else 1)"

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
