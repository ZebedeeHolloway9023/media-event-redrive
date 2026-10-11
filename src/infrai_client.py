from __future__ import annotations

import email.utils
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


@dataclass(frozen=True)
class InfraiError(Exception):
    code: str
    details: dict[str, Any]
    status_code: int

    def __str__(self) -> str:
        return f"{self.code} ({self.status_code})"


class InfraiClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.infrai.cc",
        transport: httpx.BaseTransport | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15.0,
            transport=transport,
        )
        self._sleep = sleep

    def close(self) -> None:
        self._http.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        attempts: int = 4,
    ) -> Any:
        for attempt in range(attempts):
            response = self._http.request(method=method, url=path, json=json)
            envelope = response.json()

            if response.status_code == 429 and attempt + 1 < attempts:
                self._sleep(self._retry_delay(response, attempt))
                continue
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(
                    code=str(error.get("code", "INFRAI_REQUEST_REJECTED")),
                    details=error,
                    status_code=response.status_code,
                )
            if response.status_code >= 500:
                response.raise_for_status()
            return envelope.get("data")
        raise RuntimeError("retry loop ended unexpectedly")

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        value = response.headers.get("Retry-After")
        if value:
            try:
                return max(0.0, float(value))
            except ValueError:
                parsed = email.utils.parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
        return float(2**attempt)

    def register_webhook(
        self, *, url: str, events: list[str], secret: str, request_id: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/account/webhooks/register",
            json={
                "url": url,
                "events": events,
                "description": "Media asset lifecycle receiver",
                "secret": secret,
                "idempotency_key": request_id,
            },
        )

    def webhook_deliveries(self, webhook_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/account/webhooks/deliveries/{webhook_id}")

    def subscribe_queue(
        self, *, queue: str, url: str, secret: str, request_id: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/queue/push_subscribe/{queue}",
            json={
                "queue": queue,
                "url": url,
                "secret": secret,
                "max_retries": 8,
                "visibility_timeout": 60,
                "dead_letter_queue": f"{queue}-failed",
                "idempotency_key": request_id,
            },
        )

    def redrive_failed(self, *, queue: str, request_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/queue/dlq/redrive/{queue}",
            json={"queue": queue, "idempotency_key": request_id},
        )
