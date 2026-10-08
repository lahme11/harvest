"""The producers app's public interface: producer profiles, farm verification and collection slots."""
import datetime as dt

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from . import signals
from .models import CollectionPoint, CollectionSlot, FarmApplication, Producer

IN_USE_CHECKS = {'point': [], 'rule': [], 'slot': []}


class ProducerError(Exception):
    """A change that breaks a producer rule, e.g. applying twice for verification."""


def register_in_use_check(kind, check):
    """Let another app veto deleting a point, rule or slot it depends on (check(obj) -> True means in use)."""
    IN_USE_CHECKS[kind].append(check)


def _in_use(kind, obj):
    return any(check(obj) for check in IN_USE_CHECKS[kind])


def get_producer(user):
    if not user.is_authenticated:
        return None
    return Producer.objects.filter(user=user).first()


def is_verified(user):
    producer = get_producer(user)
    return bool(producer and producer.verified)


def unique_slug(name, exclude_pk=None):
    base = slugify(name.replace('’', '').replace("'", '')) or 'producer'
    slug, n = base, 2
    others = Producer.objects.exclude(pk=exclude_pk)
    while others.filter(slug=slug).exists():
        slug = f'{base}-{n}'
        n += 1
    return slug


def create_producer(user, name, county, description=''):
    if Producer.objects.filter(user=user).exists():
        raise ProducerError('You already have a producer profile.')
    return Producer.objects.create(user=user, name=name, slug=unique_slug(name), county=county,
                                   description=description)


def pending_application(producer):
    return producer.applications.filter(status=FarmApplication.Status.PENDING).first()


def apply_for_verification(producer, farm_name, registration_no, county, description):
    if producer.verified:
        raise ProducerError('Your farm is already verified.')
    if pending_application(producer):
        raise ProducerError('You already have an application waiting for review.')
    application = FarmApplication.objects.create(producer=producer, farm_name=farm_name,
                                                 registration_no=registration_no, county=county,
                                                 description=description)
    signals.farm_application_submitted.send(sender=FarmApplication, application=application)
    return application


def _decide(application, status, staff_user, reason=''):
    if application.status != FarmApplication.Status.PENDING:
        raise ProducerError('This application has already been decided.')
    application.status = status
    application.reason = reason
    application.decided_at = timezone.now()
    application.decided_by = staff_user
    application.save()
    signals.farm_application_decided.send(sender=FarmApplication, application=application)


@transaction.atomic
def approve_application(application, staff_user=None):
    producer = application.producer
    producer.verified = True
    producer.verified_at = timezone.now()
    producer.county = application.county
    producer.save()
    _decide(application, FarmApplication.Status.APPROVED, staff_user)


def reject_application(application, reason, staff_user=None):
    reason = (reason or '').strip()
    if not reason:
        raise ProducerError('Give a reason so the applicant knows what to fix.')
    _decide(application, FarmApplication.Status.REJECTED, staff_user, reason)


def _slot_times(rule):
    """(start, end) wall-clock times of each slot a rule produces in one day."""
    length = dt.timedelta(minutes=rule.slot_minutes)
    day = dt.date(2000, 1, 1)
    start = dt.datetime.combine(day, rule.start_time)
    end_of_day = dt.datetime.combine(day, rule.end_time)
    while start + length <= end_of_day:
        yield start.time(), (start + length).time()
        start += length


def generate_slots(point=None, days=None, today=None, now=None):
    """Create the concrete slots for the next `days` days from every active rule; returns how many were new."""
    days = settings.SLOT_DAYS_AHEAD if days is None else days
    now = now or timezone.now()
    today = today or timezone.localdate(now)
    points = CollectionPoint.objects.filter(active=True)
    if point is not None:
        points = points.filter(pk=point.pk)
    created = 0
    for collection_point in points.prefetch_related('rules'):
        for rule in collection_point.rules.all():
            if not rule.active:
                continue
            for offset in range(days):
                date = today + dt.timedelta(days=offset)
                if date.weekday() != rule.weekday:
                    continue
                for start_time, end_time in _slot_times(rule):
                    start = timezone.make_aware(dt.datetime.combine(date, start_time))
                    if start <= now:
                        continue
                    end = timezone.make_aware(dt.datetime.combine(date, end_time))
                    _, was_created = CollectionSlot.objects.get_or_create(
                        point=collection_point, start=start,
                        defaults={'end': end, 'capacity': rule.capacity, 'rule': rule})
                    created += was_created
    return created


def regenerate_rule_slots(rule):
    """After a rule changes: drop its future slots nobody has booked, then generate them again."""
    for slot in rule.slots.filter(start__gt=timezone.now()):
        if not _in_use('slot', slot):
            slot.delete()
    return generate_slots(point=rule.point)


def bookable_slots(producer, now=None):
    """Future slots at the producer's active points that are still open for orders (outside the cut-off)."""
    now = now or timezone.now()
    slots = (CollectionSlot.objects.filter(point__producer=producer, point__active=True, start__gt=now)
             .select_related('point').order_by('start'))
    return [slot for slot in slots if slot.start > now + dt.timedelta(hours=slot.point.cutoff_hours)]


def can_delete_point(point):
    return not _in_use('point', point)


def delete_point(point):
    if not can_delete_point(point):
        raise ProducerError('This collection point has open orders or subscriptions, so it cannot be deleted. '
                            'Untick "active" to stop new orders instead.')
    point.delete()


def can_delete_rule(rule):
    return not _in_use('rule', rule)


def delete_rule(rule):
    if not can_delete_rule(rule):
        raise ProducerError('Subscribers collect at this time, so it cannot be deleted. Untick "active" instead.')
    for slot in rule.slots.filter(start__gt=timezone.now()):
        if not _in_use('slot', slot):
            slot.delete()
    rule.delete()


COLLECTED_ORDER_CHECK = [lambda user, producer: False]


def register_collected_order_check(check):
    """The orders app tells us whether a buyer has collected an order from a producer."""
    COLLECTED_ORDER_CHECK[0] = check


def can_review(user, producer):
    if not user.is_authenticated or not producer.verified or producer.user_id == user.pk:
        return False
    return COLLECTED_ORDER_CHECK[0](user, producer)


def save_review(user, producer, rating, text):
    from .models import Review

    if not can_review(user, producer):
        raise ProducerError('You can review a farm after collecting an order from it.')
    if rating not in (1, 2, 3, 4, 5):
        raise ProducerError('Choose a rating from 1 to 5 stars.')
    text = (text or '').strip()
    if not text:
        raise ProducerError('Write a few words about your experience.')
    review, _ = Review.objects.update_or_create(producer=producer, author=user,
                                                defaults={'rating': rating, 'text': text})
    return review


def reply(review, user, text):
    if review.producer.user_id != user.pk:
        raise ProducerError('Only the farm can reply to its reviews.')
    if review.reply:
        raise ProducerError('You have already replied to this review.')
    text = (text or '').strip()
    if not text:
        raise ProducerError('Write a reply first.')
    review.reply = text
    review.replied_at = timezone.now()
    review.save(update_fields=['reply', 'replied_at'])
    return review


def rating_summary(producer):
    """(average rating rounded to one decimal, number of reviews); the average is None with no reviews."""
    from django.db.models import Avg, Count

    data = producer.reviews.aggregate(avg=Avg('rating'), count=Count('pk'))
    average = round(data['avg'], 1) if data['avg'] is not None else None
    return average, data['count']
