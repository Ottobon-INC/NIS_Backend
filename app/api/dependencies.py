from fastapi import Header, HTTPException, status

async def get_current_user(authorization: str = Header(default=None)):
    if not authorization or authorization != "Bearer mock-token":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": {"code": "UNAUTHORIZED", "message": "Not authenticated"}}
        )
    return {"user_id": "1", "role": "MEMBER", "organization_id": "org-1"}

async def get_current_admin(authorization: str = Header(default=None)):
    if not authorization or authorization != "Bearer mock-admin-token":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"success": False, "error": {"code": "FORBIDDEN", "message": "Admin access required"}}
        )
    return {"user_id": "2", "role": "ADMIN", "organization_id": "org-1"}
