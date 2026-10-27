#!/usr/bin/env bash
# Entrypoint cho container TPAgent: chuẩn bị volume /data, in token + URL, rồi chạy server.
set -euo pipefail

PORT="${PORT:-8080}"
TPAGENT_HOME="${TPAGENT_HOME:-/data}"
TPAGENT_WORKSPACE="${TPAGENT_WORKSPACE:-$TPAGENT_HOME/workspace}"
export PORT TPAGENT_HOME TPAGENT_WORKSPACE

# --- Thư mục trên volume ---
mkdir -p "$TPAGENT_WORKSPACE" "$TPAGENT_HOME/sessions" "$TPAGENT_HOME/.tpagent" 2>/dev/null || true

# config.yaml: core đọc ./config.yaml hoặc ~/.tpagent/config.yaml (HOME=/data).
# Lần đầu chạy: copy bản cloud vào volume để anh có thể sửa (vd đổi tier model) mà không rebuild.
if [ ! -f "$TPAGENT_HOME/.tpagent/config.yaml" ] && [ -f /app/deploy/config.cloud.yaml ]; then
  cp /app/deploy/config.cloud.yaml "$TPAGENT_HOME/.tpagent/config.yaml" 2>/dev/null || true
fi

# --- Token đăng nhập ---
if [ -z "${TPAGENT_TOKEN:-}" ]; then
  if [ -f "$TPAGENT_HOME/.tpagent/token" ]; then
    TPAGENT_TOKEN="$(cat "$TPAGENT_HOME/.tpagent/token")"
  else
    TPAGENT_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
    (umask 077 && printf '%s' "$TPAGENT_TOKEN" > "$TPAGENT_HOME/.tpagent/token") 2>/dev/null || true
    echo "[tpagent] TPAGENT_TOKEN chưa được đặt -> đã tự tạo và lưu vào $TPAGENT_HOME/.tpagent/token"
  fi
  export TPAGENT_TOKEN
fi

# --- URL công khai (nếu nền tảng cung cấp) ---
PUBLIC_URL=""
[ -n "${RAILWAY_PUBLIC_DOMAIN:-}" ] && PUBLIC_URL="https://${RAILWAY_PUBLIC_DOMAIN}"
[ -n "${RENDER_EXTERNAL_URL:-}" ]    && PUBLIC_URL="${RENDER_EXTERNAL_URL}"
[ -n "${FLY_APP_NAME:-}" ]           && PUBLIC_URL="https://${FLY_APP_NAME}.fly.dev"
[ -n "${TPAGENT_PUBLIC_URL:-}" ]     && PUBLIC_URL="${TPAGENT_PUBLIC_URL}"

echo "=================================================================="
echo "  TPAgent server"
echo "  Cổng          : $PORT"
echo "  Workspace     : $TPAGENT_WORKSPACE"
echo "  Sessions      : $TPAGENT_HOME/sessions  (hoặc ~/.tpagent/sessions)"
echo "  Tools         : ${TPAGENT_ENABLED_TOOLS:-browser,video,subagent}"
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo "  ANTHROPIC_API_KEY: đã đặt (sk-ant-...${ANTHROPIC_API_KEY: -4})"
elif [ "${TPAGENT_PROVIDER:-}" = "fake" ]; then
  echo "  Provider      : fake (chạy thử, không gọi model thật)"
else
  echo "  !! CHƯA có ANTHROPIC_API_KEY — agent sẽ không trả lời được. Đặt biến môi trường rồi redeploy."
fi
echo "  Token đăng nhập (TPAGENT_TOKEN): $TPAGENT_TOKEN"
if [ -n "$PUBLIC_URL" ]; then
  echo "  Mở trình duyệt: $PUBLIC_URL"
  echo "  (dán token ở trên vào ô đăng nhập; hoặc mở $PUBLIC_URL/?token=$TPAGENT_TOKEN)"
else
  echo "  Mở trình duyệt: http://<địa-chỉ-máy-chủ>:$PORT  rồi dán token ở trên"
fi
echo "=================================================================="

# Chromium: báo trước nếu RAM máy quá thấp (tool browser cần ~ 400–600 MB)
if [ -r /sys/fs/cgroup/memory.max ]; then
  LIM="$(cat /sys/fs/cgroup/memory.max 2>/dev/null || echo max)"
  if [ "$LIM" != "max" ] && [ "$LIM" -lt 900000000 ] 2>/dev/null; then
    echo "[tpagent] Cảnh báo: giới hạn RAM container < 900MB — tool trình duyệt (Chromium) có thể bị tắt giữa chừng. Nên dùng gói >= 1GB RAM."
  fi
fi

exec "$@"
