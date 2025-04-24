from django.db import models
import uuid
from django.utils import timezone

# Create your models here.

class RawCsv(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    EbayData = models.TextField(blank=True, null=True)
    WalmartData = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.name

class Key(models.Model):
    Client_Id = models.CharField(max_length=500)
    Client_Secret = models.CharField(max_length=500)
    Approved = models.BooleanField(default=False)

    def __str__(self):
        return str(self.Approved) +" - " +str(self.id)
    