from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from typing import List, Optional
import uuid
import csv
import io
from datetime import date, datetime

from app.db.session import get_db
from app.models.identity import Contact, ContactType
from app.api.dependencies import get_current_user

router = APIRouter()


def _parse_connected_date(raw: str) -> Optional[date]:
    """Parse LinkedIn CSV date formats: 'DD MMM YYYY' or 'MM/DD/YYYY'"""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    for fmt in ("%d %b %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_linkedin_url(url: str) -> Optional[str]:
    if not url:
        return None
    url = url.strip().lower()
    if url.endswith("/"):
        url = url[:-1]
    if "linkedin.com/in/" in url and not url.startswith("https://"):
        url = "https://" + url.lstrip("http://")
    return url if "linkedin.com/in/" in url else None


@router.post("/import-csv")
async def import_bhanu_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Import Bhanu's LinkedIn Connections.csv.
    Creates BHANU_CONNECTION contact records.
    Skips rows already in the DB (matched by linkedin_url).
    Returns a summary: total rows, imported, skipped (duplicates).
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted.")

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")  # handles BOM from LinkedIn CSV
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))

    # LinkedIn CSV headers: First Name, Last Name, Email Address, Company, Position, Connected On
    batch_id = str(uuid.uuid4())
    imported = 0
    skipped = 0
    errors = []

    rows = list(reader)

    # Bulk query existing connections once to avoid N network roundtrips
    existing_res = await db.execute(
        select(Contact.full_name, Contact.current_company).where(
            Contact.contact_type == ContactType.BHANU_CONNECTION
        )
    )
    existing_set = {(r[0], r[1]) for r in existing_res.all()}

    new_contacts = []
    for row in rows:
        try:
            first_name = row.get("First Name", "").strip()
            last_name = row.get("Last Name", "").strip()
            full_name = f"{first_name} {last_name}".strip() or "Unknown"
            email = row.get("Email Address", "").strip() or None
            company = row.get("Company", "").strip() or None
            position = row.get("Position", "").strip() or None
            connected_on_raw = row.get("Connected On", "").strip()
            connected_since = _parse_connected_date(connected_on_raw)

            # Skip duplicate in memory
            if (full_name, company) in existing_set:
                skipped += 1
                continue

            existing_set.add((full_name, company))

            contact = Contact(
                id=str(uuid.uuid4()),
                organization_id=user.get("organization_id", "ottobon"),
                contact_type=ContactType.BHANU_CONNECTION,
                first_name=first_name,
                last_name=last_name,
                full_name=full_name,
                email=email,
                current_title=position,
                current_company=company,
                connected_since=connected_since,
                is_scored=False,
                import_batch_id=batch_id,
                reachability="UNKNOWN",
            )
            new_contacts.append(contact)
            imported += 1

        except Exception as e:
            errors.append(str(e))

    if new_contacts:
        db.add_all(new_contacts)
    await db.commit()

    return {
        "batch_id": batch_id,
        "total_rows": len(rows),
        "imported": imported,
        "skipped_duplicates": skipped,
        "errors": errors[:10],  # cap error list
    }


@router.get("/connections")
async def list_bhanu_connections(
    is_scored: Optional[bool] = Query(None, description="Filter by scoring status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List Bhanu's imported connections, optionally filtered by scoring status."""
    stmt = select(Contact).where(Contact.contact_type == ContactType.BHANU_CONNECTION)
    if is_scored is not None:
        stmt = stmt.where(Contact.is_scored == is_scored)
    stmt = stmt.offset(skip).limit(limit).order_by(Contact.full_name)
    result = await db.execute(stmt)
    contacts = result.scalars().all()

    return [
        {
            "id": c.id,
            "full_name": c.full_name,
            "current_title": c.current_title,
            "current_company": c.current_company,
            "email": c.email,
            "connected_since": c.connected_since.isoformat() if c.connected_since else None,
            "relationship_strength": c.relationship_strength,
            "reachability": c.reachability,
            "best_channel": c.best_channel,
            "relationship_notes": c.relationship_notes,
            "is_scored": c.is_scored,
            "import_batch_id": c.import_batch_id,
        }
        for c in contacts
    ]


@router.patch("/connections/{connection_id}/score")
async def score_bhanu_connection(
    connection_id: str,
    relationship_strength: int = Query(..., ge=1, le=5),
    reachability: str = Query(..., pattern="^(HIGH|MEDIUM|LOW|UNKNOWN)$"),
    best_channel: Optional[str] = Query(None, pattern="^(EMAIL|LINKEDIN|WHATSAPP|PHONE|UNKNOWN)$"),
    relationship_notes: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Score a single Bhanu connection (relationship strength, reachability, channel)."""
    result = await db.execute(
        select(Contact).where(
            Contact.id == connection_id,
            Contact.contact_type == ContactType.BHANU_CONNECTION,
        )
    )
    contact = result.scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Connection not found.")

    contact.relationship_strength = relationship_strength
    contact.reachability = reachability
    if best_channel:
        contact.best_channel = best_channel
    if relationship_notes is not None:
        contact.relationship_notes = relationship_notes
    contact.is_scored = True

    await db.commit()
    return {"id": contact.id, "is_scored": True, "relationship_strength": relationship_strength}


@router.get("/connections/stats")
async def bhanu_connections_stats(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Quick stats for the admin dashboard: total connections, scored vs unscored."""
    total_result = await db.execute(
        select(func.count()).where(Contact.contact_type == ContactType.BHANU_CONNECTION)
    )
    total = total_result.scalar() or 0

    scored_result = await db.execute(
        select(func.count()).where(
            Contact.contact_type == ContactType.BHANU_CONNECTION,
            Contact.is_scored == True,
        )
    )
    scored = scored_result.scalar() or 0

    return {
        "total": total,
        "scored": scored,
        "unscored": max(0, total - scored),
    }
