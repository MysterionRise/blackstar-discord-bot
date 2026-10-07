# Linux hosts only, and experimental. Docker Desktop on macOS and Windows runs
# containers inside a Linux VM with no access to host USB audio, so the amp is
# invisible from in here. On a Mac, install natively instead.
FROM python:3.12-slim

# libportaudio2: sounddevice backend. libopus0: Discord voice encoding.
# ffmpeg: fallback backend.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ffmpeg \
        libopus0 \
        libportaudio2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Unprivileged, but in the audio group so /dev/snd is reachable.
RUN useradd --create-home --groups audio guitaramp
USER guitaramp

CMD ["guitar-amp-bot"]
