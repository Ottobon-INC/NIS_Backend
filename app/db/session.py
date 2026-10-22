import urllib.parse
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

db_uri = settings.SQLALCHEMY_DATABASE_URI
connect_args = {}

if "db.czgaluszcaedowkqbzne.supabase.co" in settings.POSTGRES_SERVER:
    pw = urllib.parse.unquote(settings.POSTGRES_PASSWORD)
    db_uri = f"postgresql+asyncpg://postgres.czgaluszcaedowkqbzne:{urllib.parse.quote_plus(pw)}@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres"
    connect_args = {"ssl": "require"}

engine = create_async_engine(
    db_uri,
    echo=settings.ENVIRONMENT == "development",
    future=True,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=3,
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
