#!/bin/bash
set -e

echo "[NetworkOS Backend] Starting entrypoint..."

# Wait for database if POSTGRES_SERVER is defined
if [ -n "$POSTGRES_SERVER" ]; then
    echo "[NetworkOS Backend] Checking database connection to $POSTGRES_SERVER:${POSTGRES_PORT:-5432}..."
    python - <<END
import sys
import socket
import time

host = "$POSTGRES_SERVER"
port = int("${POSTGRES_PORT:-5432}")

for attempt in range(30):
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"[NetworkOS Backend] Database {host}:{port} is reachable!")
            sys.exit(0)
    except Exception:
        print(f"[NetworkOS Backend] Waiting for database ({attempt + 1}/30)...")
        time.sleep(2)

print("[NetworkOS Backend] Database connection timed out, proceeding...")
END
fi

# Run seed & initial table setup when starting the API
if [ "$1" = "uvicorn" ]; then
    echo "[NetworkOS Backend] Ensuring database tables and default knowledge catalog exist..."
    python seed_db.py || echo "[NetworkOS Backend] seed_db completed or skipped."
fi

echo "[NetworkOS Backend] Executing command: $@"
exec "$@"

