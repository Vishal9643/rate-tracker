"""
Custom DRF authentication for Rate-Tracker.

Bearer token authentication for the POST /rates/ingest/ endpoint.
Token stored in settings.API_INGEST_TOKEN (loaded from env var API_INGEST_TOKEN).

Deliberately simple — spec says 'no external auth service needed'.
"""
import logging

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger('rates.auth')


class _AuthenticatedSystem:
    """Minimal user-like object that DRF's IsAuthenticated expects."""
    is_authenticated = True
    is_active = True

    def __str__(self):
        return 'system-api-user'


class BearerTokenAuthentication(BaseAuthentication):
    """
    Validates Authorization: Bearer <token> header.
    Returns a lightweight sentinel object (not a real Django User)
    because ingest operations don't require user identity — just API-key auth.
    """

    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        if not auth_header.startswith('Bearer '):
            return None  # Allows other authenticators to attempt

        token = auth_header[7:].strip()  # Strip 'Bearer '

        if not token:
            raise AuthenticationFailed('Bearer token is empty.')

        expected_token = getattr(settings, 'API_INGEST_TOKEN', '')
        if not expected_token:
            logger.error({'event': 'auth_misconfigured', 'detail': 'API_INGEST_TOKEN not set'})
            raise AuthenticationFailed('Server authentication is not configured.')

        if token != expected_token:
            logger.warning({'event': 'auth_invalid_token', 'path': request.path})
            raise AuthenticationFailed('Invalid bearer token.')

        return (_AuthenticatedSystem(), token)

    def authenticate_header(self, request):
        return 'Bearer realm="Rate-Tracker API"'
