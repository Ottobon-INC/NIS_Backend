import sys
import logging
import asyncio
import threading
from typing import Dict, Any, Optional

logger = logging.getLogger("networkos.crawler")

class _CrawlerRunner:
    """
    Dedicated worker thread running an asyncio ProactorEventLoop (on Windows)
    or standard event loop (on Linux/macOS).

    This circumvents the Windows Uvicorn --reload limitation where Uvicorn sets
    WindowsSelectorEventLoopPolicy (which lacks subprocess support and raises
    NotImplementedError when Playwright launches browsers).
    """
    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._crawler = None
        self._lock = threading.Lock()
        self._init_event = threading.Event()

    def _start_worker(self):
        if sys.platform == "win32":
            self._loop = asyncio.ProactorEventLoop()
        else:
            self._loop = asyncio.new_event_loop()

        asyncio.set_event_loop(self._loop)
        self._init_event.set()
        self._loop.run_forever()

    def ensure_running(self):
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._init_event.clear()
                self._thread = threading.Thread(target=self._start_worker, daemon=True, name="Crawl4AI-Worker")
                self._thread.start()
                self._init_event.wait(timeout=5.0)

    def run_coroutine(self, coro):
        self.ensure_running()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future

_runner = _CrawlerRunner()


class CrawlerService:
    """
    Manages a single long-lived AsyncWebCrawler instance across the FastAPI application lifecycle.
    Prevents spawning and closing a new browser instance per incoming request (which incurs 1-3s overhead).
    Provides JS rendering, anti-bot stealth bypass, and clean LLM-ready markdown extraction.
    """

    @classmethod
    async def _async_start_crawler(cls):
        from crawl4ai import AsyncWebCrawler, BrowserConfig
        if _runner._crawler is not None:
            return _runner._crawler

        browser_cfg = BrowserConfig(
            headless=True,
            verbose=False
        )
        crawler = AsyncWebCrawler(config=browser_cfg)
        await crawler.start()
        _runner._crawler = crawler
        logger.info("Crawl4AI: AsyncWebCrawler pool started successfully.")
        return crawler

    @classmethod
    async def _async_close_crawler(cls):
        if _runner._crawler is not None:
            try:
                await _runner._crawler.close()
                logger.info("Crawl4AI: AsyncWebCrawler pool closed gracefully.")
            except Exception as e:
                logger.warning(f"Crawl4AI: Error closing crawler: {e}")
            finally:
                _runner._crawler = None

    @classmethod
    async def get_crawler(cls):
        """Initializes and returns the shared AsyncWebCrawler instance on the worker loop."""
        try:
            from crawl4ai import AsyncWebCrawler
        except ImportError:
            logger.warning("Crawl4AI is not installed in the environment.")
            return None

        fut = _runner.run_coroutine(cls._async_start_crawler())
        return await asyncio.wrap_future(fut)

    @classmethod
    async def shutdown(cls):
        """Gracefully shuts down the persistent browser crawler."""
        try:
            fut = _runner.run_coroutine(cls._async_close_crawler())
            await asyncio.wrap_future(fut)
        except Exception as e:
            logger.warning(f"Crawl4AI: Shutdown error: {e}")

    @classmethod
    async def _async_scrape(cls, url: str, bypass_cache: bool, timeout_ms: int) -> Dict[str, Any]:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode

        if _runner._crawler is None:
            await cls._async_start_crawler()

        crawler = _runner._crawler
        if crawler is None:
            raise RuntimeError("AsyncWebCrawler failed to initialize.")

        run_cfg = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS if bypass_cache else CacheMode.ENABLED,
            word_count_threshold=10,
            page_timeout=timeout_ms,
        )

        result = await crawler.arun(url=url, config=run_cfg)
        if result.success:
            links = []
            if result.links:
                if isinstance(result.links, dict):
                    links = result.links.get("internal", []) + result.links.get("external", [])
                elif isinstance(result.links, list):
                    links = result.links

            title = ""
            if hasattr(result, "metadata") and isinstance(result.metadata, dict):
                title = result.metadata.get("title", "")

            return {
                "success": True,
                "url": result.url,
                "title": title,
                "markdown": result.markdown or "",
                "html": result.cleaned_html or "",
                "links": links,
                "media": getattr(result, "media", []),
                "status_code": getattr(result, "status_code", 200)
            }
        else:
            raise RuntimeError(f"Crawl failed: {result.error_message}")

    @classmethod
    async def scrape_page(cls, url: str, bypass_cache: bool = True, timeout_ms: int = 30000) -> Dict[str, Any]:
        """
        Scrapes a webpage using Crawl4AI on the dedicated proactor worker thread.
        Returns clean markdown, title, links, and media.
        """
        try:
            import crawl4ai
        except ImportError:
            raise RuntimeError("crawl4ai is not installed in the environment.")

        fut = _runner.run_coroutine(cls._async_scrape(url, bypass_cache, timeout_ms))
        return await asyncio.wrap_future(fut)
