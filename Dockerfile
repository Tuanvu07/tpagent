# TPAgent — image chạy trên cloud (Railway / Render / Fly.io / VPS).
# Base: Playwright chính hãng, đã có Chromium + toàn bộ thư viện hệ thống.
# Phiên bản gói pip `playwright` PHẢI khớp tag ảnh (1.63.0).
ARG PLAYWRIGHT_VERSION=1.63.0
FROM mcr.microsoft.com/playwright/python:v${PLAYWRIGHT_VERSION}-noble
ARG PLAYWRIGHT_VERSION

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg (tool video), fonts có tiếng Việt (drawtext / phụ đề), ripgrep, git
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-dejavu fonts-dejavu-core fonts-noto-core fonts-noto-cjk fonts-liberation \
        ripgrep git curl ca-certificates tini \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

# Người dùng không phải root. /data là volume (workspace + sessions + config).
RUN useradd --create-home --uid 10001 --shell /bin/bash tpagent \
    && mkdir -p /app /data/workspace /data/sessions /data/.tpagent \
    && chown -R tpagent:tpagent /app /data

WORKDIR /app

# Cài dependency trước để tận dụng cache layer
COPY --chown=tpagent:tpagent pyproject.toml README.md ./
RUN mkdir -p tpagent && touch tpagent/__init__.py \
    && pip install --upgrade pip \
    && pip install "playwright==${PLAYWRIGHT_VERSION}" \
    && pip install -e ".[browser,video]" \
    # Extras "web" có thể chưa có trong pyproject -> cài tường minh, không lỗi build.
    && (pip install -e ".[web]" 2>/dev/null || true) \
    && pip install "fastapi>=0.115" "uvicorn[standard]>=0.30" "python-multipart>=0.0.9" "websockets>=12" \
    && rm -rf tpagent

# Mã nguồn thật
COPY --chown=tpagent:tpagent . .
RUN pip install -e ".[browser,video]" --no-deps \
    && cp deploy/config.cloud.yaml /app/config.yaml \
    && chmod +x deploy/entrypoint.sh

# Chromium của ảnh Playwright nằm ở /ms-playwright (đọc được bởi mọi user)
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/data \
    TPAGENT_HOME=/data \
    TPAGENT_WORKSPACE=/data/workspace \
    TPAGENT_BROWSER_HEADLESS=1 \
    TPAGENT_ENABLED_TOOLS=browser,video,subagent \
    PORT=8080

USER tpagent
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null || curl -fsS "http://127.0.0.1:${PORT}/" >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/app/deploy/entrypoint.sh"]
CMD ["python", "-m", "tpagent.server"]
