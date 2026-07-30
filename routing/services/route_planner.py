import numpy as np
from django.conf import settings

EARTH_RADIUS_MILES = 3958.8


def _haversine_miles(lat1, lon1, lat2, lon2):
    """Vectorized haversine distance in miles. Args can be numpy arrays."""
    lat1r, lon1r, lat2r, lon2r = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2.0) ** 2
    c = 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    return EARTH_RADIUS_MILES * c


def _simplify_geometry(geometry, max_points=600):
    """Downsample the route polyline for speed while keeping first/last points."""
    if len(geometry) <= max_points:
        return geometry
    step = len(geometry) / max_points
    idx = [int(i * step) for i in range(max_points)]
    idx[-1] = len(geometry) - 1
    return [geometry[i] for i in idx]


def _route_cumulative_distance(geometry):
    lats = np.array([p[0] for p in geometry])
    lons = np.array([p[1] for p in geometry])
    seg_dist = _haversine_miles(lats[:-1], lons[:-1], lats[1:], lons[1:])
    cum = np.concatenate(([0.0], np.cumsum(seg_dist)))
    return lats, lons, cum


def find_corridor_stations(geometry, stations_qs):
    """
    Projects every FuelStation onto the (simplified) route polyline.
    Returns a list of dicts for stations within ROUTE_CORRIDOR_MILES of the
    route, each with: station object, position_miles (distance along the
    route at the nearest point), and lateral_distance_miles.
    """
    geometry = _simplify_geometry(geometry)
    route_lats, route_lons, cum_dist = _route_cumulative_distance(geometry)

    stations = [s for s in stations_qs if s.latitude is not None and s.longitude is not None]
    if not stations:
        return []

    station_lats = np.array([s.latitude for s in stations])
    station_lons = np.array([s.longitude for s in stations])

    # Cheap bounding-box pre-filter before the expensive pairwise haversine pass
    margin_deg = (settings.ROUTE_CORRIDOR_MILES / 69.0) + 0.1
    lat_min, lat_max = route_lats.min() - margin_deg, route_lats.max() + margin_deg
    lon_min, lon_max = route_lons.min() - margin_deg, route_lons.max() + margin_deg
    bbox_mask = (
        (station_lats >= lat_min) & (station_lats <= lat_max) &
        (station_lons >= lon_min) & (station_lons <= lon_max)
    )
    if not bbox_mask.any():
        return []

    candidate_idx = np.nonzero(bbox_mask)[0]
    cand_lats = station_lats[candidate_idx]
    cand_lons = station_lons[candidate_idx]

    # (n_candidates, n_route_points) distance matrix -> nearest route vertex per station
    dist_matrix = _haversine_miles(
        cand_lats[:, None], cand_lons[:, None],
        route_lats[None, :], route_lons[None, :],
    )
    nearest_idx = np.argmin(dist_matrix, axis=1)
    lateral_dist = dist_matrix[np.arange(len(candidate_idx)), nearest_idx]

    corridor_mask = lateral_dist <= settings.ROUTE_CORRIDOR_MILES
    results = []
    for local_i in np.nonzero(corridor_mask)[0]:
        station = stations[candidate_idx[local_i]]
        results.append({
            'station': station,
            'position_miles': float(cum_dist[nearest_idx[local_i]]),
            'lateral_distance_miles': float(lateral_dist[local_i]),
        })
    return results


class RouteInfeasible(Exception):
    pass


def plan_fuel_stops(total_distance_miles, corridor_stations):
    """
    Greedy cheapest-reachable-station algorithm.
    corridor_stations: list of {'station', 'position_miles', ...} (see above)
    Returns (stops, total_cost) where stops is an ordered list of dicts:
      {'station': FuelStation, 'position_miles': float, 'price': float}
    """
    max_range = settings.VEHICLE_MAX_RANGE_MILES
    mpg = settings.VEHICLE_MPG
    print(f"\nTotal Route Distance: {total_distance_miles:.2f} miles")

    if total_distance_miles <= max_range:
        return [], 0.0

    candidates = sorted(corridor_stations, key=lambda c: c['position_miles'])

    stops = []
    current_pos = 0.0
    used_positions = set()

    while total_distance_miles - current_pos > max_range:
        window = [
            c for c in candidates
            if current_pos < c['position_miles'] <= current_pos + max_range
            and id(c['station']) not in used_positions
        ]
        print("\n" + "=" * 60)
        print(f"Current Position : {current_pos:.2f}")
        print(f"Reachable Until  : {current_pos + max_range:.2f}")

        print("\nReachable Stations:")
        for s in window:
            print(
                f"{s['station'].name} | "
                f"{s['position_miles']:.1f} miles | "
                f"${float(s['station'].retail_price):.3f}"
            )
        if not window:
            raise RouteInfeasible(
                f'No fuel station found within range between mile {current_pos:.1f} '
                f'and mile {current_pos + max_range:.1f} of the route. Trip is not '
                f'completable with a {max_range}-mile range under current data.'
            )
        # cheapest first; break ties by picking the furthest along the route
        best = min(window, key=lambda c: (float(c['station'].retail_price), -c['position_miles']))
        print("\nSelected Station:")
        print(best['station'].name)
        print(f"Position: {best['position_miles']:.1f}")
        print(f"Price   : ${float(best['station'].retail_price):.3f}")
        stops.append(best)
        used_positions.add(id(best['station']))
        current_pos = best['position_miles']
        print(f"Next Current Position: {current_pos:.1f}")

    # cost: fuel bought at each stop covers the distance to the NEXT stop (or destination)
    total_cost = 0.0
    for i, stop in enumerate(stops):
        next_pos = stops[i + 1]['position_miles'] if i + 1 < len(stops) else total_distance_miles
        segment_miles = next_pos - stop['position_miles']
        gallons = segment_miles / mpg
        total_cost += gallons * float(stop['station'].retail_price)

    return stops, round(total_cost, 2)
