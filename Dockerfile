# Stage 1: build the UI
FROM node:22-alpine AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/ ./
RUN npm run build

# Stage 2: the app
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY --from=ui /src/envoy/static ./src/envoy/static
RUN pip install --no-cache-dir .
ENV ENVOY_HOST=0.0.0.0 \
    ENVOY_PORT=8765 \
    ENVOY_DATA_DIR=/data \
    ENVOY_ENDPOINT=http://host.docker.internal:11434/v1
VOLUME ["/data"]
EXPOSE 8765
CMD ["envoy", "serve", "--no-browser"]
