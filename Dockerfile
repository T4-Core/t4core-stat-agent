# Multi-stage: base -> dev | runtime. runtime is last so an untargeted build yields the prod image.

FROM python:3.11-slim-trixie AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# config.ROOT resolves to /app (parents[2]), so storage mounts at /app/storage with no code change
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# USER switch is deferred to child stages: dev still needs root to install
RUN useradd --create-home --uid 1000 app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"


FROM base AS dev

COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt

# browsers are several hundred MB; opt in via build arg. Shared path so the non-root user can use them.
ARG INSTALL_PLAYWRIGHT=false
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN if [ "$INSTALL_PLAYWRIGHT" = "true" ]; then playwright install --with-deps chromium; fi

# code is bind-mounted by docker-compose.dev.yml, not copied
USER app
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "backend"]


FROM base AS runtime

COPY --chown=app:app backend/ backend/
USER app
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]