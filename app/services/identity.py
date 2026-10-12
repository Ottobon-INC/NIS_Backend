from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.identity import Contact, ExternalIdentity, ContactStatus
from app.models.evidence import SourceResult
import logging
import uuid

logger = logging.getLogger("networkos")

class IdentityResolver:
    @staticmethod
    async def process_source_result(db: AsyncSession, contact_id: str, source_result: SourceResult):
        if source_result.status != "SUCCESS":
            return
            
        c_res = await db.execute(select(Contact).where(Contact.id == contact_id))
        contact = c_res.scalars().first()
        if not contact:
            return
            
        data = source_result.extracted_data or {}
        
        # Simple extraction logic (mocking advanced NLP for now)
        title = data.get("title", "")
        text = data.get("text", "")
        
        updated = False
        full_name = None
        current_title = None
        current_company = None
        
        if title:
            parts = title.split("-")
            if len(parts) > 0:
                full_name = parts[0].strip()
            if len(parts) > 1:
                current_title = parts[1].strip()
            if len(parts) > 2:
                current_company = parts[2].split("|")[0].strip()

        # Handle agent-reach search results
        if source_result.source_id == "agent_reach" and "raw_data" in data:
            raw_data = data["raw_data"]
            # raw_data could be a list of results if it's a search
            if isinstance(raw_data, list) and len(raw_data) > 0:
                # E.g., agent-reach might return [{"title": "John Doe - GitHub", "link": "https://github.com/johndoe"}]
                first_result = raw_data[0]
                if isinstance(first_result, dict):
                    full_name = first_result.get("title", full_name)
                    link = first_result.get("link", first_result.get("href"))
                    if link:
                        current_title = "GitHub Profile" if "github.com" in link else "Twitter Profile" if "twitter.com" in link else "Social Profile"
                        current_company = link

        if full_name:
            identifier_str = f"{full_name} | {current_title} | {current_company}"
            # Check if this identity already exists to prevent UniqueViolationError
            existing = await db.execute(select(ExternalIdentity).where(ExternalIdentity.identifier == identifier_str))
            if not existing.scalars().first():
                candidate_id = ExternalIdentity(
                    id=str(uuid.uuid4()),
                    contact_id=contact.id,
                    provider=source_result.source_id,
                    identifier_type="candidate_profile",
                    identifier=identifier_str
                )
                db.add(candidate_id)
                updated = True

        if updated:
            contact.status = ContactStatus.RESEARCHING
        else:
            # If identity information is insufficient
            pass
            
        await db.commit()
