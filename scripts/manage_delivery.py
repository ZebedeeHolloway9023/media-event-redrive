from __future__ import annotations

import argparse
import os
import uuid

from infrai_client import InfraiClient, InfraiError


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Set {name} before running this command")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure or inspect media delivery")
    subcommands = parser.add_subparsers(dest="command", required=True)

    setup = subcommands.add_parser("setup")
    setup.add_argument("--public-base-url", required=True)
    setup.add_argument("--queue", default="media-processing")

    inspect = subcommands.add_parser("inspect")
    inspect.add_argument("--webhook-id", required=True)

    redrive = subcommands.add_parser("redrive")
    redrive.add_argument("--queue", default="media-processing")

    args = parser.parse_args()
    client = InfraiClient(required_env("INFRAI_API_KEY"))
    try:
        if args.command == "setup":
            callback = f"{args.public_base_url.rstrip('/')}/events"
            secret = required_env("WEBHOOK_SECRET")
            webhook = client.register_webhook(
                url=callback,
                events=[event for event in (
                    "media.asset.ingested",
                    "media.processing.completed",
                    "media.processing.failed",
                )],
                secret=secret,
                request_id=f"media-webhook-{uuid.uuid5(uuid.NAMESPACE_URL, callback)}",
            )
            subscription = client.subscribe_queue(
                queue=args.queue,
                url=callback,
                secret=secret,
                request_id=f"media-push-{uuid.uuid5(uuid.NAMESPACE_URL, callback + args.queue)}",
            )
            print({"webhook": webhook, "push_subscription": subscription})
        elif args.command == "inspect":
            print(client.webhook_deliveries(args.webhook_id))
        else:
            request_id = f"media-redrive-{args.queue}-{uuid.uuid4()}"
            print(client.redrive_failed(queue=args.queue, request_id=request_id))
    except InfraiError as error:
        raise SystemExit(f"Infrai rejected the request: {error}") from error
    finally:
        client.close()


if __name__ == "__main__":
    main()

