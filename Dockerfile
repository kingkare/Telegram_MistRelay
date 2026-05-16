# 阶段1: 构建前端
FROM node:20-slim AS frontend-builder

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
FROM python:3.11-slim-bookworm AS build

# 安装编译工具（TgCrypto需要编译）
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy only the requirements file first to leverage Docker cache if it hasn't changed
COPY requirements.txt /app/requirements.txt

# Install dependencies in a temporary container
RUN python -m pip install --upgrade pip && \
    pip3 --no-cache-dir install --user -r /app/requirements.txt

FROM python:3.11-slim-bookworm

# 安装必要的工具和依赖（合并所有apt-get命令以减少层数）
# 注意:使用 Docker Python SDK 代替 Docker CLI,更可靠且不需要安装二进制文件
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    gnupg2 \
    ca-certificates \
    gcc \
    g++ \
    aria2 \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy installed dependencies from the build stage
COPY --from=build /root/.local /root/.local

# 从前端构建阶段复制 dist 目录
COPY --from=frontend-builder /app/web/dist /app/web/dist

# 设置工作目录
WORKDIR /app

# Copy the rest of the application files
# 前端已通过多阶段构建集成到镜像中
COPY app.py async_aria2_client.py configer.py db.py util.py monitor.py log_config.py auth.py requirements.txt start.sh ./
COPY thumbnail_generator.py ./
COPY aria2_client/ ./aria2_client/
COPY WebStreamer/ ./WebStreamer/

# 确保PATH包含.local/bin
ENV PATH=/root/.local/bin:$PATH

# 创建缩略图缓存目录
RUN mkdir -p /app/cache/thumbnails

# 设置启动脚本权限
RUN chmod +x /app/start.sh

# 使用启动脚本
CMD ["/bin/bash", "-c", "set -e && /app/start.sh"]
