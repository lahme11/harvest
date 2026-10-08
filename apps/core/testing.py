"""Factories shared by the test suites of every app."""
import datetime as dt
import shutil
import tempfile
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from PIL import Image

PASSWORD = 'harvest-test-pw-2026'


def make_user(username='buyer', **extra):
    extra.setdefault('email', f'{username}@example.com')
    return User.objects.create_user(username, password=PASSWORD, **extra)


def make_producer(username='farmer', name=None, county='cork', verified=False, **extra):
    from apps.producers.models import Producer
    from apps.producers.services import unique_slug

    user = extra.pop('user', None) or make_user(username)
    name = name or f'{username.title()} Farm'
    return Producer.objects.create(
        user=user, name=name, slug=unique_slug(name), county=county, description='Grass-fed and seasonal.',
        verified=verified, verified_at=timezone.now() if verified else None, **extra)


def make_point(producer, name='Farm gate', cutoff_hours=12, county=None):
    from apps.producers.models import CollectionPoint

    return CollectionPoint.objects.create(producer=producer, name=name, address='Main Road',
                                          county=county or producer.county, cutoff_hours=cutoff_hours)


def make_rule(point, weekday=5, start='09:00', end='12:00', slot_minutes=60, capacity=4):
    from apps.producers.models import SlotRule

    return SlotRule.objects.create(point=point, weekday=weekday, start_time=dt.time.fromisoformat(start),
                                   end_time=dt.time.fromisoformat(end), slot_minutes=slot_minutes, capacity=capacity)


def make_slot(point, start=None, hours_from_now=48, minutes=60, capacity=4, rule=None):
    from apps.producers.models import CollectionSlot

    start = start or (timezone.now() + dt.timedelta(hours=hours_from_now)).replace(second=0, microsecond=0)
    return CollectionSlot.objects.create(point=point, rule=rule, start=start,
                                         end=start + dt.timedelta(minutes=minutes), capacity=capacity)


def local(year, month, day, hour=0, minute=0):
    """An aware datetime in Europe/Dublin."""
    return timezone.make_aware(dt.datetime(year, month, day, hour, minute))


def image_upload(name='photo.jpg', size=(800, 600), color=(120, 160, 90), fmt='JPEG', exif=None):
    buffer = BytesIO()
    image = Image.new('RGB', size, color)
    if exif is not None:
        image.save(buffer, format=fmt, exif=exif)
    else:
        image.save(buffer, format=fmt)
    content_type = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}[fmt]
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


class TemporaryMediaMixin:
    """Store uploaded files in a temporary folder that is removed after the test class."""

    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp(prefix='harvest-test-media-')
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)


def make_product(producer, name='Carrots', category='vegetables', price='2.50', stock=10, ingredients='',
                 status='live', **extra):
    from decimal import Decimal

    from apps.catalogue.models import Product
    from apps.catalogue.services import refresh_analysis

    product = Product.objects.create(
        producer=producer, name=name, category=category, unit=extra.pop('unit', 'kg'), price=Decimal(price),
        stock=stock, ingredients=ingredients, status=status,
        published_at=timezone.now() if status == 'live' else None, **extra)
    refresh_analysis(product)
    product.save()
    return product


def make_order(buyer, product, quantity=1, slot=None, status='pending', **extra):
    """An order created directly (bypassing checkout), for lifecycle and reporting tests."""
    from decimal import Decimal

    from apps.orders.models import Order, OrderItem
    from apps.orders.services import next_order_number

    if slot is None:
        point = product.producer.points.first() or make_point(product.producer)
        slot = point.slots.filter(start__gt=timezone.now()).first() or make_slot(point)
    total = product.price * quantity
    order = Order.objects.create(number=next_order_number(timezone.localdate().year), buyer=buyer,
                                 producer=product.producer, slot=slot, point=slot.point, status=status,
                                 total=Decimal(total), **extra)
    OrderItem.objects.create(order=order, product=product, name=product.name, unit=product.get_unit_display(),
                             unit_price=product.price, quantity=quantity, line_total=total)
    return order
