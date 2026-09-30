FROM python:3.11-slim

LABEL maintainer="MistRelay Team"
LABEL description="MistRelay Edge Streaming Worker"

WORKDIR /opt/mistrelay-edge

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    aiohttp \
    pyrogram \
    tgcrypto \
    psutil

COPY worker_server.py /opt/mistrelay-edge/worker_server.py
RUN chmod +x /opt/mistrelay-edge/worker_server.py

ENV PORT=8090
ENV NODE_SECRET=""
ENV MASTER_URL=""

EXPOSE 8090

ENTRYPOINT ["python3", "/opt/mistrelay-edge/worker_server.py"]
