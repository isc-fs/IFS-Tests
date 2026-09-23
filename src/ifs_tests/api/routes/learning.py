from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from ...services import learning
from ..deps import Member
from ..schemas import Learning

router = APIRouter(prefix="/api/learning", tags=["learning"])


@router.get("/{topic}")
def topic_aids(topic: Annotated[str, Path(max_length=32)], user: Member) -> Learning:
    return Learning.model_validate(learning.for_topic(user, topic))
