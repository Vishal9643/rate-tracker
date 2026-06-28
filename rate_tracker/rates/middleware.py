"""
Middleware for Rate-Tracker.
"""
import json
import logging
import time

logger = logging.getLogger('rates.middleware')


class SlowQueryMiddleware:
    """
    Log a warning for any HTTP request that takes longer than 200ms.
    Satisfies Phase 4C observability requirement.
    """
    THRESHOLD_MS = 200

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - start) * 1000, 2)

        if duration_ms > self.THRESHOLD_MS:
            logger.warning(json.dumps({
                'event': 'slow_request',
                'path': request.path,
                'method': request.method,
                'status_code': response.status_code,
                'duration_ms': duration_ms,
            }))

        return response
