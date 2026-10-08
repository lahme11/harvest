import datetime as dt

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.catalogue import services as catalogue
from apps.producers.decorators import producer_required
from apps.producers.models import SlotRule

from . import services
from .models import Subscription


@require_POST
@login_required
def subscribe(request, box_pk):
    box = catalogue.get_live_product(box_pk)
    if box is None:
        raise Http404
    rule = SlotRule.objects.filter(pk=request.POST.get('rule'), point__producer=box.producer).first()
    if rule is None:
        messages.error(request, 'Choose a collection time.')
        return redirect(box.get_absolute_url())
    try:
        services.subscribe(request.user, box, rule)
    except services.SubscriptionError as error:
        messages.error(request, str(error))
        return redirect(box.get_absolute_url())
    messages.success(request, f'You are subscribed to {box.name}.')
    return redirect('subscriptions:mine')


@login_required
def mine(request):
    subscriptions = (request.user.subscriptions.exclude(status=Subscription.Status.CANCELLED)
                     .select_related('box__producer', 'rule__point'))
    rows = [(subscription, services.upcoming(subscription)) for subscription in subscriptions]
    return render(request, 'subscriptions/mine.html', {'rows': rows})


def _own(request, pk):
    return get_object_or_404(Subscription, pk=pk, buyer=request.user)


@require_POST
@login_required
def control(request, pk, action):
    subscription = _own(request, pk)
    try:
        if action == 'skip':
            services.skip(subscription, dt.date.fromisoformat(request.POST.get('date', '')))
            messages.success(request, 'That delivery is skipped.')
        else:
            {'pause': services.pause, 'resume': services.resume, 'cancel': services.cancel}[action](subscription)
            messages.success(request, f'Subscription {subscription.get_status_display().lower()}.')
    except (services.SubscriptionError, ValueError) as error:
        messages.error(request, str(error) or 'That is not possible.')
    return redirect('subscriptions:mine')


@producer_required
def producer(request, producer):
    subscriptions = (Subscription.objects.filter(box__producer=producer)
                     .exclude(status=Subscription.Status.CANCELLED).select_related('buyer', 'box', 'rule__point'))
    return render(request, 'subscriptions/producer.html', {'producer': producer, 'subscriptions': subscriptions})
