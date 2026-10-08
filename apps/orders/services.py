"""The orders app's public interface: basket, stock holds, checkout and the order lifecycle."""
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.catalogue import services as catalogue
from apps.catalogue.models import Product
from apps.producers import services as producers
from apps.producers.models import CollectionSlot

from . import signals
from .models import BasketItem, Order, OrderEvent, OrderItem, StockHold


class OrderError(Exception):
    """An order change that breaks a rule, e.g. reserving more than is in stock."""


@dataclass
class BasketLine:
    item: BasketItem
    product: Product
    quantity: int
    line_total: Decimal
    available: int
    problem: str = ''


@dataclass
class BasketGroup:
    producer: object
    lines: list = field(default_factory=list)

    @property
    def subtotal(self):
        return sum((line.line_total for line in self.lines if not line.problem), Decimal('0.00'))

    @property
    def can_checkout(self):
        return any(not line.problem for line in self.lines)


def held_quantity(product, exclude_user=None, now=None):
    """Units of a product other buyers are holding at checkout right now."""
    holds = StockHold.objects.filter(product=product, expires_at__gt=now or timezone.now())
    if exclude_user is not None:
        holds = holds.exclude(user=exclude_user)
    return holds.aggregate(total=Sum('quantity'))['total'] or 0


def _check_buyable(user, product):
    if product is None or not product.is_live:
        raise OrderError('That product is not available.')
    if product.is_box:
        raise OrderError('Veg boxes are subscribed to from their page, not added to the basket.')
    if product.producer.user_id == user.pk:
        raise OrderError("You can't order your own products.")


def add_to_basket(user, product, quantity=1):
    _check_buyable(user, product)
    if quantity < 1:
        raise OrderError('Choose at least one.')
    item = BasketItem.objects.filter(user=user, product=product).first()
    wanted = quantity + (item.quantity if item else 0)
    available = catalogue.available_stock(product, exclude_user=user)
    if wanted > available:
        raise OrderError(f'Only {available} available of {product.name}.' if available else
                         f'{product.name} is sold out.')
    if item:
        item.quantity = wanted
        item.save(update_fields=['quantity'])
        return item
    return BasketItem.objects.create(user=user, product=product, quantity=quantity)


def update_quantity(user, product, quantity):
    item = BasketItem.objects.filter(user=user, product=product).first()
    if item is None:
        raise OrderError('That product is not in your basket.')
    if quantity <= 0:
        item.delete()
        return None
    available = catalogue.available_stock(product, exclude_user=user)
    if quantity > available:
        raise OrderError(f'Only {available} available of {product.name}.')
    item.quantity = quantity
    item.save(update_fields=['quantity'])
    return item


def remove_from_basket(user, product):
    BasketItem.objects.filter(user=user, product=product).delete()


def basket_count(user):
    if not user.is_authenticated:
        return 0
    return BasketItem.objects.filter(user=user).aggregate(total=Sum('quantity'))['total'] or 0


def basket_groups(user):
    """The basket grouped by producer, each line checked against what is still available."""
    groups = {}
    items = BasketItem.objects.filter(user=user).select_related('product__producer__user')
    for item in items:
        product = item.product
        available = catalogue.available_stock(product, exclude_user=user)
        problem = ''
        if not product.is_live or product.is_box:
            problem = 'No longer available'
        elif available == 0:
            problem = 'Sold out'
        elif item.quantity > available:
            problem = f'Only {available} left'
        group = groups.setdefault(product.producer_id, BasketGroup(producer=product.producer))
        group.lines.append(BasketLine(item=item, product=product, quantity=item.quantity,
                                      line_total=product.price * item.quantity, available=available,
                                      problem=problem))
    return list(groups.values())


def basket_group_for(user, producer):
    return next((group for group in basket_groups(user) if group.producer.pk == producer.pk), None)


def slot_bookings(slot, exclude_user=None, now=None):
    """Orders using the slot plus other buyers currently holding it at checkout."""
    orders = Order.objects.filter(slot=slot, status__in=Order.HOLDS_SLOT).count()
    holds = StockHold.objects.filter(slot=slot, expires_at__gt=now or timezone.now())
    if exclude_user is not None:
        holds = holds.exclude(user=exclude_user)
    return orders + holds.values('user').distinct().count()


def slot_has_room(slot, exclude_user=None):
    return slot_bookings(slot, exclude_user) < slot.capacity


def available_slots(user, producer):
    return [slot for slot in producers.bookable_slots(producer) if slot_has_room(slot, exclude_user=user)]


