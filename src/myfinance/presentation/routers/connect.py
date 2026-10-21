"""Connect-token endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends

from myfinance.application.use_cases import CreateConnectTokenUseCase
from myfinance.presentation.dependencies import get_create_connect_token_use_case
from myfinance.presentation.schemas import (
    ConnectTokenRequest,
    ConnectTokenResponse,
)

router = APIRouter(prefix="/api", tags=["connect"])


@router.post("/connect-token", response_model=ConnectTokenResponse)
async def create_connect_token(
    payload: ConnectTokenRequest,
    use_case: Annotated[
        CreateConnectTokenUseCase,
        Depends(get_create_connect_token_use_case),
    ],
) -> ConnectTokenResponse:
    token = await use_case.execute(payload.client_user_id)
    return ConnectTokenResponse(access_token=token.reveal())
