ARG NODE_BASE_IMAGE=node:22-alpine
ARG PYTHON_BASE_IMAGE=python:3.12-slim
ARG LEDGERLY_VERSION=0.1.0

FROM ${NODE_BASE_IMAGE} AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_BASE_IMAGE} AS runtime
ARG LEDGERLY_VERSION
LABEL org.opencontainers.image.source="https://github.com/goldenfishs/Ledgerly"
LABEL org.opencontainers.image.title="Ledgerly"
USER root
ENTRYPOINT []
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STUDIO_DATA_DIR=/app/data \
    STUDIO_WEB_DIR=/app/web \
    LEDGERLY_VERSION=${LEDGERLY_VERSION}
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt \
    && groupadd --gid 10001 ledgerly \
    && useradd --uid 10001 --gid ledgerly --create-home ledgerly \
    && mkdir -p /app/data /app/web \
    && chown ledgerly:ledgerly /app/data
COPY backend/ ./backend/
COPY --from=frontend-build /build/frontend/dist/ ./web/
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import json,urllib.request; result=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)); assert result['data']['status']=='ok'"
STOPSIGNAL SIGTERM
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
