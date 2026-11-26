FROM node:22-bookworm-slim AS dashboard-build

WORKDIR /workspace/dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

FROM python:3.12-slim

LABEL org.opencontainers.image.title="StreamSnip AI" \
      org.opencontainers.image.description="Local-first stream capture, AI-assisted highlight editing, captions, and Zernio publishing" \
      org.opencontainers.image.source="https://github.com/sifat-jaman-13/stream-clip-ai" \
      org.opencontainers.image.licenses="LicenseRef-Proprietary-NonCommercial"

ENV PYTHONUNBUFFERED=1 \
    STREAMSNIP_DATA_DIR=/data \
    STREAMSNIP_BIND_HOST=0.0.0.0 \
    STREAMSNIP_PORT=8080

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY autoclip.py api_server.py ai_highlights.py post_metadata.py zernio_poster.py zernio_connections.py facecam_detect.py ./
COPY models/ ./models/
COPY assets/ ./assets/
COPY --from=dashboard-build /workspace/dashboard/dist/ ./dashboard/dist/

RUN mkdir -p /data/out /data/rec /data/creators

EXPOSE 8080

ENTRYPOINT ["python", "autoclip.py"]
CMD []
