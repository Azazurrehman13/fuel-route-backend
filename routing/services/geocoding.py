import time
import requests
from django.conf import settings

MAPBOX_GEOCODING_URL = 'https://api.mapbox.com/geocoding/v5/mapbox.places/{query}.json'


class GeocodingError(Exception):
    pass


def geocode(query: str, retries: int = 3, delay: float = 0.5):
    """
    Resolve a free-text US location string (e.g. "Springfield, IL" or a full
    street address) to (latitude, longitude). Raises GeocodingError if no
    match is found after retries.
    """
    if not settings.MAPBOX_ACCESS_TOKEN:
        raise GeocodingError(
            'MAPBOX_ACCESS_TOKEN is not set. Sign up free at mapbox.com and '
            'set the MAPBOX_ACCESS_TOKEN environment variable.'
        )

    url = MAPBOX_GEOCODING_URL.format(query=requests.utils.quote(query))
    params = {
        'access_token': settings.MAPBOX_ACCESS_TOKEN,
        'country': 'us',
        'limit': 1,
        'types': 'place,address,postcode',
    }

    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            features = data.get('features', [])
            if features:
                lon, lat = features[0]['center']  # Mapbox returns [lon, lat]
                return float(lat), float(lon)
            last_err = f'No geocoding match for "{query}"'
        except requests.RequestException as exc:
            last_err = str(exc)
        time.sleep(delay)

    raise GeocodingError(last_err or f'Failed to geocode "{query}"')