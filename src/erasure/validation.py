from __future__ import annotations

from datetime import UTC, datetime, timedelta

from erasure.models import Broker

MAX_BATCH_SIZE = 10
VALIDATION_MAX_AGE = timedelta(days=90)


def is_recently_validated(broker: Broker, now: datetime | None = None) -> bool:
    validated_at = broker.last_validated_at
    if validated_at is None:
        return False
    if validated_at.tzinfo is None:
        validated_at = validated_at.replace(tzinfo=UTC)
    return validated_at >= (now or datetime.now(UTC)) - VALIDATION_MAX_AGE
