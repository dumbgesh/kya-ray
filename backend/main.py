"""
backend/main.py - Main entrypoint for Kya-Ray Cloud Backend.

Runs the FastAPI application exposing REST and streaming endpoints.
"""

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.config import get_settings
from backend.routes.ai import router as ai_router, get_ai_provider

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="High-performance cloud AI inference backend for Kya-Ray desktop companion.",
    docs_url="/docs",
    redoc_url="/redoc",
)

class HostValidationMiddleware:
    """Pure ASGI middleware protecting local backend against DNS rebinding attacks by validating the Host header."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            raw_host_bytes = headers.get(b"host", b"")
            raw_host = raw_host_bytes.decode("latin-1", errors="ignore").split(":")[0].strip().lower()
            allowed_hosts = {"127.0.0.1", "localhost", "testserver", settings.HOST.split(":")[0].lower()}
            if raw_host and raw_host not in allowed_hosts:
                response = JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Forbidden: Untrusted Host header."},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


# CORS Middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.ALLOWED_CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(HostValidationMiddleware)

# Mount Routers
app.include_router(ai_router, prefix="/api/v1/ai", tags=["AI Inference"])


@app.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Backend Health Check",
    description="Returns backend service health, version, and GroqCloud provider readiness.",
    tags=["System"],
)
async def health_check():
    """Health check endpoint reporting API and provider readiness."""
    provider = get_ai_provider()
    return {
        "status": "healthy",
        "service": "kya-ray-backend",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "groq_configured": provider.is_configured(),
        "model": settings.GROQ_MODEL,
    }


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanly closes AI provider client and connection pools upon backend termination."""
    provider = get_ai_provider()
    if hasattr(provider, "close"):
        try:
            close_res = provider.close()
            if hasattr(close_res, "__await__"):
                await close_res
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn

    provider = get_ai_provider()
    print("=" * 60)
    print(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    print(f"Host: {settings.HOST}:{settings.PORT} ({settings.ENVIRONMENT})")
    print(f"Effective Groq Model: {settings.GROQ_MODEL}")
    print(f"Groq API Key Configured: {provider.is_configured()}")
    print("=" * 60)

    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
    )
