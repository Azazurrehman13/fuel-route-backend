from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings

from routing.models import FuelStation
from routing.services.geocoding import geocode, GeocodingError
from routing.services.directions_client import get_route, RoutingError
from routing.services.route_planner import (
    find_corridor_stations, plan_fuel_stops, RouteInfeasible,
)


class RoutePlanView(APIView):
    """
    POST /api/route/
    Body: {"start": "Chicago, IL", "finish": "Denver, CO"}
    """

    def post(self, request):
        start_query = (request.data.get('start') or '').strip()
        finish_query = (request.data.get('finish') or '').strip()

        if not start_query or not finish_query:
            return Response(
                {'error': 'Both "start" and "finish" location strings are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --- External call #1 & #2: geocode start/finish (one request each) ---
        try:
            start_lat, start_lon = geocode(start_query)
            finish_lat, finish_lon = geocode(finish_query)
        except GeocodingError as exc:
            return Response({'error': f'Could not locate a start/finish point: {exc}'},
                             status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        # --- External call #3: one single call to the routing engine ---
        try:
            route = get_route(start_lat, start_lon, finish_lat, finish_lon)
        except RoutingError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        distance_miles = route['distance_miles']

        # --- Everything below is local DB + numpy computation, no further external calls ---
        corridor_stations = find_corridor_stations(
            route['geometry'],
            FuelStation.objects.filter(latitude__isnull=False, longitude__isnull=False),
        )

        try:
            stops, total_cost = plan_fuel_stops(distance_miles, corridor_stations)
        except RouteInfeasible as exc:
            return Response({'error': str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        fuel_stops_payload = [
            {
                'name': s['station'].name,
                'address': s['station'].address,
                'city': s['station'].city,
                'state': s['station'].state,
                'latitude': s['station'].latitude,
                'longitude': s['station'].longitude,
                'price_per_gallon': float(s['station'].retail_price),
                'distance_along_route_miles': round(s['position_miles'], 1),
            }
            for s in stops
        ]

        return Response({
            'start': {'query': start_query, 'latitude': start_lat, 'longitude': start_lon},
            'finish': {'query': finish_query, 'latitude': finish_lat, 'longitude': finish_lon},
            'distance_miles': round(distance_miles, 1),
            'duration_hours': round(route['duration_seconds'] / 3600, 2),
            'route_geometry': [[lat, lon] for lat, lon in route['geometry']],
            'fuel_stops': fuel_stops_payload,
            'total_fuel_cost_usd': total_cost,
            'assumptions': {
                'vehicle_range_miles': settings.VEHICLE_MAX_RANGE_MILES,
                'vehicle_mpg': settings.VEHICLE_MPG,
                'route_corridor_miles': settings.ROUTE_CORRIDOR_MILES,
                'note': (
                    'Vehicle starts with a full tank, so the first leg is not '
                    'charged. Fuel bought at each stop is priced to cover the '
                    'distance to the next stop (or destination).'
                ),
            },
        })