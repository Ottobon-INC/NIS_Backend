import urllib.parse
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

db_uri = settings.SQLALCHEMY_DATABASE_URI
connect_args = {}

if "supabase" in settings.POSTGRES_SERVER or "pooler" in settings.POSTGRES_SERVER or "supabase" in str(settings.SQLALCHEMY_DATABASE_URI):
    connect_args = {"ssl": "require"}

engine = create_async_engine(
    db_uri,
    echo=False,
    future=True,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=10,
    pool_timeout=10,
    pool_recycle=300
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            raise e
        finally:
            await session.close()
