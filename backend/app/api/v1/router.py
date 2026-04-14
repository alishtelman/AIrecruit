from fastapi import APIRouter

from app.api.v1 import admin, auth, candidates, company, employee, interviews, reports, stt, tts

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(candidates.router)
api_router.include_router(interviews.router)
api_router.include_router(reports.router)
api_router.include_router(company.router)
api_router.include_router(tts.router)
api_router.include_router(stt.router)
api_router.include_router(employee.router)


@api_router.get("/health")
async def health():
    return {"status": "ok", "version": "v1"}
