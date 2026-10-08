from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.analysis import openfoodfacts
from apps.core.choices import MONTH_LABELS, MONTHS
from apps.producers.decorators import producer_required
from apps.producers.models import SlotRule

from . import services
from .forms import PhotoUploadForm, PriceForm, ProductForm, StockForm
from .models import Product, ProductPhoto


def _own_product(producer, pk):
    return get_object_or_404(Product, pk=pk, producer=producer)


@producer_required
def mine(request, producer):
    products = services.products_for(producer)
    return render(request, 'catalogue/mine.html', {
        'producer': producer, 'products': products, 'limit': services.limit_for(producer),
        'live_count': services.live_count(producer),
    })


@producer_required
def product_form(request, producer, pk=None):
    product = _own_product(producer, pk) if pk else None
    form = ProductForm(request.POST or None, instance=product, producer=producer)
    if request.method == 'POST' and form.is_valid():
        try:
            saved = services.save_product(producer, form.cleaned_data, product=product)
        except services.ProductError as error:
            form.add_error(None, str(error))
        else:
            if product:
                messages.success(request, f'{saved.name} has been saved.')
                return redirect('catalogue:mine')
            messages.success(request, f'{saved.name} has been created as a draft. Add photos, then publish it.')
            return redirect('catalogue:photos', saved.pk)
    return render(request, 'catalogue/product_form.html', {'form': form, 'product': product, 'producer': producer})


@require_POST
@producer_required
def publish(request, producer, pk):
    product = _own_product(producer, pk)
    try:
        services.publish(product)
    except services.ProductError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f'{product.name} is live.')
    return redirect('catalogue:mine')


@require_POST
@producer_required
def pause(request, producer, pk):
    product = _own_product(producer, pk)
    services.pause(product)
    messages.success(request, f'{product.name} is paused.')
    return redirect('catalogue:mine')


@require_POST
@producer_required
def archive(request, producer, pk):
    product = _own_product(producer, pk)
    services.archive(product)
    messages.success(request, f'{product.name} has been archived.')
    return redirect('catalogue:mine')


@require_POST
@producer_required
def stock(request, producer, pk):
    product = _own_product(producer, pk)
    form = StockForm(request.POST)
    if form.is_valid():
        services.set_stock(product, form.cleaned_data['stock'])
        messages.success(request, f'Stock for {product.name} is now {product.stock}.')
    else:
        messages.error(request, 'Enter a whole number of 0 or more.')
    return redirect('catalogue:mine')


@require_POST
@producer_required
def price(request, producer, pk):
    product = _own_product(producer, pk)
    form = PriceForm(request.POST)
    if form.is_valid():
        services.change_price(product, form.cleaned_data['price'])
        messages.success(request, f'{product.name} now costs €{product.price}.')
    else:
        messages.error(request, 'Enter a price between €0.10 and €500.')
    return redirect('catalogue:mine')


@producer_required
def photos(request, producer, pk):
    product = _own_product(producer, pk)
    form = PhotoUploadForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        try:
            services.add_photos(product, form.cleaned_data['photos'])
        except services.ProductError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, 'Photos added.')
        return redirect('catalogue:photos', product.pk)
    return render(request, 'catalogue/photos.html', {'product': product, 'form': form})


def _own_photo(producer, pk):
    return get_object_or_404(ProductPhoto.objects.select_related('product'), pk=pk, product__producer=producer)


@require_POST
@producer_required
def photo_cover(request, producer, pk):
    photo = _own_photo(producer, pk)
    services.set_cover(photo)
    return redirect('catalogue:photos', photo.product_id)


@require_POST
@producer_required
def photo_delete(request, producer, pk):
    photo = _own_photo(producer, pk)
    product_id = photo.product_id
    services.delete_photo(photo)
    return redirect('catalogue:photos', product_id)


@require_GET
@producer_required
def barcode(request, producer):
    try:
        found = openfoodfacts.lookup(request.GET.get('code', ''))
    except openfoodfacts.InvalidBarcode:
        return JsonResponse({'error': 'That is not a valid EAN-8 or EAN-13 barcode.'}, status=400)
    if found is None:
        return JsonResponse({'found': False})
    return JsonResponse({'found': True, 'name': found.name, 'ingredients': found.ingredients,
                         'allergens': found.allergens, 'nova_group': found.nova_group})


def detail(request, pk, slug):
    product = services.get_product(pk)
    if product is None or not services.is_visible_to(product, request.user):
        raise Http404
    if slug != product.slug:
        return redirect(product.get_absolute_url(), permanent=True)
    services.record_view(product, request.user)
    is_owner = request.user.is_authenticated and request.user.pk == product.producer.user_id
    return render(request, 'catalogue/detail.html', {
        'product': product, 'is_owner': is_owner,
        'hints': services.allergen_hints(product) if is_owner else [],
        'photos': product.photos.order_by('-is_cover', 'position'),
        'is_favourite': request.user.is_authenticated and product.favourited_by.filter(user=request.user).exists(),
        'box_rules': (SlotRule.objects.filter(point__producer=product.producer, active=True, point__active=True)
                      .select_related('point') if product.is_box else []),
    })


def browse(request):
    form, products = services.search_from_params(request.GET)
    page = Paginator(products, 20).get_page(request.GET.get('page'))
    return render(request, 'catalogue/browse.html', {'form': form, 'page_obj': page})


def api(request):
    _, products = services.search_from_params(request.GET)
    page = Paginator(products, 20).get_page(request.GET.get('page'))
    return JsonResponse({
        'count': page.paginator.count, 'page': page.number, 'num_pages': page.paginator.num_pages,
        'results': [{
            'id': product.pk, 'name': product.name, 'producer': product.producer.name,
            'county': product.producer.get_county_display(), 'category': product.category,
            'price': str(product.price), 'unit': product.get_unit_display(), 'nova_group': product.nova_group,
            'clean_score': product.clean_score, 'grade': product.grade, 'organic': product.organic,
            'sold_out': product.is_sold_out, 'url': product.get_absolute_url(),
        } for product in page],
    })


def season(request):
    try:
        month = int(request.GET.get('month', ''))
    except ValueError:
        month = None
    if month not in MONTH_LABELS:
        month = timezone.localdate().month
    return render(request, 'catalogue/season.html', {
        'month': month, 'month_name': MONTH_LABELS[month], 'groups': services.in_season_by_category(month),
        'months': MONTHS,
    })
