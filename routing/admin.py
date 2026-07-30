from django.contrib import admin
from routing.models import FuelStation, GeocodeCache


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'state', 'retail_price', 'latitude', 'longitude')
    list_filter = ('state',)
    search_fields = ('name', 'city')


@admin.register(GeocodeCache)
class GeocodeCacheAdmin(admin.ModelAdmin):
    list_display = ('city', 'state', 'latitude', 'longitude', 'resolved')
    list_filter = ('resolved', 'state')