# syntax=docker/dockerfile:1.7
# Images for the API and the worker, built from the uv workspace:
#
#   docker build --target api    -t tabscribe-api .
#   docker build --target worker -t tabscribe-worker .
#
# Each image holds one virtualenv with only its own packages: the API has no pipeline or ML
# libraries; the worker has the pipeline (with its Rust extension) and an LGPL ffmpeg.

ARG PYTHON_IMAGE=python:3.12-slim-trixie
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.9

FROM ${UV_IMAGE} AS uv

# ---------------------------------------------------------------------------------------------
# ffmpeg, LGPL build (TD-9). Configured without --enable-gpl and --enable-nonfree, with no
# external libraries, and only what `normalize` needs: decoding the upload types the API accepts
# (AUDIO_TYPES) to raw float samples. The source tarball is pinned by checksum.
FROM ${PYTHON_IMAGE} AS ffmpeg
ARG FFMPEG_VERSION=9.0.2
ARG FFMPEG_SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl ca-certificates nasm xz-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN curl -fsSL "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz" -o ffmpeg.tar.xz \
    && echo "${FFMPEG_SHA256}  ffmpeg.tar.xz" | sha256sum -c - \
    && tar -xJf ffmpeg.tar.xz --strip-components=1 \
    && rm ffmpeg.tar.xz
RUN ./configure \
        --prefix=/opt/ffmpeg \
        --disable-autodetect --disable-everything --disable-doc --disable-debug \
        --disable-ffplay --disable-ffprobe --disable-network \
        --disable-shared --enable-static \
        --enable-protocol=file,pipe \
        --enable-demuxer=mov,mp3,aac,wav,flac,ogg,matroska \
        --enable-parser=aac,aac_latm,mpegaudio,flac,vorbis,opus \
        --enable-decoder=aac,aac_latm,mp3,mp3float,flac,vorbis,opus,alac,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_u8 \
        --enable-encoder=pcm_f32le --enable-muxer=pcm_f32le \
        --enable-filter=aresample,aformat,anull,atrim,abuffer,abuffersink \
        --enable-swresample \
        | tee configure.log \
    # configure only warns about a component name it doesn't know; that would silently drop a
    # format, so it fails the build here.
    && ! grep -i "did not match anything" configure.log \
    && make -j"$(nproc)" \
    && make install \
    && /opt/ffmpeg/bin/ffmpeg -hide_banner -buildconf > /opt/ffmpeg/BUILDCONF \
    && ! grep -qE -- '--enable-(gpl|nonfree)' /opt/ffmpeg/BUILDCONF \
    && cp COPYING.LGPLv2.1 /opt/ffmpeg/LICENSE

# ---------------------------------------------------------------------------------------------
# Python environments. Dependencies are installed before the source is copied, so editing code
# doesn't reinstall them.
FROM ${PYTHON_IMAGE} AS python-base
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

FROM python-base AS api-build
COPY pyproject.toml uv.lock ./
COPY packages/platform/pyproject.toml packages/platform/
COPY packages/pipeline/pyproject.toml packages/pipeline/
COPY services/api/pyproject.toml services/api/
COPY services/worker/pyproject.toml services/worker/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package tabscribe-api --no-install-workspace
COPY packages/platform packages/platform
COPY services/api services/api
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package tabscribe-api --no-editable

FROM python-base AS worker-build
# The pipeline's Rust extension is built by maturin (edition 2024: Rust 1.85 or newer).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"
COPY pyproject.toml uv.lock ./
COPY packages/platform/pyproject.toml packages/platform/
COPY packages/pipeline/pyproject.toml packages/pipeline/
COPY services/api/pyproject.toml services/api/
COPY services/worker/pyproject.toml services/worker/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package tabscribe-worker --no-install-workspace
COPY packages packages
COPY services/worker services/worker
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/app/packages/pipeline/target \
    uv sync --locked --no-dev --package tabscribe-worker --no-editable

# ---------------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime
RUN useradd --create-home --uid 10001 app
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1
WORKDIR /app

FROM runtime AS api
COPY --from=api-build /app/.venv /app/.venv
USER app
EXPOSE 8000
# --proxy-headers: client addresses come from the load balancer's X-Forwarded-For.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

FROM runtime AS worker
COPY --from=ffmpeg /opt/ffmpeg/bin/ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /opt/ffmpeg/LICENSE /opt/ffmpeg/BUILDCONF /usr/share/doc/ffmpeg/
COPY --from=worker-build /app/.venv /app/.venv
# ONNX Runtime telemetry off (also set in code; this covers any other entry point).
ENV ORT_DISABLE_TELEMETRY=1
USER app
EXPOSE 9100
# On SIGTERM the worker finishes its current stage, then exits (give it time: see compose).
CMD ["python", "-m", "worker"]
