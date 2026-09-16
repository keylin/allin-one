# 基础镜像仓库前缀（含结尾斜杠）。国内默认走 docker.1ms.run；某个镜像源拉不动时
# 由部署脚本探测可用源后通过 --build-arg REGISTRY=... 覆盖，留空则直连 Docker Hub
ARG REGISTRY=docker.1ms.run/

# ============================================
# Stage 1: Build Frontend
# ============================================
FROM ${REGISTRY}node:22-alpine AS frontend-builder

# 配置阿里云 Alpine 镜像源
RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories

WORKDIR /app/frontend

# 配置淘宝 npm 镜像源
RUN npm config set registry https://registry.npmmirror.com

# Copy package files
COPY frontend/package*.json ./

# Install dependencies
RUN --mount=type=cache,target=/root/.npm npm ci

# Copy frontend source
COPY frontend/ ./

# Build frontend
RUN npm run build

# ============================================
# Stage 2: Docker CLI (for RSSHub container management)
# ============================================
FROM ${REGISTRY}docker:cli AS docker-cli

# ============================================
# Stage 3: Backend Runtime
# ============================================
FROM ${REGISTRY}python:3.11-slim

# 配置阿里云 Debian 镜像源
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
    sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources

WORKDIR /app

# Install system dependencies (FFmpeg for video processing)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI (for RSSHub container management via docker.sock)
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins /usr/local/libexec/docker/cli-plugins

# 配置阿里云 PyPI 镜像源
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set install.trusted-host mirrors.aliyun.com

# Copy backend requirements
COPY backend/requirements.txt ./

# Install Python dependencies
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

# Copy backend code
COPY backend/ ./

# Copy frontend build from stage 1
COPY --from=frontend-builder /app/frontend/dist ./static

# Create data directories
RUN mkdir -p data/db data/media data/reports data/logs

# Expose port
EXPOSE 8000

# Default command (can be overridden in docker-compose)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
