"""Cron/systemd entry point: ``python -m seeker_os.inbound.poll``."""

from __future__ import annotations

import json
import sys

from seeker_os.config import get_settings
from seeker_os.inbound.oauth import OAuthError
from seeker_os.inbound.service import InboundDisabled, InboundService, SyncLocked


def main() -> int:
    settings = get_settings()
    if settings.email is None:
        print("Inbound email is not configured (config/email.yml is missing)", file=sys.stderr)
        return 2
    try:
        result = InboundService(settings.email).poll()
    except InboundDisabled as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OAuthError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except SyncLocked as exc:
        print(str(exc), file=sys.stderr)
        return 75
    except Exception as exc:
        print(f"Inbound poll failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result.__dict__, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