def open_order_limit_reached(user, now=None):
    """Buyers with NO_SHOW_LIMIT no-shows in NO_SHOW_WINDOW_DAYS may have only one open order at a time."""
    now = now or timezone.now()
    window_start = now - timedelta(days=settings.NO_SHOW_WINDOW_DAYS)
    recent = Order.objects.filter(buyer=user, status=Order.Status.NO_SHOW, no_show_at__gte=window_start).count()
    if recent < settings.NO_SHOW_LIMIT:
        return False
    return Order.objects.filter(buyer=user, status__in=Order.OPEN).exists()


def _lines_for(user, producer):
    group = basket_group_for(user, producer)
    lines = [line for line in group.lines if not line.problem] if group else []
    if not lines:
        if group and group.lines:
            details = '; '.join(f'{line.product.name}: {line.problem.lower()}' for line in group.lines)
            raise OrderError(f'Nothing in your basket from {producer.name} can be ordered right now ({details}).')
        raise OrderError('There is nothing from this producer in your basket that can be ordered.')
    return lines


def _check_slot(user, producer, slot):
    if slot.point.producer_id != producer.pk:
        raise OrderError('That collection slot belongs to another producer.')
    if slot not in producers.bookable_slots(producer):
        raise OrderError('That collection slot is no longer taking orders. Please choose another.')
    if not slot_has_room(slot, exclude_user=user):
        raise OrderError('That collection slot is full. Please choose another.')


@transaction.atomic
def reserve(user, producer, slot):
    """Hold the basket's items from this producer for STOCK_HOLD_MINUTES while the buyer confirms."""
    if open_order_limit_reached(user):
        raise OrderError('After two missed collections you can have one open order at a time. '
                         'Collect your current order first.')
    lines = _lines_for(user, producer)
    slot = CollectionSlot.objects.select_for_update().select_related('point').get(pk=slot.pk)
    StockHold.objects.filter(user=user, product__producer=producer).delete()
    _check_slot(user, producer, slot)
    locked = {p.pk: p for p in Product.objects.select_for_update().filter(pk__in=[l.product.pk for l in lines])}
    expires_at = timezone.now() + timedelta(minutes=settings.STOCK_HOLD_MINUTES)
    holds = []
    for line in lines:
        product = locked[line.product.pk]
        available = product.stock - held_quantity(product, exclude_user=user)
        if line.quantity > available:
            raise OrderError(f'Only {max(available, 0)} available of {product.name} right now.')
        holds.append(StockHold.objects.create(user=user, product=product, slot=slot, quantity=line.quantity,
                                              expires_at=expires_at))
    return holds


def active_holds(user, producer, slot):
    return list(StockHold.objects.filter(user=user, product__producer=producer, slot=slot,
                                         expires_at__gt=timezone.now()).select_related('product'))


def next_order_number(year):
    prefix = f'HV-{year}-'
    last = Order.objects.filter(number__startswith=prefix).order_by('-number').values_list('number', flat=True).first()
    sequence = int(last[len(prefix):]) + 1 if last else 1
    return f'{prefix}{sequence:06d}'


def record_event(order, actor, from_status, to_status, note=''):
    return OrderEvent.objects.create(order=order, actor=actor, from_status=from_status, to_status=to_status,
                                     note=note)


@transaction.atomic
def confirm(user, producer, slot):
    """Turn a live reservation into an order: take the stock, copy the prices, empty those basket lines."""
    holds = active_holds(user, producer, slot)
    if not holds:
        raise OrderError('Your reservation has expired. Please reserve a collection slot again.')
    if open_order_limit_reached(user):
        raise OrderError('After two missed collections you can have one open order at a time.')
    slot = CollectionSlot.objects.select_for_update().select_related('point').get(pk=slot.pk)
    _check_slot(user, producer, slot)
    held = {hold.product_id: hold.quantity for hold in holds}
    lines = [line for line in _lines_for(user, producer) if line.product.pk in held]
    if len(lines) != len(holds) or any(held[line.product.pk] != line.quantity for line in lines):
        raise OrderError('Your basket changed since you reserved. Please reserve a collection slot again.')
    locked = {p.pk: p for p in Product.objects.select_for_update().filter(pk__in=held)}
    order = Order.objects.create(number=next_order_number(timezone.localdate().year), buyer=user, producer=producer,
                                 slot=slot, point=slot.point, total=Decimal('0.00'))
    total = Decimal('0.00')
    for line in lines:
        product = locked[line.product.pk]
        if product.stock - held_quantity(product, exclude_user=user) < line.quantity:
            raise OrderError(f'Sorry, {product.name} sold out while you were checking out.')
        catalogue.decrement_stock(product, line.quantity)
        line_total = product.price * line.quantity
        OrderItem.objects.create(order=order, product=product, name=product.name, unit=product.get_unit_display(),
                                 unit_price=product.price, quantity=line.quantity, line_total=line_total)
        total += line_total
    order.total = total
    order.save(update_fields=['total'])
    StockHold.objects.filter(pk__in=[hold.pk for hold in holds]).delete()
    BasketItem.objects.filter(user=user, product_id__in=held).delete()
    record_event(order, user, '', Order.Status.PENDING)
    signals.order_placed.send(sender=Order, order=order)
    return order


