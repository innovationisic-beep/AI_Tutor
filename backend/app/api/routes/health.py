from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
def health_check() -> dict:
    """Health check endpoint for load balancers and monitoring."""
    return {"status": "ok"}
