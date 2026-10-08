from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse

from apps.core.choices import COUNTIES


class ProducerQuerySet(models.QuerySet):
    def verified(self):
        return self.filter(verified=True)


class Producer(models.Model):
    """Someone who sells on Harvest: a home producer, or a verified farm once staff approve it."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='producer')
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True)
    county = models.CharField(max_length=20, choices=COUNTIES)
    description = models.TextField(blank=True)
    verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    organic_cert_no = models.CharField('organic certificate number', max_length=40, blank=True,
                                       help_text='Shown on certified organic products. Verified farms only.')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ProducerQuerySet.as_manager()

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('producers:detail', args=[self.slug])


class FarmApplication(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    producer = models.ForeignKey(Producer, on_delete=models.CASCADE, related_name='applications')
    farm_name = models.CharField(max_length=100)
    registration_no = models.CharField('registration or herd number', max_length=40)
    county = models.CharField(max_length=20, choices=COUNTIES)
    description = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    reason = models.TextField(blank=True, help_text='Shown to the applicant when an application is rejected.')
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.farm_name} ({self.get_status_display()})'


class CollectionPoint(models.Model):
    """Where buyers collect orders: a farm gate, a market stall or a shop."""

    producer = models.ForeignKey(Producer, on_delete=models.CASCADE, related_name='points')
    name = models.CharField(max_length=80)
    address = models.CharField(max_length=200)
    county = models.CharField(max_length=20, choices=COUNTIES)
    cutoff_hours = models.PositiveSmallIntegerField(
        'order cut-off (hours)', default=12, validators=[MaxValueValidator(72)],
        help_text='Orders and cancellations close this many hours before a slot starts.')
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name}, {self.get_county_display()}'


class SlotRule(models.Model):
    """A weekly pattern of collection slots, e.g. Saturdays 09:00–12:00 in one-hour slots for 5 orders each."""

    class Weekday(models.IntegerChoices):
        MONDAY = 0, 'Monday'
        TUESDAY = 1, 'Tuesday'
        WEDNESDAY = 2, 'Wednesday'
        THURSDAY = 3, 'Thursday'
        FRIDAY = 4, 'Friday'
        SATURDAY = 5, 'Saturday'
        SUNDAY = 6, 'Sunday'

    SLOT_LENGTHS = [(30, '30 minutes'), (60, '1 hour')]

    point = models.ForeignKey(CollectionPoint, on_delete=models.CASCADE, related_name='rules')
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    slot_minutes = models.PositiveSmallIntegerField('slot length', choices=SLOT_LENGTHS, default=60)
    capacity = models.PositiveSmallIntegerField('orders per slot', default=4,
                                                validators=[MinValueValidator(1), MaxValueValidator(100)])
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['weekday', 'start_time']

    def __str__(self):
        return f'{self.get_weekday_display()} {self.start_time:%H:%M}–{self.end_time:%H:%M}'


class CollectionSlot(models.Model):
    point = models.ForeignKey(CollectionPoint, on_delete=models.CASCADE, related_name='slots')
    rule = models.ForeignKey(SlotRule, null=True, blank=True, on_delete=models.SET_NULL, related_name='slots')
    start = models.DateTimeField()
    end = models.DateTimeField()
    capacity = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ['start']
        constraints = [models.UniqueConstraint(fields=['point', 'start'], name='unique_slot_start_per_point')]

    def __str__(self):
        from django.utils import timezone

        start = timezone.localtime(self.start)
        end = timezone.localtime(self.end)
        return f'{start:%a %d/%m %H:%M}–{end:%H:%M} at {self.point.name}'


class Review(models.Model):
    """A buyer's review of a verified farm, allowed after a collected order. The farm may reply once."""

    producer = models.ForeignKey(Producer, on_delete=models.CASCADE, related_name='reviews')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    text = models.TextField(max_length=2000)
    reply = models.TextField(blank=True, max_length=2000)
    replied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [models.UniqueConstraint(fields=['producer', 'author'], name='one_review_per_buyer')]

    def __str__(self):
        return f'{self.rating}★ for {self.producer} by {self.author}'
