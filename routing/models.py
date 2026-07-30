from django.db import models


class GeocodeCache(models.Model):
    city = models.CharField(max_length=128)
    state = models.CharField(max_length=8)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        unique_together = ('city', 'state')

    def __str__(self):
        return f'{self.city}, {self.state}'


class FuelStation(models.Model):
    opis_id = models.IntegerField(db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=128)
    state = models.CharField(max_length=8)
    rack_id = models.IntegerField(null=True, blank=True)
    retail_price = models.DecimalField(max_digits=8, decimal_places=5)
    latitude = models.FloatField(null=True, blank=True, db_index=True)
    longitude = models.FloatField(null=True, blank=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['latitude', 'longitude']),
        ]

    def __str__(self):
        return f'{self.name} ({self.city}, {self.state}) - ${self.retail_price}'