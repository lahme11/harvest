from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.catalogue import services as catalogue
from apps.core.urls_safety import safe_next

from . import services
from .models import SavedSearch


@login_required
def favourites(request):
    return render(request, 'saved/favourites.html', {'favourites': services.favourites(request.user)})


@require_POST
@login_required
def toggle(request, product_pk):
    product = catalogue.get_product(product_pk)
    if product is None or not catalogue.is_visible_to(product, request.user):
        raise Http404
    saved = services.toggle_favourite(request.user, product)
    messages.success(request, f'{product.name} {"saved" if saved else "removed from your saved food"}.')
    return redirect(safe_next(request, product.get_absolute_url()))


@login_required
def searches(request):
    return render(request, 'saved/searches.html', {'searches': request.user.saved_searches.all()})


@require_POST
@login_required
def save_search(request):
    search = services.save_search(request.user, request.POST.get('name', ''), request.POST.get('query_string', ''))
    messages.success(request, f'Saved "{search.name}". We will email you when something new matches.')
    return redirect('saved:searches')


@require_POST
@login_required
def delete_search(request, pk):
    get_object_or_404(SavedSearch, pk=pk, user=request.user).delete()
    messages.success(request, 'Saved search deleted.')
    return redirect('saved:searches')
