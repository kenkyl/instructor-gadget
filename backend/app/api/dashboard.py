from fastapi import APIRouter

from app.auth import CurrentUserDep
from app.deps import Db, RedisDep
from app.services.dashboard import DashboardResponse, get_dashboard

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
async def dashboard(user: CurrentUserDep, db: Db, redis: RedisDep) -> DashboardResponse:
    return await get_dashboard(db, redis, user)
