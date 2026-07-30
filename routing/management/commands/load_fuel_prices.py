import csv
import time
from django.core.management.base import BaseCommand
from django.conf import settings
from routing.models import FuelStation, GeocodeCache
from routing.services.geocoding import geocode, GeocodingError


class Command(BaseCommand):
    help = (
        'Loads the fuel prices CSV into the FuelStation table and geocodes '
        'every unique (city, state) pair ONCE via Nominatim, caching results '
        'in GeocodeCache. Safe to re-run: already-geocoded pairs are skipped, '
        'and FuelStation rows are replaced fresh each run.'
    )

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=str, help='Path to the fuel prices CSV file')
        parser.add_argument(
            '--skip-geocode', action='store_true',
            help='Load stations without geocoding (useful for quick local testing)',
        )

    def handle(self, *args, **options):
        csv_path = options['csv_path']
        skip_geocode = options['skip_geocode']

        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
        self.stdout.write(f'Read {len(rows)} rows from {csv_path}')

        unique_pairs = sorted({(r['City'].strip(), r['State'].strip()) for r in rows})
        self.stdout.write(f'{len(unique_pairs)} unique (city, state) pairs to geocode')

        if not skip_geocode:
            for i, (city, state) in enumerate(unique_pairs, start=1):
                cache_obj, created = GeocodeCache.objects.get_or_create(city=city, state=state)
                if cache_obj.resolved:
                    continue
                try:
                    lat, lon = geocode(f'{city}, {state}, USA')
                    cache_obj.latitude, cache_obj.longitude, cache_obj.resolved = lat, lon, True
                    cache_obj.save()
                except GeocodingError as exc:
                    self.stderr.write(f'  [{i}/{len(unique_pairs)}] FAILED "{city}, {state}": {exc}')
                if i % 50 == 0:
                    self.stdout.write(f'  ...geocoded {i}/{len(unique_pairs)}')
                time.sleep(1.0)  # respect Nominatim's 1 req/sec fair-use policy

        geo_lookup = {
            (g.city, g.state): (g.latitude, g.longitude)
            for g in GeocodeCache.objects.filter(resolved=True)
        }

        FuelStation.objects.all().delete()
        stations = []
        for r in rows:
            city, state = r['City'].strip(), r['State'].strip()
            lat, lon = geo_lookup.get((city, state), (None, None))
            stations.append(FuelStation(
                opis_id=int(r['OPIS Truckstop ID']),
                name=r['Truckstop Name'].strip(),
                address=r['Address'].strip(),
                city=city,
                state=state,
                rack_id=int(r['Rack ID']) if r['Rack ID'] else None,
                retail_price=r['Retail Price'],
                latitude=lat,
                longitude=lon,
            ))
        FuelStation.objects.bulk_create(stations, batch_size=500)
        geocoded_count = sum(1 for s in stations if s.latitude is not None)
        self.stdout.write(self.style.SUCCESS(
            f'Loaded {len(stations)} stations ({geocoded_count} with coordinates).'
        ))