import requests
from django.conf import settings

METERS_PER_MILE = 1609.344
MAPBOX_DIRECTIONS_URL = 'https://api.mapbox.com/directions/v5/mapbox/driving/{coords}'


class RoutingError(Exception):
    pass


def get_route(start_lat, start_lon, finish_lat, finish_lon):
    """
    Calls Mapbox's Directions API once and returns a dict:
      {
        'distance_miles': float,
        'duration_seconds': float,
        'geometry': [(lat, lon), (lat, lon), ...]   # full route polyline
      }
    """
    if not settings.MAPBOX_ACCESS_TOKEN:
        raise RoutingError(
            'MAPBOX_ACCESS_TOKEN is not set. Sign up free at mapbox.com and '
            'set the MAPBOX_ACCESS_TOKEN environment variable.'
        )

    coords = f'{start_lon},{start_lat};{finish_lon},{finish_lat}'
    url = MAPBOX_DIRECTIONS_URL.format(coords=coords)
    params = {
        'access_token': settings.MAPBOX_ACCESS_TOKEN,
        'geometries': 'geojson',
        'overview': 'full',
        'alternatives': 'false',
        'steps': 'false',
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise RoutingError(f'Routing service request failed: {exc}')

    if data.get('code') != 'Ok' or not data.get('routes'):
        raise RoutingError(f'Routing service returned no route: {data.get("message", data.get("code"))}')

    route = data['routes'][0]
    # GeoJSON coordinates are [lon, lat] -- flip to (lat, lon) for the rest of our code
    geometry = [(lat, lon) for lon, lat in route['geometry']['coordinates']]

    return {
        'distance_miles': route['distance'] / METERS_PER_MILE,
        'duration_seconds': route['duration'],
        'geometry': geometry,
    }