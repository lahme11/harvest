"""Redirect helpers that never send users to another site."""
from django.shortcuts import resolve_url
from django.utils.http import url_has_allowed_host_and_scheme


def safe_next(request, fallback, *args):
    """The POSTed `next` URL if it points at this site, otherwise the fallback (a URL or URL name)."""
    target = request.POST.get('next') or request.GET.get('next')
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                                  require_https=request.is_secure()):
        return target
    return resolve_url(fallback, *args)
