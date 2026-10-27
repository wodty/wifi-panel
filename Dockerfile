FROM python:3.12-slim

# adb：电视控制用（容器内直连电视，不依赖宿主机）
RUN apt-get update \
    && apt-get install -y --no-install-recommends adb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server ./server
COPY web ./web

# 面板配置与电视配对密钥写在这里，用卷挂出来即可持久化
ENV PANEL_PORT=8765 \
    PANEL_TOKEN=change-me-please

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=3)"

CMD ["sh", "-c", "python -m uvicorn server.main:app --host 0.0.0.0 --port ${PANEL_PORT}"]
