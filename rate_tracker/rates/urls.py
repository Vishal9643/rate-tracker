"""
URL routing for rates app.
"""
from django.urls import re_path
from rates.views import LatestRatesView, RateHistoryView, RateIngestView

urlpatterns = [
    re_path(r'^latest/?$', LatestRatesView.as_view(), name='rates-latest'),
    re_path(r'^history/?$', RateHistoryView.as_view(), name='rates-history'),
    re_path(r'^ingest/?$', RateIngestView.as_view(), name='rates-ingest'),
]
