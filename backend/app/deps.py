"""FastAPI dependencies: one place to get a DB session, the Redis client, and the current user."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from agent.llm import LLMClient


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


def get_llm(request: Request) -> LLMClient:
    llm: LLMClient | None = request.app.state.llm
    if llm is None:
        raise HTTPException(503, "LLM not configured: set ANTHROPIC_API_KEY in .env")
    return llm


Db = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
LlmDep = Annotated[LLMClient, Depends(get_llm)]
