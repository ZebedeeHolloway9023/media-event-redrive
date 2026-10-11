import hashlib
import hmac

from fastapi.testclient import TestClient

from media_delivery import MediaWorkflow, app


def test_completed_asset_is_ready_and_duplicate_is_not_reapplied() -> None:
    workflow = MediaWorkflow()
    payload = {
        "event_id": "evt-1042",
        "event_type": "media.processing.completed",
        "asset_id": "asset-88",
        "creator_id": "creator-7",
        "source_uri": "s3://incoming/asset-88.mov",
        "rendition_uri": "https://media.example/renditions/asset-88.m3u8",
    }

    from media_delivery import MediaEvent

    first = workflow.apply(MediaEvent.model_validate(payload))
    second = workflow.apply(MediaEvent.model_validate(payload))

    assert first.state == "ready_for_creator"
    assert first.creator_delivery_ready is True
    assert first.duplicate is False
    assert second.duplicate is True


def test_receiver_checks_the_real_request_body_signature(monkeypatch) -> None:
    monkeypatch.setenv("WEBHOOK_SECRET", "local-test-secret")
    body = (
        b'{"event_id":"evt-signed","event_type":"media.asset.ingested",'
        b'"asset_id":"asset-9","creator_id":"creator-2",'
        b'"source_uri":"s3://incoming/asset-9.mov"}'
    )
    signature = hmac.new(b"local-test-secret", body, hashlib.sha256).hexdigest()

    response = TestClient(app).post(
        "/events",
        content=body,
        headers={"Content-Type": "application/json", "X-Infrai-Signature": signature},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "processing_queued"

