"""System/health endpoints."""

from fastapi import APIRouter

router = APIRouter(tags=["system"])


@router.get("/")
async def root() -> dict[str, str]:
    return {"message": "Hello World"}


@router.get("/hello/{name}")
async def say_hello(name: str) -> dict[str, str]:
    return {"message": f"Hello {name}"}
