"""
API views for Rate-Tracker.

Endpoints:
  GET  /api/v1/health/          — Health check (no auth)
  GET  /api/v1/rates/latest/    — Latest rate per provider (cached, no auth)
  GET  /api/v1/rates/history/   — Paginated time-series (no auth)
  POST /api/v1/rates/ingest/    — Authenticated webhook
"""
import logging
from datetime import date, timedelta, datetime

from django.db import connection, IntegrityError
from django.utils import timezone as django_tz
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from rates.authentication import BearerTokenAuthentication
from rates.models import Provider, Rate, RawResponse, IngestionJob
from rates.pagination import RatePagination
from rates.serializers import (
    RateLatestSerializer,
    RateHistorySerializer,
    RateIngestSerializer,
    RateIngestResponseSerializer,
)
from rates.services.cache_manager import (
    get_cached_latest,
    set_latest_cache,
    invalidate_latest_cache,
)
from rates.services.data_cleaner import normalize_provider, normalize_currency
from rates.utils import format_errors

logger = logging.getLogger('rates.views')


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class HealthCheckView(APIView):
    """
    GET /api/v1/health/
    Simple liveness + readiness check used by Docker healthcheck.
    No authentication required.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        checks = {'status': 'healthy', 'db': 'ok', 'redis': 'ok'}

        # DB check
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
        except Exception as exc:
            checks['status'] = 'unhealthy'
            checks['db'] = str(exc)
            return Response(checks, status=503)

        # Redis / cache check
        try:
            from django.core.cache import cache
            cache.set('health_check', 'ok', timeout=10)
            val = cache.get('health_check')
            if val != 'ok':
                raise ValueError('Cache read returned unexpected value')
        except Exception as exc:
            # Redis is optional in local dev — degrade gracefully rather than 503
            checks['redis'] = 'unavailable'
            logger.warning('Redis health check failed: %s', exc)

        return Response(checks)


# ---------------------------------------------------------------------------
# GET /api/v1/rates/latest/
# ---------------------------------------------------------------------------

class LatestRatesView(APIView):
    """
    GET /api/v1/rates/latest/?type=<rate_type>

    Returns the most recent rate per provider (per type).
    Responses are cached in Redis with a 5-minute TTL.
    Cache is invalidated whenever new data is ingested.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        rate_type = request.query_params.get('type', '').strip() or None

        # --- Cache lookup ---
        cached_data, is_cached = get_cached_latest(rate_type)
        if is_cached:
            return Response({
                'data': cached_data,
                'meta': {
                    'count': len(cached_data),
                    'cached': True,
                    'cache_ttl_seconds': 300,
                }
            })

        # --- DB query: latest per (provider × rate_type) using DISTINCT ON ---
        from django.db import connection

        qs = Rate.objects.select_related('provider')
        if rate_type:
            qs = qs.filter(rate_type=rate_type)

        if connection.vendor == 'postgresql':
            qs = (
                qs.order_by(
                    'provider__normalized_name',
                    'rate_type',
                    '-effective_date',
                    '-ingestion_ts',
                )
                .distinct('provider__normalized_name', 'rate_type')
            )
            data = list(
                qs.values(
                    'provider__normalized_name',
                    'rate_type',
                    'rate_value',
                    'effective_date',
                    'currency',
                    'ingestion_ts',
                )
            )
        else:
            # Fallback for SQLite (local dev without Docker)
            qs = qs.order_by('-effective_date', '-ingestion_ts')
            seen = set()
            data = []
            for rate in qs:
                key = (rate.provider_id, rate.rate_type)
                if key not in seen:
                    seen.add(key)
                    data.append({
                        'provider__normalized_name': rate.provider.normalized_name,
                        'rate_type': rate.rate_type,
                        'rate_value': rate.rate_value,
                        'effective_date': rate.effective_date,
                        'currency': rate.currency,
                        'ingestion_ts': rate.ingestion_ts,
                    })

        # Normalise field names for response
        result = [
            {
                'provider': r['provider__normalized_name'],
                'rate_type': r['rate_type'],
                'rate_value': str(r['rate_value']),
                'effective_date': r['effective_date'].isoformat() if r['effective_date'] else None,
                'currency': r['currency'],
                'last_updated': (
                    r['ingestion_ts'].strftime('%Y-%m-%dT%H:%M:%SZ')
                    if r['ingestion_ts'] else None
                ),
            }
            for r in data
        ]

        # Write to cache
        set_latest_cache(result, rate_type)

        return Response({
            'data': result,
            'meta': {
                'count': len(result),
                'cached': False,
                'cache_ttl_seconds': 300,
            }
        })


