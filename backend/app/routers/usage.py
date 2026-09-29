"""作問数の残り（要件 N2-3）。上限に達してから知るのではなく、作問フォームで先に見せる。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import get_problem_service
from app.schemas.api import UsageStatus
from app.services.problem_service import ProblemService

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("", summary="作問数の残り")
def get_usage(service: Annotated[ProblemService, Depends(get_problem_service)]) -> UsageStatus:
    return service.usage_status()
