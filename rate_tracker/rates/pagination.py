"""
Pagination classes for Rate-Tracker API.
"""
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class RatePagination(PageNumberPagination):
    """
    Pagination for GET /rates/history/
    Default 50 items, max 100. No unbounded result sets.
    """
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
                'next': self.get_next_link(),
                'previous': self.get_previous_link(),
            }
        })

    def get_paginated_response_schema(self, schema):
        return {
            'type': 'object',
            'properties': {
                'data': schema,
                'meta': {
                    'type': 'object',
                    'properties': {
                        'count': {'type': 'integer'},
                        'page': {'type': 'integer'},
                        'page_size': {'type': 'integer'},
                        'total_pages': {'type': 'integer'},
                    }
                }
            }
        }
