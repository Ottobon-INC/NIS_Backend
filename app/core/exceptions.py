from typing import Any
from fastapi import Request, status, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
import logging

logger = logging.getLogger("networkos")

def get_cors_headers(request: Request) -> dict:
    origin = request.headers.get("origin")
    headers = {
        "Access-Control-Allow-Methods": "*",
        "Access-Control-Allow-Headers": "*",
    }
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
    else:
        headers["Access-Control-Allow-Origin"] = "*"
    return headers

async def custom_validation_exception_handler(request: Request, exc: Any):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        headers=get_cors_headers(request),
        content={
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request parameters",
                "details": exc.errors() if hasattr(exc, "errors") else str(exc)
            }
        },
    )

async def sqlalchemy_exception_handler(request: Request, exc: Any):
    logger.error(f"Database error: {str(exc)}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        headers=get_cors_headers(request),
        content={
            "success": False,
            "error": {
                "code": "DATABASE_ERROR",
                "message": "An internal database error occurred."
            }
        },
    )

async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        logger.warning(f"HTTPException encountered: {exc.status_code} - {exc.detail}")
        return JSONResponse(
            status_code=exc.status_code,
            headers=get_cors_headers(request),
            content={
                "success": False,
                "error": {
                    "code": f"HTTP_{exc.status_code}",
                    "message": exc.detail
                },
                "detail": exc.detail
            }
        )
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        headers=get_cors_headers(request),
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": str(exc) or "An unexpected error occurred."
            },
            "detail": str(exc) or "An unexpected error occurred."
        },
    )

