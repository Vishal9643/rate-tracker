# API Layer Design

## URL Structure

```
/api/v1/rates/latest/          GET   — Latest rate per provider
/api/v1/rates/history/         GET   — Paginated time-series
/api/v1/rates/ingest/          POST  — Authenticated webhook
```

**Why `/api/v1/`**: Explicit versioning from day one. When the schema changes, we can ship `/api/v2/` without breaking existing consumers.

---

## Endpoint 1: `GET /api/v1/rates/latest/`

### Purpose
Return the most recent rate per provider, with optional type filter.

### Query Parameters
| Param | Type | Required | Example | Description |
|-------|------|----------|---------|-------------|
| `type` | string | No | `30yr_fixed_mortgage` | Filter by rate type |

### Response (200 OK)
```json
{
    "data": [
        {
            "provider": "Chase",
            "rate_type": "30yr_fixed_mortgage",
            "rate_value": "6.7500",
            "effective_date": "2026-03-25",
            "currency": "USD",
            "last_updated": "2026-03-25T18:30:00Z"
        },
        {
            "provider": "Wells Fargo",
            "rate_type": "30yr_fixed_mortgage",
            "rate_value": "6.8200",
            "effective_date": "2026-03-25",
            "currency": "USD",
            "last_updated": "2026-03-25T17:45:00Z"
        }
    ],
    "meta": {
        "count": 2,
        "cached": true,
        "cache_ttl_seconds": 300
    }
}
```

### Implementation Notes

**Query**: Uses PostgreSQL `DISTINCT ON` for efficient "latest per group":
```python
Rate.objects.filter(**filters) \
    .select_related('provider') \
    .order_by('provider__normalized_name', 'rate_type', '-effective_date', '-ingestion_ts') \
    .distinct('provider__normalized_name', 'rate_type')
```

**Caching Strategy**:
- Cache key: `rates:latest` or `rates:latest:type={type}`
- TTL: 300 seconds (5 minutes)
- Invalidation: When `POST /rates/ingest` writes new data, delete `rates:latest*` keys
- Framework: Django cache with Redis backend

```python
from django.core.cache import cache

CACHE_TTL = 300  # 5 minutes

def get_latest_rates(rate_type=None):
    cache_key = f"rates:latest:type={rate_type}" if rate_type else "rates:latest"
    cached = cache.get(cache_key)
    if cached:
        return cached, True  # data, is_cached

    queryset = Rate.objects.select_related('provider') \
        .order_by('provider__normalized_name', 'rate_type', '-effective_date', '-ingestion_ts') \
        .distinct('provider__normalized_name', 'rate_type')

    if rate_type:
        queryset = queryset.filter(rate_type=rate_type)

    data = list(queryset.values(...))
    cache.set(cache_key, data, CACHE_TTL)
    return data, False
```

---

## Endpoint 2: `GET /api/v1/rates/history/`

### Purpose
Paginated time-series for a provider + type combination.

### Query Parameters
| Param | Type | Required | Example | Description |
|-------|------|----------|---------|-------------|
| `provider` | string | Yes | `Chase` | Provider name |
| `type` | string | Yes | `30yr_fixed_mortgage` | Rate type |
| `from` | date | No | `2026-01-01` | Start date (inclusive) |
| `to` | date | No | `2026-03-26` | End date (inclusive) |
| `page` | int | No | `1` | Page number |
| `page_size` | int | No | `50` | Items per page (max 100) |

### Response (200 OK)
```json
{
    "data": [
        {
            "rate_value": "6.5000",
            "effective_date": "2026-03-01",
            "ingestion_ts": "2026-03-01T12:00:00Z"
        },
        {
            "rate_value": "6.6200",
            "effective_date": "2026-03-02",
            "ingestion_ts": "2026-03-02T12:00:00Z"
        }
    ],
    "meta": {
        "count": 245,
        "page": 1,
        "page_size": 50,
        "total_pages": 5,
        "provider": "Chase",
        "rate_type": "30yr_fixed_mortgage"
    }
}
```

### Error Response (400)
```json
{
    "errors": [
        {"field": "provider", "message": "This field is required."},
        {"field": "type", "message": "This field is required."}
    ]
}
```

### Implementation Notes

**Bounded results**: Default page_size=50, max=100. No unbounded result sets.

**Date validation**: If `from` > `to`, return 400. If `from` is not provided, default to 30 days ago.

```python
class RateHistoryView(APIView):
    pagination_class = RatePagination

    def get(self, request):
        provider = request.query_params.get('provider')
        rate_type = request.query_params.get('type')

        if not provider or not rate_type:
            return Response({'errors': [...]}, status=400)

        from_date = request.query_params.get('from', thirty_days_ago)
        to_date = request.query_params.get('to', today)

        queryset = Rate.objects.filter(
            provider__normalized_name__iexact=provider,
            rate_type=rate_type,
            effective_date__gte=from_date,
            effective_date__lte=to_date,
        ).order_by('effective_date', 'ingestion_ts')

        page = self.paginate_queryset(queryset)
        serializer = RateHistorySerializer(page, many=True)
        return self.get_paginated_response(serializer.data)
```

---

## Endpoint 3: `POST /api/v1/rates/ingest/`

### Purpose
Authenticated webhook. Accepts JSON rate data, validates, writes to DB, invalidates cache.

### Authentication
**Bearer token** via `Authorization: Bearer <token>` header.

### Request Body
```json
{
    "provider": "Chase",
    "rate_type": "30yr_fixed_mortgage",
    "rate_value": 6.75,
    "effective_date": "2026-03-26",
    "source_url": "https://www.chase.com/rates/30yr_fixed_mortgage",
    "currency": "USD"
}
```

