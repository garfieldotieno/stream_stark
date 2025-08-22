#!/bin/sh
set -e

# Wait for MinIO to start
sleep 5

# Download mc if not available
if ! command -v mc >/dev/null 2>&1; then
  curl -sSL https://dl.min.io/client/mc/release/linux-amd64/mc -o /usr/local/bin/mc
  chmod +x /usr/local/bin/mc
fi

# Configure mc client and apply CORS
mc alias set local http://127.0.0.1:9000 minioadmin minioadmin
mc admin config import local < /root/.minio/config/cors.json
mc admin service restart local
