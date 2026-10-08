from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from .services import get_producer


def producer_required(view):
    """Logged-in users with a producer profile; the profile is passed to the view as `producer`."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        producer = get_producer(request.user)
        if producer is None:
            messages.info(request, 'Set up your producer profile to start selling.')
            return redirect('producers:setup')
        return view(request, producer, *args, **kwargs)

    return wrapper
