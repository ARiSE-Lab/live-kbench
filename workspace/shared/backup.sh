#!/bin/bash
# Database backup script for karena.db

set -e

# Configuration
DB_FILE="$(dirname "$0")/karena.db"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${DB_FILE}.backup_${TIMESTAMP}"

# Check if database exists
if [ ! -f "$DB_FILE" ]; then
    echo "Error: Database file not found: $DB_FILE"
    exit 1
fi

# Create backup
echo "Creating backup of $DB_FILE..."
cp "$DB_FILE" "$BACKUP_FILE"

# Verify backup
if [ -f "$BACKUP_FILE" ]; then
    BACKUP_SIZE=$(stat -f%z "$BACKUP_FILE" 2>/dev/null || stat -c%s "$BACKUP_FILE" 2>/dev/null)
    echo "Backup created successfully: $BACKUP_FILE"
    echo "Backup size: $(numfmt --to=iec-i --suffix=B $BACKUP_SIZE 2>/dev/null || echo "$BACKUP_SIZE bytes")"
else
    echo "Error: Backup failed"
    exit 1
fi
