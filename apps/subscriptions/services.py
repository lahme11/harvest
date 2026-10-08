"""The subscriptions app's public interface: veg-box subscriptions and the weekly order schedule."""
import datetime as dt
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalogue.models import Product
from apps.orders import services as orders
from apps.orders.models import Order
from apps.producers import services as producers
from apps.producers.models import CollectionSlot

from . import signals
from .models import MissedDelivery, SkippedDelivery, Subscription

GENERATE_DAYS_AHEAD = 7


class SubscriptionError(Exception):
    """A subscription change that breaks a rule, e.g. joining a full box."""


def current(box):
    return Subscription.objects.filter(box=box).exclude(status=Subscription.Status.CANCELLED)


def places_left(box):
    return max(0, (box.max_subscribers or 0) - current(box).count())


def rules_for(box):
    return box.producer.points.filter(active=True).values_list('rules', flat=True)


@transaction.atomic
def subscribe(user, box, rule):
    if box.kind != Product.Kind.BOX or not box.is_live:
        raise SubscriptionError('That is not a veg box you can subscribe to.')
    if box.producer.user_id == user.pk:
        raise SubscriptionError("You can't subscribe to your own box.")
    if rule.point.producer_id != box.producer_id or not rule.active or not rule.point.active:
        raise SubscriptionError('Choose one of the collection times offered for this box.')
    Product.objects.select_for_update().filter(pk=box.pk).first()
    if current(box).filter(buyer=user).exists():
        raise SubscriptionError('You already subscribe to this box.')
    if places_left(box) == 0:
        raise SubscriptionError('Sorry, this box is full.')
    try:
        subscription = Subscription.objects.create(buyer=user, box=box, rule=rule, start_date=first_bookable_date(rule))
    except IntegrityError:
        raise SubscriptionError('You already subscribe to this box.')
    signals.subscription_started.send(sender=Subscription, subscription=subscription)
    return subscription


def first_bookable_date(rule, now=None):
    """The first date on the rule's weekday whose collection time is still outside the point's cut-off."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    date = today + timedelta(days=(rule.weekday - today.weekday()) % 7)
    start = timezone.make_aware(dt.datetime.combine(date, rule.start_time))
    if start <= now + timedelta(hours=rule.point.cutoff_hours):
        date += timedelta(days=7)
    return date


def _first_date(subscription):
    start = subscription.start_date
    return start + timedelta(days=(subscription.rule.weekday - start.weekday()) % 7)


def due_dates(subscription, start, end):
    """Collection dates between start and end (inclusive) on the subscription's schedule."""
    first = _first_date(subscription)
    step = 14 if subscription.box.box_frequency == Product.Frequency.FORTNIGHTLY else 7
    if end < first:
        return []
    offset = max(0, (start - first).days)
    current_date = first + timedelta(days=-(-offset // step) * step)
    dates = []
    while current_date <= end:
        dates.append(current_date)
        current_date += timedelta(days=step)
    return dates


def _slot_start(subscription, date):
    return timezone.make_aware(dt.datetime.combine(date, subscription.rule.start_time))


def upcoming(subscription, count=4):
    today = timezone.localdate()
    dates = due_dates(subscription, today, today + timedelta(days=7 * 2 * count))[:count]
    skipped = set(subscription.skipped.values_list('date', flat=True))
    return [(date, date in skipped) for date in dates]


@transaction.atomic
def skip(subscription, date):
    """Skip one delivery, up to the collection point's cut-off; cancels its order if it already exists."""
    if date not in due_dates(subscription, date, date):
        raise SubscriptionError('There is no delivery due on that date.')
    deadline = _slot_start(subscription, date) - timedelta(hours=subscription.rule.point.cutoff_hours)
    if timezone.now() >= deadline:
        raise SubscriptionError('It is too late to skip that delivery.')
    SkippedDelivery.objects.get_or_create(subscription=subscription, date=date)
    for order in Order.objects.filter(subscription=subscription, delivery_date=date, status__in=Order.OPEN):
        orders.perform(order, subscription.buyer, 'cancel')


def _set_status(subscription, status):
    subscription.status = status
    if status == Subscription.Status.CANCELLED:
        subscription.cancelled_at = timezone.now()
    subscription.save()
    signals.subscription_changed.send(sender=Subscription, subscription=subscription)


def pause(subscription):
    if subscription.status != Subscription.Status.ACTIVE:
        raise SubscriptionError('Only an active subscription can be paused.')
    _set_status(subscription, Subscription.Status.PAUSED)


def resume(subscription):
    if subscription.status != Subscription.Status.PAUSED:
        raise SubscriptionError('Only a paused subscription can be resumed.')
    _set_status(subscription, Subscription.Status.ACTIVE)


def cancel(subscription):
    if subscription.status == Subscription.Status.CANCELLED:
        return
    _set_status(subscription, Subscription.Status.CANCELLED)


def _find_slot(subscription, date, now):
    """The slot generated from the rule on that date, or the next one at the same point that day with room."""
    start = _slot_start(subscription, date)
    point = subscription.rule.point
    slot = CollectionSlot.objects.filter(point=point, start=start).first()
    if slot is not None and slot.start > now and orders.slot_has_room(slot):
        return slot
    day_slots = CollectionSlot.objects.filter(point=point, start__gte=start, start__gt=now).order_by('start')
    for candidate in day_slots:
        if timezone.localtime(candidate.start).date() != date:
            break
        if orders.slot_has_room(candidate):
            return candidate
    return None


def generate_box_orders(now=None):
    """Create box orders for due deliveries in the next 7 days. Idempotent; run daily."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    end = today + timedelta(days=GENERATE_DAYS_AHEAD - 1)
    result = {'created': 0, 'missed': 0, 'skipped': 0}
    subscriptions = (Subscription.objects.filter(status=Subscription.Status.ACTIVE, box__status=Product.Status.LIVE)
                     .select_related('box__producer__user', 'rule__point', 'buyer'))
    points_ready = set()
    for subscription in subscriptions:
        point = subscription.rule.point
        if point.pk not in points_ready:
            producers.generate_slots(point=point, today=today, now=now)
            points_ready.add(point.pk)
        skipped = set(subscription.skipped.values_list('date', flat=True))
        for date in due_dates(subscription, today, end):
            if _slot_start(subscription, date) <= now:
                continue
            if date in skipped:
                result['skipped'] += 1
                continue
            if Order.objects.filter(subscription=subscription, delivery_date=date).exists() or \
                    MissedDelivery.objects.filter(subscription=subscription, date=date).exists():
                continue
            slot = _find_slot(subscription, date, now)
            if slot is None:
                missed = MissedDelivery.objects.create(subscription=subscription, date=date,
                                                       reason='Every collection slot that day was full.')
                signals.delivery_missed.send(sender=Subscription, subscription=subscription, missed=missed)
                result['missed'] += 1
                continue
            orders.create_box_order(subscription, slot, date)
            result['created'] += 1
    return result


def rule_in_use(rule):
    return Subscription.objects.filter(rule=rule).exclude(status=Subscription.Status.CANCELLED).exists()


def point_in_use(point):
    return Subscription.objects.filter(rule__point=point).exclude(status=Subscription.Status.CANCELLED).exists()