### Response (201 Created)
```json
{
    "data": {
        "id": 1005001,
        "provider": "Chase",
        "rate_type": "30yr_fixed_mortgage",
        "rate_value": "6.7500",
        "effective_date": "2026-03-26",
        "currency": "USD",
        "created_at": "2026-03-26T20:00:00Z"
    }
}
```

### Error Responses

**400 Bad Request** — Validation failure:
```json
{
    "errors": [
        {"field": "rate_value", "message": "Rate value must be between 0 and 20."},
        {"field": "rate_type", "message": "Invalid rate type. Must be one of: 15yr_fixed_mortgage, 30yr_fixed_mortgage, 5yr_arm_mortgage, savings_1yr_fixed, savings_easy_access"}
    ]
}
```

**401 Unauthorized** — Missing or invalid token:
```json
{
    "detail": "Authentication credentials were not provided."
}
```

**409 Conflict** — Duplicate record:
```json
{
    "detail": "A rate record with this provider, type, date, and timestamp already exists."
}
```

### Implementation Notes

```python
class RateIngestView(APIView):
    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = RateIngestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'errors': format_errors(serializer.errors)}, status=400)

        # 1. Normalize provider name
        # 2. Store raw response
        # 3. Create Rate record
        # 4. Invalidate cache
        cache.delete_pattern('rates:latest*')

        return Response({'data': RateSerializer(rate).data}, status=201)
```

---

## Authentication: Bearer Token

### Implementation

```python
# rates/authentication.py
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.conf import settings

class BearerTokenAuthentication(BaseAuthentication):
    """
    Simple bearer token auth.
    Token is stored in settings (loaded from env var).
    """
    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        if not auth_header.startswith('Bearer '):
            return None  # Let other auth classes try

        token = auth_header[7:]  # Strip 'Bearer '

        if token != settings.API_INGEST_TOKEN:
            raise AuthenticationFailed('Invalid bearer token.')

        # Return a tuple of (user, auth) — use AnonymousUser with is_authenticated=True
        from django.contrib.auth.models import AnonymousUser
        user = AnonymousUser()
        user.is_authenticated = True
        return (user, token)
```

**Why not JWT/OAuth?**: The spec says *"no external auth service needed."* A simple bearer token comparison is sufficient. The token is loaded from an environment variable (`API_INGEST_TOKEN`).

---

## Serializers

```python
# rates/serializers.py

class RateLatestSerializer(serializers.Serializer):
    provider = serializers.CharField(source='provider__normalized_name')
    rate_type = serializers.CharField()
    rate_value = serializers.DecimalField(max_digits=10, decimal_places=4)
    effective_date = serializers.DateField()
    currency = serializers.CharField()
    last_updated = serializers.DateTimeField(source='ingestion_ts')


class RateHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Rate
        fields = ['rate_value', 'effective_date', 'ingestion_ts']


class RateIngestSerializer(serializers.Serializer):
    provider = serializers.CharField(max_length=255)
    rate_type = serializers.ChoiceField(choices=[
        '15yr_fixed_mortgage', '30yr_fixed_mortgage',
        '5yr_arm_mortgage', 'savings_1yr_fixed', 'savings_easy_access'
    ])
    rate_value = serializers.DecimalField(max_digits=10, decimal_places=4)
    effective_date = serializers.DateField()
    source_url = serializers.URLField(required=False, allow_blank=True)
    currency = serializers.CharField(max_length=10, default='USD')

    def validate_rate_value(self, value):
        if value < 0 or value > 20:
            raise serializers.ValidationError(
                'Rate value must be between 0 and 20.'
            )
        return value
```

---

## Cache Strategy

### Keys
| Key Pattern | Used By | TTL |
|-------------|---------|-----|
| `rates:latest` | GET /rates/latest (no filter) | 300s |
| `rates:latest:type={type}` | GET /rates/latest?type=... | 300s |

### Invalidation
- `POST /rates/ingest` → delete all `rates:latest*` keys
- `seed_data` command → delete all `rates:latest*` keys
- Celery scheduled ingestion → delete all `rates:latest*` keys

### Implementation
```python
# rates/services/cache_manager.py
from django.core.cache import cache

def invalidate_latest_cache():
    """Delete all cached 'latest rates' entries."""
    # Django's Redis backend supports delete_pattern
    cache.delete_pattern('rates:latest*')

def get_or_set_latest(rate_type=None, ttl=300):
    """Cache-aside pattern for latest rates."""
    key = f"rates:latest:type={rate_type}" if rate_type else "rates:latest"
    data = cache.get(key)
    if data is not None:
        return data, True
    data = _fetch_latest_from_db(rate_type)
    cache.set(key, data, ttl)
    return data, False
```

---

## Pagination

```python
# rates/pagination.py
from rest_framework.pagination import PageNumberPagination

class RatePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({
            'data': data,
            'meta': {
                'count': self.page.paginator.count,
                'page': self.page.number,
                'page_size': self.get_page_size(self.request),
                'total_pages': self.page.paginator.num_pages,
            }
        })
```

---

## Error Response Format

All error responses follow a consistent structure:

```json
{
    "errors": [
        {
            "field": "rate_value",       // null for non-field errors
            "message": "Human-readable error message."
        }
    ]
}
```

```python
# rates/utils.py
def format_errors(serializer_errors: dict) -> list:
    """Convert DRF serializer errors to our consistent format."""
    errors = []
    for field, messages in serializer_errors.items():
        for msg in messages:
            errors.append({
                'field': field if field != 'non_field_errors' else None,
                'message': str(msg),
            })
    return errors
```