# ---------------------------------------------------------------------------
# GET /api/v1/rates/history/
# ---------------------------------------------------------------------------

class RateHistoryView(APIView):
    """
    GET /api/v1/rates/history/?provider=<name>&type=<rate_type>&from=<date>&to=<date>

    Paginated time-series. Bounded: default 50, max 100 per page.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        provider_param = request.query_params.get('provider', '').strip()
        rate_type = request.query_params.get('type', '').strip()

        errors = []
        if not provider_param:
            errors.append({'field': 'provider', 'message': 'This field is required.'})
        if not rate_type:
            errors.append({'field': 'type', 'message': 'This field is required.'})
        if errors:
            return Response({'errors': errors}, status=400)

        from_str = request.query_params.get('from', '')
        to_str = request.query_params.get('to', '')

        from_date = None
        if from_str:
            try:
                from_date = date.fromisoformat(from_str)
            except ValueError:
                return Response({'errors': [{'field': 'from', 'message': f"Invalid date format: '{from_str}'. Use YYYY-MM-DD."}]}, status=400)

        to_date = None
        if to_str:
            try:
                to_date = date.fromisoformat(to_str)
            except ValueError:
                return Response({'errors': [{'field': 'to', 'message': f"Invalid date format: '{to_str}'. Use YYYY-MM-DD."}]}, status=400)

        if from_date and to_date and from_date > to_date:
            return Response({'errors': [{'field': 'from', 'message': "'from' date must not be after 'to' date."}]}, status=400)

        qs = Rate.objects.filter(
            provider__normalized_name__iexact=provider_param,
            rate_type=rate_type,
        )
        if from_date:
            qs = qs.filter(effective_date__gte=from_date)
        if to_date:
            qs = qs.filter(effective_date__lte=to_date)

        # Order descending to return newest first
        qs = qs.order_by('-effective_date', '-ingestion_ts')

        paginator = RatePagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = RateHistorySerializer(page, many=True)

        paginated_response = paginator.get_paginated_response(serializer.data)
        # Add context to meta
        paginated_response.data['meta']['provider'] = provider_param
        paginated_response.data['meta']['rate_type'] = rate_type
        if from_date:
            paginated_response.data['meta']['from'] = from_date.isoformat()
        if to_date:
            paginated_response.data['meta']['to'] = to_date.isoformat()

        return paginated_response


# ---------------------------------------------------------------------------
# POST /api/v1/rates/ingest/
# ---------------------------------------------------------------------------

class RateIngestView(APIView):
    """
    POST /api/v1/rates/ingest/

    Authenticated webhook. Validates, writes to DB, invalidates cache.
    Returns structured errors — never raw 500s.
    """
    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = RateIngestSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {'errors': format_errors(serializer.errors)},
                status=400,
            )

        validated = serializer.validated_data
        provider_name = normalize_provider(validated['provider'])
        currency = normalize_currency(validated.get('currency', 'USD'))

        # Get or create provider
        provider, _ = Provider.objects.get_or_create(
            normalized_name=provider_name,
            defaults={'name': validated['provider']},
        )

        # Store raw response for auditability
        import uuid
        raw_response = RawResponse.objects.create(
            raw_response_id=str(uuid.uuid4()),
            raw_data={k: str(v) for k, v in validated.items()},
            source_url=validated.get('source_url', ''),
            status='processed',
        )

        # Upsert the Rate record — idempotent on (provider, rate_type, effective_date)
        # If the same provider/type/date is posted again, update the rate_value and currency.
        # ingestion_ts is set on first creation only; updated_at tracks subsequent changes.
        try:
            from django.utils import timezone as tz
            rate, created = Rate.objects.update_or_create(
                provider=provider,
                rate_type=validated['rate_type'],
                effective_date=validated['effective_date'],
                defaults={
                    'rate_value': validated['rate_value'],
                    'currency': currency,
                    'source_url': validated.get('source_url', ''),
                    'raw_response': raw_response,
                    'ingestion_ts': tz.now(),
                },
            )
        except IntegrityError as exc:
            logger.error({'event': 'ingest_integrity_error', 'error': str(exc)})
            return Response(
                {'detail': 'Could not save rate record due to a data conflict.'},
                status=409,
            )

        # Invalidate latest-rates cache
        try:
            invalidate_latest_cache()
        except Exception as exc:
            logger.warning({'event': 'cache_invalidation_failed', 'error': str(exc)})

        logger.info({
            'event': 'rate_ingested_via_api',
            'rate_id': rate.id,
            'provider': provider_name,
            'rate_type': rate.rate_type,
            'created': created,
        })

        response_serializer = RateIngestResponseSerializer(rate)
        return Response({'data': response_serializer.data}, status=201 if created else 200)
