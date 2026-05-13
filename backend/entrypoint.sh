#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
while ! python -c "
import asyncio, sys, os

async def check():
    try:
        import asyncpg
        url = os.environ.get('ASD_DATABASE_URL', '')
        # asyncpg expects a plain postgresql:// URL, not the SQLAlchemy dialect
        dsn = url.replace('postgresql+asyncpg://', 'postgresql://')
        conn = await asyncpg.connect(dsn)
        await conn.close()
        return True
    except Exception:
        return False

sys.exit(0 if asyncio.run(check()) else 1)
" 2>/dev/null; do
    sleep 1
done
echo "PostgreSQL is ready."

echo "Running database migrations..."
alembic upgrade head

echo "Starting application..."
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000
