from django.contrib import messages as flash
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render

from apps.orders.services import order_for_user

from . import services


@login_required
def inbox(request):
    return render(request, 'messaging/inbox.html', {'conversations': services.inbox(request.user)})


@login_required
def thread(request, number):
    order = order_for_user(number, request.user)
    if order is None or request.user.pk not in services.participants(order):
        raise Http404
    if request.method == 'POST':
        try:
            services.post_message(order, request.user, request.POST.get('body', ''))
        except services.MessagingError as error:
            flash.error(request, str(error))
        return redirect('messaging:thread', order.number)
    services.mark_read(order, request.user)
    return render(request, 'messaging/thread.html', {
        'order': order, 'thread': order.messages.select_related('sender'),
        'other': order.producer.name if request.user.pk == order.buyer_id else order.buyer.get_username(),
    })
