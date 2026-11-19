# ── Stage 1: build wheel ──────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml .
COPY src/ src/
RUN pip install --upgrade pip build \
 && python -m build --wheel --outdir /dist


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim

LABEL org.opencontainers.image.title="StreamClipAI" \
      org.opencontainers.image.description="AI-powered stream auto-clipper: Twitch/YouTube → 9:16 Shorts/TikTok/Reels" \
      org.opencontainers.image.source="https://github.com/sifat-jaman-13/stream-clip-ai" \
      org.opencontainers.image.licenses="MIT"

# System deps: ffmpeg + streamlink runtime libs
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install wheel + optional live/cpu deps (no CUDA in this image)
COPY --from=builder /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl streamlink \
    && rm /tmp/*.whl

# Output directories (mount these as volumes)
RUN mkdir -p /data/out /data/rec
WORKDIR /data

EXPOSE 8080

ENV PYTHONUNBUFFERED=1

# Default: open web UI on 0.0.0.0 so the host can reach it
# Override CMD for headless: docker run ... autoclip live <url>
#                                          autoclip file /data/rec/video.mp4
ENTRYPOINT ["autoclip"]
CMD []
