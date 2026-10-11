from __future__ import annotations

import hashlib
import hmac
import json
import os
from enum import StrEnum
from threading import Lock

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, ValidationError


class MediaEventType(StrEnum):
    ASSET_INGESTED = "media.asset.ingested"
    PROCESSING_COMPLETED = "media.processing.completed"
    PROCESSING_FAILED = "media.processing.failed"


class MediaEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: MediaEventType
    asset_id: str
    creator_id: str
    source_uri: str
    rendition_uri: str | None = None


class DeliveryDecision(BaseModel):
    event_id: str
    asset_id: str
    state: str
    creator_delivery_ready: bool
    duplicate: bool


class MediaWorkflow:
    def __init__(self) -> None:
        self._decisions: dict[str, DeliveryDecision] = {}
        self._lock = Lock()

    def apply(self, event: MediaEvent) -> DeliveryDecision:
        with self._lock:
            previous = self._decisions.get(event.event_id)
            if previous:
                return previous.model_copy(update={"duplicate": True})

            state = {
                MediaEventType.ASSET_INGESTED: "processing_queued",
                MediaEventType.PROCESSING_COMPLETED: "ready_for_creator",
                MediaEventType.PROCESSING_FAILED: "processing_failed",
            }[event.event_type]
            decision = DeliveryDecision(
                event_id=event.event_id,
                asset_id=event.asset_id,
                state=state,
                creator_delivery_ready=event.event_type
                is MediaEventType.PROCESSING_COMPLETED,
                duplicate=False,
            )
            self._decisions[event.event_id] = decision
            return decision


def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    supplied = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, supplied)


workflow = MediaWorkflow()
app = FastAPI(title="Media delivery receiver")


@app.post("/events", response_model=DeliveryDecision)
async def receive_event(
    request: Request,
    x_infrai_signature: str = Header(alias="X-Infrai-Signature"),
) -> DeliveryDecision:
    body = await request.body()
    secret = os.environ.get("WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="WEBHOOK_SECRET is required")
    if not verify_signature(body, x_infrai_signature, secret):
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        event = MediaEvent.model_validate(json.loads(body))
    except (json.JSONDecodeError, ValidationError) as error:
        raise HTTPException(status_code=422, detail="invalid media event") from error
    return workflow.apply(event)
