from __future__ import annotations

from erasure.auth import LoginThrottle


def test_login_throttle_blocks_then_expires() -> None:
    now = [100.0]
    throttle = LoginThrottle(
        max_failures=3,
        window_seconds=60,
        clock=lambda: now[0],
    )

    for _ in range(3):
        assert throttle.retry_after("local") == 0
        throttle.record_failure("local")

    assert throttle.retry_after("local") == 60
    now[0] = 159.1
    assert throttle.retry_after("local") == 1
    now[0] = 160.0
    assert throttle.retry_after("local") == 0


def test_success_clears_login_failures() -> None:
    throttle = LoginThrottle(max_failures=1)
    throttle.record_failure("local")
    assert throttle.retry_after("local") > 0

    throttle.record_success("local")

    assert throttle.retry_after("local") == 0


def test_login_throttle_rejects_invalid_limits() -> None:
    for values in ({"max_failures": 0}, {"window_seconds": 0}):
        try:
            LoginThrottle(**values)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid throttle limits must fail")
