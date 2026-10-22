import logging
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import text, func

from app.db.session import AsyncSessionLocal
from app.models.opportunity import Opportunity, OpportunityLifecycleStatus
from app.models.scraped_job import ScrapedJob
from app.services.scraping.ports import ScrapedJobRecord, ScraperPort, IngestionStatus, CollectorResult
from app.services.scraping.collectors import DEFAULT_COLLECTORS
from app.services.scraping.normalizer import (
    clean_html_to_text,
    canonicalize_url,
    normalize_company_name,
    normalize_job_title,
    normalize_location,
    compute_content_hash,
    compute_cross_source_hash
)

logger = logging.getLogger("networkos.scraping.ingestion")

class JobIngestionService:
    """
    Core ingestion service that processes scraped job records into the dedicated
    'scraped_jobs' ledger and creates/updates linked 'Opportunity' entities
    in the opportunities section.
    """

    @classmethod
    async def ingest_single_record(
        cls,
        session: AsyncSession,
        record: ScrapedJobRecord,
        organization_id: str = "org-1"
    ) -> Tuple[IngestionStatus, Optional[str], Optional[str]]:
        """
        Idempotently ingests one job record.
        Returns: (status, opportunity_id, error_message)
        """
        try:
            # 1. Normalize attributes
            clean_desc = clean_html_to_text(record.description_raw)
            clean_title = (record.title or "").strip()
            clean_company = (record.company_name or "").strip()
            norm_company = normalize_company_name(clean_company)
            norm_title = normalize_job_title(clean_title)
            norm_loc = normalize_location(record.location)
            canonical_url = canonicalize_url(record.apply_url)

            # Compute fingerprints
            content_hash = compute_content_hash(clean_title, clean_company, clean_desc)
            cross_source_hash = compute_cross_source_hash(norm_company, norm_title, norm_loc)

            # Deterministic canonical opportunity ID based on cross-source fingerprint
            # Prevents race conditions from ever creating two opportunities for the same role
            canonical_opp_id = f"opp-job-{cross_source_hash[:16]}"

            now = datetime.now(timezone.utc)

            # 2. Check for existing source record (Tier 1: source + external_id)
            stmt = select(ScrapedJob).where(
                ScrapedJob.source == record.source,
                ScrapedJob.external_id == record.external_id
            )
            res = await session.execute(stmt)
            existing_job: Optional[ScrapedJob] = res.scalars().first()

            if existing_job:
                # Existing job found for this source
                if existing_job.content_hash == content_hash:
                    # Content unchanged: touch last_scraped_at and reset missing counter
                    existing_job.last_scraped_at = now
                    existing_job.consecutive_missing_count = 0
                    await session.commit()
                    return IngestionStatus.UNCHANGED, existing_job.opportunity_id, None
                else:
                    # Content changed: update job record and linked opportunity
                    existing_job.content_hash = content_hash
                    existing_job.title = clean_title
                    existing_job.company_name = clean_company
                    existing_job.salary = record.salary
                    existing_job.description_raw = record.description_raw
                    existing_job.description_clean = clean_desc
                    existing_job.last_scraped_at = now
                    existing_job.consecutive_missing_count = 0
                    existing_job.updated_at = now

                    if existing_job.opportunity_id:
                        opp_stmt = select(Opportunity).where(Opportunity.id == existing_job.opportunity_id)
                        opp = (await session.execute(opp_stmt)).scalars().first()
                        if opp:
                            opp.title = clean_title
                            opp.description = cls._format_opportunity_description(clean_desc, record.apply_url, record.source)
                            opp.problem = f"Active Hiring: {clean_company} is recruiting for {clean_title} ({record.location or 'Remote'})."
                            opp.requirement = cls._extract_requirement_summary(clean_desc, record.tags)
                            opp.budget_signal = record.salary or opp.budget_signal
                            opp.updated_at = now

                    await session.commit()
                    return IngestionStatus.UPDATED, existing_job.opportunity_id, None

            # 3. Check for Cross-Source Duplicate (Tier 2: cross_source_hash or canonical_apply_url)
            # Find if another job board has already registered this exact position
            cross_stmt = select(ScrapedJob).where(
                (ScrapedJob.cross_source_hash == cross_source_hash) |
                (ScrapedJob.canonical_apply_url == canonical_url)
            ).order_by(ScrapedJob.created_at.asc())
            cross_res = await session.execute(cross_stmt)
            cross_match: Optional[ScrapedJob] = cross_res.scalars().first()

            target_opp_id = cross_match.opportunity_id if (cross_match and cross_match.opportunity_id) else canonical_opp_id

            # 4. Upsert/Find Canonical Opportunity
            opp_stmt = select(Opportunity).where(Opportunity.id == target_opp_id)
            opp = (await session.execute(opp_stmt)).scalars().first()

            if not opp:
                # Create brand new commercial opportunity in the opportunities section
                problem_stmt = f"Active Hiring: {clean_company} is actively recruiting for {clean_title} ({record.location or 'Remote'})."
                req_summary = cls._extract_requirement_summary(clean_desc, record.tags)
                full_desc = cls._format_opportunity_description(clean_desc, record.apply_url, record.source)

                opp = Opportunity(
                    id=target_opp_id,
                    organization_id=organization_id,
                    company_name=clean_company,
                    title=clean_title,
                    problem=problem_stmt,
                    requirement=req_summary,
                    description=full_desc,
                    opportunity_type="JOB_OPENING",
                    status=OpportunityLifecycleStatus.DISCOVERED,
                    confidence=85,
                    timeline="Active Hiring",
                    budget_signal=record.salary or "Disclosed in job posting",
                    delivery_path="NETWORK",
                    supporting_evidence_ids=[record.apply_url],
                    review_notes=f"Ingested from {record.source.capitalize()} on {now.strftime('%Y-%m-%d')}"
                )
                session.add(opp)
                await session.flush()
            else:
                # Add this source URL to supporting_evidence_ids if not already present
                ev_ids = list(opp.supporting_evidence_ids or [])
                if record.apply_url not in ev_ids:
                    ev_ids.append(record.apply_url)
                    opp.supporting_evidence_ids = ev_ids
                    opp.updated_at = now

            # 5. Insert ScrapedJob ledger entry
            scraped_job_id = f"job-{uuid.uuid4().hex[:12]}"
            new_job = ScrapedJob(
                id=scraped_job_id,
                organization_id=organization_id,
                source=record.source,
                external_id=record.external_id,
                opportunity_id=opp.id,
                content_hash=content_hash,
                cross_source_hash=cross_source_hash,
                title=clean_title,
                company_name=clean_company,
                normalized_company=norm_company,
                normalized_title=norm_title,
                apply_url=record.apply_url,
                canonical_apply_url=canonical_url,
                location=record.location or "Remote",
                salary=record.salary,
                description_raw=record.description_raw,
                description_clean=clean_desc,
                status="ACTIVE",
                consecutive_missing_count=0,
                published_at=record.published_at,
                last_scraped_at=now,
                raw_data=record.raw_data or {}
            )
            session.add(new_job)
            await session.commit()

            return IngestionStatus.NEW, opp.id, None

        except Exception as e:
            await session.rollback()
            logger.exception(f"Error ingesting record {record.source}:{record.external_id}: {e}")
            return IngestionStatus.FAILED, None, str(e)

    @classmethod
    def _extract_requirement_summary(cls, clean_desc: str, tags: List[str]) -> str:
        """Constructs a concise requirement string from tags and opening text."""
        tag_str = ", ".join(tags[:6]) if tags else ""
        intro = clean_desc[:300].strip()
        if tag_str:
            return f"Required Skills: {tag_str}. Overview: {intro}..."
        return intro or "Refer to full job posting description for detailed qualifications."

    @classmethod
    def _format_opportunity_description(cls, clean_desc: str, apply_url: str, source: str) -> str:
        """Formats job description with prominent metadata and application link."""
        header = f"**Source:** {source.capitalize()} | **Direct Apply:** {apply_url}\n\n---\n\n"
        return header + clean_desc

    @classmethod
    async def run_pipeline(
        cls,
        organization_id: str = "org-1",
        collectors: Optional[List[ScraperPort]] = None,
        limit_per_collector: int = 25
    ) -> Dict[str, Any]:
        """
        Executes the complete end-to-end scraping and ingestion pipeline across all collectors.
        Collects records, executes deduplication and database upserts, and tracks statistics.
        """
        active_collectors = collectors or DEFAULT_COLLECTORS
        start_time = datetime.now(timezone.utc)

        summary: Dict[str, Any] = {
            "started_at": start_time.isoformat(),
            "organization_id": organization_id,
            "total_collected": 0,
            "new": 0,
            "updated": 0,
            "unchanged": 0,
            "failed": 0,
            "source_summaries": {}
        }

        logger.info(f"Starting Job Ingestion Pipeline with {len(active_collectors)} collectors...")

        for collector in active_collectors:
            s_name = collector.source_name
            collector_stats = {
                "success": False,
                "collected": 0,
                "new": 0,
                "updated": 0,
                "unchanged": 0,
                "failed": 0,
                "error": None
            }

            try:
                # 1. Collect records with bounded execution
                collector_res: CollectorResult = await collector.scrape(limit=limit_per_collector)
                collector_stats["success"] = collector_res.success
                collector_stats["collected"] = collector_res.jobs_collected
                collector_stats["error"] = collector_res.error_message
                summary["total_collected"] += collector_res.jobs_collected

                if not collector_res.success:
                    logger.warning(f"Collector {s_name} failed: {collector_res.error_message}")
                    summary["source_summaries"][s_name] = collector_stats
                    continue

                # 2. Ingest collected records into database
                seen_external_ids = set()
                async with AsyncSessionLocal() as session:
                    for rec in collector_res.records:
                        seen_external_ids.add(rec.external_id)
                        status, opp_id, err = await cls.ingest_single_record(
                            session=session,
                            record=rec,
                            organization_id=organization_id
                        )

                        if status == IngestionStatus.NEW:
                            collector_stats["new"] += 1
                            summary["new"] += 1
                        elif status == IngestionStatus.UPDATED:
                            collector_stats["updated"] += 1
                            summary["updated"] += 1
                        elif status == IngestionStatus.UNCHANGED:
                            collector_stats["unchanged"] += 1
                            summary["unchanged"] += 1
                        elif status == IngestionStatus.FAILED:
                            collector_stats["failed"] += 1
                            summary["failed"] += 1

                    # 3. Track Missing Jobs (Safeguard 5: Only increment counter, do not auto-expire)
                    # When a scrape completes successfully, jobs from this source not in seen_external_ids
                    # get consecutive_missing_count += 1
                    if seen_external_ids:
                        missing_update_stmt = text("""
                            UPDATE scraped_jobs
                            SET consecutive_missing_count = consecutive_missing_count + 1,
                                updated_at = now()
                            WHERE source = :source
                              AND organization_id = :org_id
                              AND external_id NOT IN :seen_ids
                              AND status = 'ACTIVE'
                        """)
                        # Using tuple for IN clause
                        await session.execute(
                            text("""
                                UPDATE scraped_jobs
                                SET consecutive_missing_count = consecutive_missing_count + 1,
                                    updated_at = now()
                                WHERE source = :source
                                  AND organization_id = :org_id
                                  AND external_id != ALL(:seen_ids)
                                  AND status = 'ACTIVE'
                            """),
                            {"source": s_name, "org_id": organization_id, "seen_ids": list(seen_external_ids)}
                        )
                        await session.commit()

            except Exception as e:
                logger.exception(f"Unhandled error in pipeline for source {s_name}: {e}")
                collector_stats["success"] = False
                collector_stats["error"] = str(e)

            summary["source_summaries"][s_name] = collector_stats

        end_time = datetime.now(timezone.utc)
        summary["completed_at"] = end_time.isoformat()
        summary["duration_seconds"] = round((end_time - start_time).total_seconds(), 2)

        logger.info(
            f"Pipeline completed in {summary['duration_seconds']}s: "
            f"Collected={summary['total_collected']}, New={summary['new']}, "
            f"Updated={summary['updated']}, Unchanged={summary['unchanged']}, Failed={summary['failed']}"
        )
        return summary