def release_expired_holds(now=None):
    deleted, _ = StockHold.objects.filter(expires_at__lte=now or timezone.now()).delete()
    return deleted


def order_for_user(number, user):
    """An order the user may see (as buyer or as the producer), or None."""
    order = Order.objects.select_related('producer__user', 'slot', 'point', 'buyer').filter(number=number).first()
    if order is None or not user.is_authenticated:
        return None
    if order.buyer_id == user.pk or order.producer.user_id == user.pk or user.is_staff:
        return order
    return None


def point_in_use(point):
    return Order.objects.filter(point=point).exists()


def slot_in_use(slot):
    return Order.objects.filter(slot=slot).exists() or StockHold.objects.filter(slot=slot).exists()


@dataclass(frozen=True)
class Transition:
    sources: tuple
    target: str
    actor: str
    label: str


TRANSITIONS = {
    'accept': Transition((Order.Status.PENDING,), Order.Status.ACCEPTED, 'producer', 'Accept'),
    'reject': Transition((Order.Status.PENDING,), Order.Status.REJECTED, 'producer', 'Reject'),
    'cancel': Transition((Order.Status.PENDING, Order.Status.ACCEPTED), Order.Status.CANCELLED, 'buyer',
                         'Cancel order'),
    'mark_ready': Transition((Order.Status.ACCEPTED,), Order.Status.READY, 'producer', 'Mark ready to collect'),
    'collect': Transition((Order.Status.READY,), Order.Status.COLLECTED, 'producer', 'Mark collected'),
    'no_show': Transition((Order.Status.READY,), Order.Status.NO_SHOW, 'producer', 'Not collected'),
}

RETURNS_STOCK = ('reject', 'cancel')


def _role(order, user):
    if not user.is_authenticated:
        return None
    if order.producer.user_id == user.pk:
        return 'producer'
    if order.buyer_id == user.pk:
        return 'buyer'
    return None


def _time_allows(order, action, now):
    if action == 'accept':
        return now < order.slot.start
    if action == 'cancel':
        return now < order.slot.start - timedelta(hours=order.point.cutoff_hours)
    if action == 'no_show':
        return now >= order.slot.end + timedelta(hours=settings.NO_SHOW_GRACE_HOURS)
    return True


def allowed_actions(order, user, now=None):
    """The actions this user may take on the order right now, in display order."""
    now = now or timezone.now()
    role = _role(order, user)
    return [name for name, transition in TRANSITIONS.items()
            if role == transition.actor and order.status in transition.sources and _time_allows(order, name, now)]


def _return_stock(order):
    if order.is_box:
        return
    for item in order.items.select_related('product'):
        if item.product is not None:
            catalogue.return_stock(item.product, item.quantity)


def _apply(order, actor, transition_name, note=''):
    transition = TRANSITIONS[transition_name]
    from_status = order.status
    now = timezone.now()
    order.status = transition.target
    stamp = {'accept': 'accepted_at', 'mark_ready': 'ready_at', 'collect': 'collected_at',
             'no_show': 'no_show_at'}.get(transition_name)
    if stamp:
        setattr(order, stamp, now)
    if transition.target not in Order.OPEN:
        order.closed_at = now
    order.save()
    if transition_name in RETURNS_STOCK:
        _return_stock(order)
    record_event(order, actor, from_status, transition.target, note)
    signals.order_status_changed.send(sender=Order, order=order, from_status=from_status,
                                      to_status=transition.target, actor=actor)
    return order


@transaction.atomic
def perform(order, user, action, reason='', payment_method=''):
    """Apply one lifecycle action for a user, checking who may do it and when."""
    Order.objects.select_for_update().filter(pk=order.pk).first()
    order.refresh_from_db()
    if action not in allowed_actions(order, user):
        raise OrderError('That is not possible for this order right now.')
    note = ''
    if action == 'reject':
        reason = (reason or '').strip()
        if not reason:
            raise OrderError('Tell the buyer why you are rejecting the order.')
        order.reject_reason = reason
        note = reason
    if action == 'collect':
        if payment_method not in Order.Payment.values:
            raise OrderError('Record how the buyer paid.')
        order.payment_method = payment_method
        note = f'Paid by {Order.Payment(payment_method).label.lower()}'
    return _apply(order, user, action, note)


