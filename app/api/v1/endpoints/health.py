from fastapi import APIRouter
from sqlalchemy import text

from app.db.session import db_session

router = APIRouter()


@router.get("")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/db")
async def database_healthcheck() -> dict[str, str]:
    async with db_session.session() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}
