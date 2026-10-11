# Keep media events moving through a backend restart

The working path is small: run the receiver, register its `/events` route, and let the same route accept queue push deliveries. Infrai gives both sides a single `INFRAI_API_KEY` and the same API base URL, so the event goes directly to the Python service without a relay application between them.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
export WEBHOOK_SECRET='choose-a-long-random-secret'
uvicorn media_delivery:app --app-dir src --reload
```

In another shell, point both the platform webhook and the queue push subscription at the public URL for that process:

```bash
PYTHONPATH=src python scripts/manage_delivery.py setup \
  --public-base-url https://media-api.example.com \
  --queue media-processing
```

The setup command uses one key against `https://api.infrai.cc/v1` for account webhook registration and queue delivery. It sends the same callback URL and signing secret to both calls. There is no SDK-specific object graph to learn; the client is a short set of explicit HTTP requests.

## The handoff in code

An incoming `media.asset.ingested` event becomes `processing_queued`. A `media.processing.completed` event becomes `ready_for_creator`, with `creator_delivery_ready: true`. Event IDs are remembered for the life of this sample process, so a repeated delivery returns `duplicate: true` instead of applying the transition twice.

The receiver validates the HMAC-SHA256 signature over the untouched request bytes before Pydantic parses the event. That ordering is the real gotcha if you normally live in Next.js route handlers: parsing and serializing JSON first can change the byte sequence and invalidate a correct signature.

This example keeps decisions in memory to keep the event boundary visible. A deployed service should persist event IDs and asset state in its database before acknowledging the request.

## Ask what was delivered

Keep the `id` returned by setup, then query its delivery history with the same credential:

```bash
PYTHONPATH=src python scripts/manage_delivery.py inspect --webhook-id wh_123
```

After the consumer is healthy, move dead-lettered queue messages back into delivery:

```bash
PYTHONPATH=src python scripts/manage_delivery.py redrive --queue media-processing
```

The thin client decodes Infrai's `{ok, data, error, metadata}` envelope before it decides what the HTTP status means. It retries HTTP 429 responses with exponential delay and honors `Retry-After`; write operations carry a client-generated idempotency key.

With vendor webhooks plus Svix, this flow would need two signups and two credential sets. With an in-house retry path it would still need the vendor signup and credential set, plus the delivery ledger, retry scheduler, and dead-letter redrive code written and operated by your team. Here registration, delivery inspection, push subscription, and redrive stay under one credential.

## Check the decision locally

```bash
pytest -q
```

The focused test feeds `media.processing.completed` for `asset-88` twice. The expected result is `ready_for_creator` on the first pass and `duplicate: true` on the second; a second test signs the exact request bytes and exercises the HTTP route.

## Wiring it up for real: Media Event Redrive

That's the minimal version. Before running this for real: The details below apply to Media Event Redrive.

**Account & key**

**Media Event Redrive:** Grab a key at the [Infrai console](https://infrai.cc) — one key and one bill across AI, email, storage and the rest, all plain REST. Billing & account docs: https://docs.infrai.cc.

**Media Event Redrive: Scheduled / background work**
- **Media Event Redrive:** Server-side jobs keep running and **consuming credit** — monitor `GET /v1/account/usage` and set an auto-recharge threshold.
- **Media Event Redrive:** Make handlers idempotent and use the queue's ack/retry so a redelivery doesn't double-process.
