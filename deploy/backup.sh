#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Shopkeeper daily SQLite backup
# Installed to /etc/cron.daily/ by setup.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail

DB_PATH="/var/www/shopkeeper/data/shopkeeper.db"
BACKUP_DIR="/var/backups/shopkeeper"
RETENTION_DAYS=30

# Skip if no database exists yet
if [ ! -f "${DB_PATH}" ]; then
    exit 0
fi

mkdir -p "${BACKUP_DIR}"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/shopkeeper-${TIMESTAMP}.db"

# Use SQLite .backup for a consistent copy (safe even while server is running)
sqlite3 "${DB_PATH}" ".backup '${BACKUP_FILE}'"

# Compress
gzip "${BACKUP_FILE}"

# Prune old backups
find "${BACKUP_DIR}" -name "shopkeeper-*.db.gz" -mtime +${RETENTION_DAYS} -delete

echo "[backup] Created ${BACKUP_FILE}.gz"
