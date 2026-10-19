from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.exceptions import (
    custom_validation_exception_handler,
    sqlalchemy_exception_handler,
    global_exception_handler
)
from app.api.v1.api import api_router

# Setup structured logging
setup_logging()
logger = logging.getLogger("networkos")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Crawl4AI persistent browser pool once on server startup
    try:
        from app.services.web.crawler import CrawlerService
        await CrawlerService.get_crawler()
    except Exception as e:
        logger.warning(f"Crawl4AI lifespan startup warning: {e}")
    yield
    # Gracefully shut down on server stop
    try:
        from app.services.web.crawler import CrawlerService
        await CrawlerService.shutdown()
    except Exception as e:
        logger.warning(f"Crawl4AI lifespan shutdown warning: {e}")

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    description="NetworkOS Backend API Foundation",
    lifespan=lifespan
)

# CORS Config
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception Handlers
app.add_exception_handler(RequestValidationError, custom_validation_exception_handler)
app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)
# Mount central API router under both standard versioned path
# and legacy unversioned path.
app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(api_router, prefix="/api")

@app.get("/scrape", tags=["scraping"])
@app.post("/scrape", tags=["scraping"])
async def scrape_endpoint(
    url: str = Query(..., description="Target webpage URL to scrape")
):
    """
    High-fidelity asynchronous webpage scraper powered by Crawl4AI.
    Renders JavaScript and extracts markdown, links, and media.
    """
    from app.services.web.crawler import CrawlerService
    try:
        result = await CrawlerService.scrape_page(url)
        raw_links = result.get("links", [])
        links = raw_links[:50] if isinstance(raw_links, list) else raw_links
        raw_media = result.get("media", {})
        media = raw_media[:20] if isinstance(raw_media, list) else raw_media
        return {
            "title": result.get("title", ""),
            "markdown": result.get("markdown", ""),
            "url": result.get("url", url),
            "links": links,
            "media": media,
        }
    except Exception as e:
        logger.exception("Scrape endpoint error: %s", e)
        error_msg = str(e) or repr(e)
        raise HTTPException(status_code=500, detail=error_msg)

@app.get("/health", tags=["health"])
async def root_health():
    return {"status": "ok", "message": "Go to /api/v1/health for detailed status."}

# Crawl4AI integration active
