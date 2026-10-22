import argparse
import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.logging import setup_logging
from app.services.scraping.ingestion_service import JobIngestionService

setup_logging()
logger = logging.getLogger("networkos.workers.job_scraper")

# In-memory execution state tracking
class PipelineExecutionManager:
    _lock = asyncio.Lock()
    _is_running: bool = False
    _last_run_summary: Optional[Dict[str, Any]] = None
    _last_run_at: Optional[datetime] = None

    @classmethod
    def is_running(cls) -> bool:
        return cls._is_running

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        return {
            "is_running": cls._is_running,
            "last_run_at": cls._last_run_at.isoformat() if cls._last_run_at else None,
            "last_summary": cls._last_run_summary
        }

    @classmethod
    async def execute_job(cls, organization_id: str = "org-1", trigger_source: str = "SCHEDULED") -> Dict[str, Any]:
        """
        Executes the job scraping pipeline with strict overlap protection.
        """
        if cls._is_running:
            logger.warning(f"Job scraping pipeline already in progress. Skipping trigger ({trigger_source}).")
            return {
                "success": False,
                "message": "Scraping pipeline is already running. Overlapping run prevented.",
                "last_status": cls.get_status()
            }

        async with cls._lock:
            cls._is_running = True
            try:
                logger.info(f"Triggering Job Ingestion Pipeline ({trigger_source}) for organization '{organization_id}'...")
                summary = await JobIngestionService.run_pipeline(organization_id=organization_id)
                summary["trigger_source"] = trigger_source
                cls._last_run_summary = summary
                cls._last_run_at = datetime.now(timezone.utc)
                return summary
            except Exception as e:
                logger.exception(f"Error during job scraping execution: {e}")
                error_summary = {
                    "success": False,
                    "error": str(e),
                    "trigger_source": trigger_source,
                    "failed_at": datetime.now(timezone.utc).isoformat()
                }
                cls._last_run_summary = error_summary
                return error_summary
            finally:
                cls._is_running = False

def scheduled_cron_job():
    """Wrapper invoked by APScheduler cron."""
    logger.info("APScheduler triggered 2:00 AM Asia/Kolkata daily job scraping run.")
    asyncio.create_task(PipelineExecutionManager.execute_job(organization_id="org-1", trigger_source="DAILY_CRON_2AM_IST"))

def start_scheduler() -> AsyncIOScheduler:
    """
    Initializes and configures the APScheduler for daily 2:00 AM Asia/Kolkata runs.
    """
    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    
    # Run once daily at 2:00 AM IST
    trigger = CronTrigger(
        hour=2,
        minute=0,
        timezone="Asia/Kolkata"
    )

    scheduler.add_job(
        scheduled_cron_job,
        trigger=trigger,
        id="daily_job_scraper",
        name="Daily Job Board Scraping & Ingestion (2:00 AM IST)",
        replace_existing=True,
        coalesce=True,
        max_instances=1
    )

    scheduler.start()
    logger.info("Job Scraper Worker: APScheduler started. Scheduled daily run for 02:00 AM Asia/Kolkata (IST).")
    return scheduler

async def main():
    parser = argparse.ArgumentParser(description="NetworkOS Daily Job Scraper & Scheduler Worker")
    parser.add_argument("--run-now", action="store_true", help="Execute the scraping pipeline immediately once and exit")
    parser.add_argument("--org-id", type=str, default="org-1", help="Target organization ID (default: org-1)")
    parser.add_argument("--limit", type=int, default=25, help="Limit records per collector (default: 25)")
    args = parser.parse_args()

    if args.run_now:
        logger.info(f"Manual execution requested for organization '{args.org_id}'...")
        summary = await PipelineExecutionManager.execute_job(organization_id=args.org_id, trigger_source="MANUAL_CLI")
        print("\n--- JOB SCRAPING PIPELINE RUN SUMMARY ---")
        import json
        print(json.dumps(summary, indent=2))
        return

    # Start persistent scheduler
    scheduler = start_scheduler()

    # Handle graceful termination
    stop_event = asyncio.Event()

    def handle_signal():
        logger.info("Shutdown signal received. Shutting down APScheduler...")
        scheduler.shutdown(wait=False)
        stop_event.set()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, handle_signal)
    else:
        # Windows compatibility
        signal.signal(signal.SIGINT, lambda s, f: stop_event.set())
        signal.signal(signal.SIGTERM, lambda s, f: stop_event.set())

    logger.info("Job Scraper Worker daemon running. Press Ctrl+C to terminate.")
    try:
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        scheduler.shutdown(wait=False)
        logger.info("Job Scraper Worker daemon stopped cleanly.")

if __name__ == "__main__":
    asyncio.run(main())
