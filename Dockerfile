# syntax=docker/dockerfile:1.6
FROM --platform=$BUILDPLATFORM node:24-bookworm-slim AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM rust:1.94-bookworm AS server-build
RUN apt-get update && apt-get install -y --no-install-recommends libfreetype6-dev pkg-config && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY server/ server/
COPY app/data/ app/data/
RUN cargo build --manifest-path server/Cargo.toml --locked --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libfreetype6 fonts-dejavu-core poppler-utils && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=server-build /build/server/target/release/label-studio-server /usr/local/bin/label-studio-server
COPY --from=frontend-build /build/app/static/studio /app/app/static/studio
ENV SERVER_HOST=0.0.0.0 SERVER_PORT=8013 STUDIO_DATA_DIR=/data PRINTER_PRINTER=simulation
EXPOSE 8013
VOLUME ["/data"]
ENTRYPOINT ["label-studio-server"]
