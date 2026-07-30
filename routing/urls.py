from django.urls import path
from routing.views import RoutePlanView

urlpatterns = [
    path('route/plan/', RoutePlanView.as_view(), name='route-plan'),
]