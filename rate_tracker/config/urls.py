"""
URL configuration for Rate-Tracker project.
"""
from django.contrib import admin
from django.urls import path, include
from rates.views import HealthCheckView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/rates/', include('rates.urls')),
    path('api/v1/health/', HealthCheckView.as_view(), name='health'),
]
