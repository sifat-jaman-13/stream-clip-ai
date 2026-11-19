FROM python:3.12-slim

LABEL org.opencontainers.image.title="StreamClipAI" \
      org.opencontainers.image.description="AI-powered stream auto-clipper: Twitch/YouTube → 9:16 Shorts/TikTok/Reels" \
      org.opencontainers.image.source="https://github.com/sifat-jaman-13/stream-clip-ai" \
      org.opencontainers.image.licenses="MIT"

# System dependencies: ffmpeg + streamlink runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy autoclip script
COPY autoclip.py .

RUN mkdir -p /app/out /app/rec

EXPOSE 8080

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "autoclip.py"]
CMD []
