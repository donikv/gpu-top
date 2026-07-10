# Multi-stage build with two final targets:
#   docker build --target server -t gpu-top-server .
#   docker build --target agent  -t gpu-top-agent  .

# --- build the React bundle --------------------------------------------------
FROM node:22-alpine AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- build the Python wheel (with the web bundle inside) ---------------------
FROM python:3.12-slim AS py-build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src/ src/
COPY --from=web-build /web/dist/ src/gpu_top/server/static/
RUN pip install --no-cache-dir build && python -m build --wheel -o /wheels

# --- server ------------------------------------------------------------------
FROM python:3.12-slim AS server
COPY --from=py-build /wheels/*.whl /tmp/
RUN pip install --no-cache-dir "$(ls /tmp/*.whl)[server]" && rm /tmp/*.whl
VOLUME /var/lib/gpu-top
EXPOSE 8000
ENTRYPOINT ["gpu-top-server"]
CMD ["-c", "/etc/gpu-top/server.toml"]

# --- agent -------------------------------------------------------------------
# Needs host GPU access at runtime:
#   docker run --gpus all --pid=host ... gpu-top-agent
# nvidia-smi is injected by the NVIDIA container toolkit; the docker CLI is
# installed for optional container attribution (mount /var/run/docker.sock).
FROM python:3.12-slim AS agent
RUN apt-get update && apt-get install -y --no-install-recommends docker-cli \
    && rm -rf /var/lib/apt/lists/* || true
COPY --from=py-build /wheels/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl
ENTRYPOINT ["gpu-top-agent"]
CMD ["-c", "/etc/gpu-top/agent.toml"]
