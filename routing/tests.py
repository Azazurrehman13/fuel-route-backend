from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient

from routing.models import FuelStation
from routing.services.route_planner import find_corridor_stations, plan_fuel_stops


class FuelPlannerAlgorithmTests(TestCase):
    """Pure unit tests for the corridor filter + greedy fuel-stop algorithm."""

    def setUp(self):
        self.geometry = [(0.0, lon / 10.0) for lon in range(0, 151)]
        self.stations_data = [
            (2.0, '2.50'),
            (4.0, '4.00'),
            (6.5, '2.20'),
            (9.0, '3.90'),
            (11.5, '2.10'),
        ]
        for i, (lon, price) in enumerate(self.stations_data):
            FuelStation.objects.create(
                opis_id=i, name=f'Station-{i}', address='', city='Test', state='OK',
                rack_id=1, retail_price=price, latitude=0.0, longitude=lon,
            )

    def test_corridor_filter_finds_all_onroute_stations(self):
        corridor = find_corridor_stations(self.geometry, FuelStation.objects.all())
        self.assertEqual(len(corridor), 5)

    def test_short_trip_needs_no_stops(self):
        corridor = find_corridor_stations(self.geometry, FuelStation.objects.all())
        stops, cost = plan_fuel_stops(400.0, corridor)
        self.assertEqual(stops, [])
        self.assertEqual(cost, 0.0)

    def test_long_trip_picks_cheapest_reachable_station(self):
        corridor = find_corridor_stations(self.geometry, FuelStation.objects.all())
        stops, cost = plan_fuel_stops(900.0, corridor)
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0]['station'].name, 'Station-2')
        self.assertGreater(cost, 0)

    def test_very_long_trip_needs_two_stops(self):
        corridor = find_corridor_stations(self.geometry, FuelStation.objects.all())
        stops, cost = plan_fuel_stops(1100.0, corridor)
        self.assertEqual([s['station'].name for s in stops], ['Station-2', 'Station-4'])


class RoutePlanViewTests(TestCase):
    """API-level test with geocoding/OSRM mocked out (no real network calls)."""

    def setUp(self):
        self.client = APIClient()
        # Placed directly on the straight-line interpolation between the mocked
        # Chicago -> Denver coordinates used below, so it falls inside the corridor.
        FuelStation.objects.create(
            opis_id=1, name='Cheap Gas', address='', city='Midway', state='KS',
            rack_id=1, retail_price='2.50', latitude=40.60, longitude=-98.0,
        )

    @patch('routing.views.get_route')
    @patch('routing.views.geocode')
    def test_route_endpoint_happy_path(self, mock_geocode, mock_get_route):
        mock_geocode.side_effect = [(41.8781, -87.6298), (39.7392, -104.9903)]
        start = (41.8781, -87.6298)
        finish = (39.7392, -104.9903)
        steps = 60
        geometry = [
            (start[0] + (finish[0] - start[0]) * i / steps,
             start[1] + (finish[1] - start[1]) * i / steps)
            for i in range(steps + 1)
        ]
        mock_get_route.return_value = {
            'distance_miles': 400.0,
            'duration_seconds': 3600 * 6,
            'geometry': geometry,
        }
        resp = self.client.post('/api/route/', {'start': 'Chicago, IL', 'finish': 'Denver, CO'}, format='json')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn('route_geometry', body)
        self.assertIn('total_fuel_cost_usd', body)
        self.assertIn('fuel_stops', body)

    def test_route_endpoint_requires_both_fields(self):
        resp = self.client.post('/api/route/', {'start': 'Chicago, IL'}, format='json')
        self.assertEqual(resp.status_code, 400)