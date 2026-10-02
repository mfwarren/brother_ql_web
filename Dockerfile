# syntax=docker/dockerfile:1.6
FROM --platform=$BUILDPLATFORM node:24-alpine AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM --platform=$TARGETPLATFORM python:3-alpine

ARG TARGETARCH
WORKDIR /app

# First, copy only the requirements.txt
# This ensures the dependencies can be sourced from docker's cache (and save a
# lot of time during building) *unless* the requirements.txt file actually
# changes
COPY ./requirements.txt ./requirements-server.txt /app/

RUN if [ $TARGETARCH == "arm" ]; then \
    apk update --no-cache && \
    apk add --no-cache \
    # Build dependencies for Pillow
    gcc \
    musl-dev \
    zlib-dev \
    jpeg-dev \
    tiff-dev \
    freetype-dev \
    lcms2-dev \
    libwebp-dev \
    tcl-dev \
    tk-dev \
    harfbuzz-dev \
    fribidi-dev \
    libimagequant-dev \
    libxcb-dev \
    openjpeg-dev \
    bash \
    ; fi

RUN apk update --no-cache && \
    apk add --no-cache \
    git \
    ttf-dejavu \
    ttf-liberation \
    ttf-droid \
    ttf-freefont \
    font-terminus \
    font-inconsolata \
    font-dejavu \
    font-noto \
    poppler-utils \
    bash && \
    pip3 install -r requirements-server.txt

RUN if [ $TARGETARCH == "arm" ]; then \
        # Clean up build dependencies to reduce image size
        apk del gcc musl-dev \
    ; fi

COPY . /app
COPY --from=frontend-build /build/app/static/studio /app/app/static/studio

EXPOSE 8013
ENTRYPOINT ["python3", "serve.py"]
