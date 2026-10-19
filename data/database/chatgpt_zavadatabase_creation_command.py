python - <<'PY'
import asyncio
import asyncpg

async def create_database():
    conn = await asyncpg.connect(
        host="db",
        port=5432,
        user="postgres",
        password="P@ssw0rd!",
        database="postgres"
    )

    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = 'zava'"
        )

        if exists:
            print("Database 'zava' already exists.")
        else:
            await conn.execute("CREATE DATABASE zava")
            print("Database 'zava' created successfully.")
    finally:
        await conn.close()

asyncio.run(create_database())
PY