def expire_pending(now=None):
    """Cancel pending orders the producer didn't accept within ORDER_ACCEPT_HOURS or before the slot started."""
    now = now or timezone.now()
    deadline = now - timedelta(hours=settings.ORDER_ACCEPT_HOURS)
    stale = Order.objects.filter(status=Order.Status.PENDING).filter(
        Q(created_at__lte=deadline) | Q(slot__start__lte=now))
    expired = 0
    for order in stale.select_related('slot', 'point', 'producer'):
        with transaction.atomic():
            from_status = order.status
            order.status = Order.Status.CANCELLED
            order.closed_at = now
            order.save()
            _return_stock(order)
            record_event(order, None, from_status, order.status,
                         'Cancelled automatically: not accepted in time.')
            signals.order_status_changed.send(sender=Order, order=order, from_status=from_status,
                                              to_status=order.status, actor=None)
        expired += 1
    return expired


def pick_list(producer, date):
    """What to pack for a day: totals per product, then each accepted or ready order."""
    orders = (Order.objects.filter(producer=producer, status__in=(Order.Status.ACCEPTED, Order.Status.READY))
              .select_related('buyer', 'slot').prefetch_related('items').order_by('slot__start', 'number'))
    orders = [order for order in orders if timezone.localtime(order.slot.start).date() == date]
    totals = {}
    for order in orders:
        for item in order.items.all():
            key = (item.name, item.unit)
            totals[key] = totals.get(key, 0) + item.quantity
    return {'products': sorted((name, unit, qty) for (name, unit), qty in totals.items()), 'orders': orders}


def producer_orders(producer, status=None, date=None):
    orders = Order.objects.filter(producer=producer).select_related('buyer', 'slot', 'point')
    if status == 'open':
        orders = orders.filter(status__in=Order.OPEN)
    elif status:
        orders = orders.filter(status=status)
    if date:
        orders = [order for order in orders.order_by('slot__start')
                  if timezone.localtime(order.slot.start).date() == date]
        return orders
    return orders.order_by('slot__start')


@transaction.atomic
def create_box_order(subscription, slot, delivery_date):
    """A pending order for one veg box, created by the subscription schedule."""
    box = subscription.box
    order = Order.objects.create(number=next_order_number(delivery_date.year), buyer=subscription.buyer,
                                 producer=box.producer, slot=slot, point=slot.point, total=box.price, is_box=True,
                                 subscription=subscription, delivery_date=delivery_date)
    OrderItem.objects.create(order=order, product=box, name=box.name, unit=box.get_unit_display(),
                             unit_price=box.price, quantity=1, line_total=box.price)
    record_event(order, None, '', Order.Status.PENDING, 'Created from a veg-box subscription.')
    signals.order_placed.send(sender=Order, order=order)
    return order


def has_collected_order(user, producer):
    return Order.objects.filter(buyer=user, producer=producer, status=Order.Status.COLLECTED).exists()


def producer_sales(producer, since):
    """(total of collected orders since `since`, top 5 [(product name, quantity)])."""
    collected = Order.objects.filter(producer=producer, status=Order.Status.COLLECTED, collected_at__gte=since)
    total = collected.aggregate(total=Sum('total'))['total'] or Decimal('0.00')
    top = (OrderItem.objects.filter(order__in=collected).values('name').annotate(quantity=Sum('quantity'))
           .order_by('-quantity', 'name')[:5])
    return total, [(row['name'], row['quantity']) for row in top]


def dashboard(producer, now=None):
    """The numbers on a producer's dashboard."""
    now = now or timezone.now()
    slots = (CollectionSlot.objects.filter(point__producer=producer, start__gt=now, start__lte=now + timedelta(days=7))
             .select_related('point').order_by('start'))
    booked = {row['slot']: row['count'] for row in Order.objects.filter(slot__in=slots, status__in=Order.HOLDS_SLOT)
              .values('slot').annotate(count=Count('pk'))}
    counts = {status: 0 for status in Order.OPEN}
    for row in Order.objects.filter(producer=producer, status__in=Order.OPEN).values('status').annotate(
            count=Count('pk')):
        counts[row['status']] = row['count']
    total, top = producer_sales(producer, now - timedelta(days=30))
    low_stock = Product.objects.filter(producer=producer, status=Product.Status.LIVE, kind=Product.Kind.STANDARD,
                                       stock__lte=settings.LOW_STOCK_THRESHOLD).order_by('stock', 'name')
    return {
        'slots_next_7_days': [(slot, booked.get(slot.pk, 0)) for slot in slots],
        'open_orders': {str(status): count for status, count in counts.items()},
        'low_stock': list(low_stock), 'sales_30_days': total, 'top_products': top,
    }
