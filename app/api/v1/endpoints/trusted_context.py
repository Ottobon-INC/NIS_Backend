"""
Trusted Context API Endpoints.
NetworkOS Module: Founder-Confirmed Intelligence & Verified Ground Truth.

Provides:
- GET /contacts/{contact_id}/trusted-context : Retrieve verified context items for a contact.
- POST /contacts/{contact_id}/trusted-context: Create a new founder-confirmed ground truth context item.
- GET /trusted-context/{item_id}             : Retrieve a single trusted context item by ID.
- PATCH /trusted-context/{item_id}           : Update/correct trusted context with version increment & history retention.
- DELETE /trusted-context/{item_id}          : Remove a trusted context item.

All endpoints require authentication and strictly enforce multi-tenant isolation.
"""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.api.dependencies import get_current_user
from app.schemas.trusted_context import (
    TrustedContextItemOut,
    TrustedContextListResponse,
    TrustedContextCreateIn,
    TrustedContextUpdateIn,
    TrustedContextUpdateResponse,
)
from app.services.trusted_context_service import TrustedContextService

router = APIRouter(dependencies=[Depends(get_current_user)])


# ==============================================================================
# Contact-Scoped Endpoints
# ==============================================================================

@router.get("/contacts/{contact_id}/trusted-context", response_model=TrustedContextListResponse)
async def get_contact_trusted_context(
    contact_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Retrieves all founder-confirmed trusted context items for a specific contact.
    Enforces tenant boundaries and bootstraps initial context from Contact 360 intelligence if needed.
    """
    items = await TrustedContextService.get_for_contact(
        db=db,
        organization_id=user["organization_id"],
        contact_id=contact_id,
        auto_bootstrap=True,
    )
    return TrustedContextListResponse(
        items=[TrustedContextItemOut.model_validate(item) for item in items],
        total=len(items),
    )


@router.post(
    "/contacts/{contact_id}/trusted-context",
    status_code=status.HTTP_201_CREATED,
    response_model=TrustedContextItemOut,
)
async def create_contact_trusted_context(
    contact_id: str,
    payload: TrustedContextCreateIn,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Creates a new founder-confirmed trusted context item for a contact.
    Initializes version 1 and creates the first audit history record.
    """
    created = await TrustedContextService.create_trusted_context(
        db=db,
        organization_id=user["organization_id"],
        payload=payload,
        user=user,
        target_contact_id=contact_id,
    )
    return TrustedContextItemOut.model_validate(created)


# ==============================================================================
# Direct Item-Scoped Endpoints
# ==============================================================================

@router.get("/trusted-context/{item_id}", response_model=TrustedContextItemOut)
async def get_trusted_context_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Retrieves a specific trusted context item by ID.
    Strictly verifies tenant organization ownership.
    """
    item = await TrustedContextService.get_by_id(
        db=db,
        organization_id=user["organization_id"],
        item_id=item_id,
    )
    return TrustedContextItemOut.model_validate(item)


@router.patch("/trusted-context/{item_id}", response_model=TrustedContextUpdateResponse)
async def update_trusted_context_item(
    item_id: str,
    payload: TrustedContextUpdateIn,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Updates or corrects a trusted context statement.
    Increments current_version, preserves the previous version in history,
    and updates founder confirmation provenance.
    """
    updated = await TrustedContextService.update_trusted_context(
        db=db,
        organization_id=user["organization_id"],
        item_id=item_id,
        payload=payload,
        user=user,
    )
    return TrustedContextUpdateResponse(
        success=True,
        item=TrustedContextItemOut.model_validate(updated),
        message="Trusted context updated successfully",
    )


@router.delete("/trusted-context/{item_id}", status_code=status.HTTP_200_OK)
async def delete_trusted_context_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Deletes a trusted context record after tenant isolation verification."""
    await TrustedContextService.delete_trusted_context(
        db=db,
        organization_id=user["organization_id"],
        item_id=item_id,
    )
    return {"success": True, "message": "Trusted context deleted successfully"}
