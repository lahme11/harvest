import datetime as dt

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.catalogue import services as catalogue
from apps.core.urls_safety import safe_next
from apps.producers.decorators import producer_required
from apps.producers.models import CollectionSlot, Producer

from . import services
from .forms import QuantityForm, SlotChoiceForm
from .models import Order


@login_required
def basket(request):
    return render(request, 'orders/basket.html', {
        'groups': services.basket_groups(request.user),
        'limited': services.open_order_limit_reached(request.user),
    })


@require_POST
@login_required
def add(request, product_pk):
    product = catalogue.get_live_product(product_pk)
    if product is None:
        raise Http404
    form = QuantityForm(request.POST)
    quantity = form.cleaned_data['quantity'] if form.is_valid() else 1
    try:
        services.add_to_basket(request.user, product, max(quantity, 1))
    except services.OrderError as error:
        messages.error(request, str(error))
        return redirect(product.get_absolute_url())
    messages.success(request, f'{product.name} added to your basket.')
    return redirect(safe_next(request, 'orders:basket'))


@require_POST
@login_required
def update(request, product_pk):
    product = catalogue.get_product(product_pk)
    if product is None:
        raise Http404
    form = QuantityForm(request.POST)
    if form.is_valid():
        try:
            services.update_quantity(request.user, product, form.cleaned_data['quantity'])
        except services.OrderError as error:
            messages.error(request, str(error))
    return redirect('orders:basket')


@require_POST
@login_required
def remove(request, product_pk):
    product = catalogue.get_product(product_pk)
    if product is not None:
        services.remove_from_basket(request.user, product)
    return redirect('orders:basket')


@login_required
def checkout(request, producer_pk):
    producer = get_object_or_404(Producer, pk=producer_pk)
    group = services.basket_group_for(request.user, producer)
    if group is None or not group.can_checkout:
        messages.info(request, 'There is nothing from this producer in your basket to order.')
        return redirect('orders:basket')
    if request.method == 'POST':
        form = SlotChoiceForm(request.POST)
        slot = CollectionSlot.objects.filter(pk=form.data.get('slot'), point__producer=producer).first() \
            if form.is_valid() else None
        if slot is None:
            messages.error(request, 'Choose a collection slot.')
        else:
            try:
                services.reserve(request.user, producer, slot)
            except services.OrderError as error:
                messages.error(request, str(error))
            else:
                return redirect('orders:confirm', producer.pk, slot.pk)
    slots = services.available_slots(request.user, producer)
    return render(request, 'orders/checkout.html', {'producer': producer, 'group': group, 'slots': slots,
                                                    'limited': services.open_order_limit_reached(request.user)})


@login_required
def confirm(request, producer_pk, slot_pk):
    producer = get_object_or_404(Producer, pk=producer_pk)
    slot = get_object_or_404(CollectionSlot.objects.select_related('point'), pk=slot_pk, point__producer=producer)
    holds = services.active_holds(request.user, producer, slot)
    if request.method == 'POST':
        try:
            order = services.confirm(request.user, producer, slot)
        except services.OrderError as error:
            messages.error(request, str(error))
            return redirect('orders:checkout', producer.pk)
        messages.success(request, f'Order {order.number} placed. Pay {producer.name} when you collect.')
        return redirect(order.get_absolute_url())
    if not holds:
        messages.info(request, 'Your reservation has expired. Please choose a slot again.')
        return redirect('orders:checkout', producer.pk)
    expires_at = min(hold.expires_at for hold in holds)
    total = sum(hold.product.price * hold.quantity for hold in holds)
    return render(request, 'orders/confirm.html', {
        'producer': producer, 'slot': slot, 'holds': holds, 'total': total, 'expires_at': expires_at,
        'seconds_left': max(0, int((expires_at - timezone.now()).total_seconds())),
    })


@login_required
def detail(request, number):
    order = services.order_for_user(number, request.user)
    if order is None:
        raise Http404
    actions = [(name, services.TRANSITIONS[name].label) for name in services.allowed_actions(order, request.user)]
    return render(request, 'orders/detail.html', {
        'order': order, 'items': order.items.all(), 'events': order.events.select_related('actor'),
        'is_producer': order.producer.user_id == request.user.pk, 'actions': actions,
        'payment_choices': Order.Payment.choices,
    })


@require_POST
@login_required
def act(request, number):
    order = services.order_for_user(number, request.user)
    if order is None or request.user.is_staff and services._role(order, request.user) is None:
        raise Http404
    try:
        services.perform(order, request.user, request.POST.get('action', ''), reason=request.POST.get('reason', ''),
                         payment_method=request.POST.get('payment_method', ''))
    except services.OrderError as error:
        messages.error(request, str(error))
    else:
        order.refresh_from_db()
        messages.success(request, f'Order {order.number}: {order.get_status_display().lower()}.')
    return redirect(safe_next(request, order.get_absolute_url()))


@producer_required
def producer_orders(request, producer):
    status = request.GET.get('status', 'open')
    try:
        date = dt.date.fromisoformat(request.GET.get('date', ''))
    except ValueError:
        date = None
    orders = services.producer_orders(producer, status=status if status != 'all' else None, date=date)
    return render(request, 'orders/producer_orders.html', {
        'producer': producer, 'orders': orders, 'status': status, 'date': date,
        'statuses': [('open', 'Open'), *Order.Status.choices, ('all', 'All')],
    })


@producer_required
def pick_list(request, producer):
    try:
        date = dt.date.fromisoformat(request.GET.get('date', ''))
    except ValueError:
        date = timezone.localdate()
    return render(request, 'orders/pick_list.html', {'producer': producer, 'date': date,
                                                     **services.pick_list(producer, date)})


@login_required
def my_orders(request):
    orders = request.user.orders.select_related('producer', 'slot', 'point')
    return render(request, 'orders/my_orders.html', {'orders': orders})


@producer_required
def dashboard(request, producer):
    return render(request, 'orders/dashboard.html', {'producer': producer, **services.dashboard(producer)})
