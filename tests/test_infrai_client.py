import httpx

from infrai_client import InfraiClient


def test_client_decodes_429_envelope_then_honors_retry_after() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "3"},
                json={"ok": False, "data": None, "error": {"code": "RATE_LIMITED"}, "metadata": {}},
            )
        return httpx.Response(
            200,
            json={"ok": True, "data": {"items": []}, "error": None, "metadata": {}},
        )

    delays: list[float] = []
    client = InfraiClient(
        "test-key",
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    )
    try:
        result = client.webhook_deliveries("wh_123")
    finally:
        client.close()

    assert result == {"items": []}
    assert calls == 2
    assert delays == [3.0]

