from fastapi import APIRouter

from app.api.v1 import auth, candidates, company, interviews, reports, tts

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(candidates.router)
api_router.include_router(interviews.router)
api_router.include_router(reports.router)
api_router.include_router(company.router)
api_router.include_router(tts.router)


@api_router.get("/health")
async def health():
    return {"status": "ok", "version": "v1"}
