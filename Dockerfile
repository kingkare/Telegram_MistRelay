# 阶段1: 构建前端
FROM node:20-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS frontend-builder

WORKDIR /app/web

# 复制 package.json 和 package-lock.json
COPY web/package*.json ./

# 安装前端构建依赖
RUN npm ci

# 复制前端源码
COPY web/ ./

# 构建前端
RUN npm run build

# 阶段2: Python 依赖构建
FROM python:3.11-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba AS build

# 安装编译工具（TgCrypto需要编译）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy only the requirements file first to leverage Docker cache if it hasn't changed
COPY requirements.txt /app/requirements.txt

# Install dependencies in a temporary prefix that can be copied to a non-root image.
RUN pip3 --no-cache-dir install --prefix=/install -r /app/requirements.txt

FROM python:3.11-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba

# 安装必要的工具和依赖（合并所有apt-get命令以减少层数）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    aria2 \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy installed dependencies from the build stage.
COPY --from=build /install /usr/local

# 从前端构建阶段复制 dist 目录
COPY --from=frontend-builder /app/web/dist /app/web/dist

# 设置工作目录
WORKDIR /app

# Copy the rest of the application files
# 前端已通过多阶段构建集成到镜像中
COPY activation_preflight.py app.py async_aria2_client.py bootstrap_legacy.py configer.py db.py util.py monitor.py log_config.py auth.py download_cleanup.py legacy_config.py path_security.py request_security.py rotate_credentials.py security_validation.py service_runtime.py requirements.txt start.sh ./
COPY thumbnail_generator.py ./
COPY aria2_client/ ./aria2_client/
COPY WebStreamer/ ./WebStreamer/

RUN groupadd --gid 10001 mistrelay && \
    useradd --uid 10001 --gid 10001 --create-home --home-dir /home/mistrelay \
      --shell /usr/sbin/nologin mistrelay && \
    mkdir -p /app/cache/thumbnails /app/aria2 /data/downloads && \
    chown -R mistrelay:mistrelay /app/cache /app/aria2 /data /home/mistrelay

# 设置启动脚本权限
RUN chmod +x /app/start.sh

USER 10001:10001

# 使用启动脚本
CMD ["/app/start.sh"]
