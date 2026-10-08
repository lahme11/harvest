from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import services
from .decorators import producer_required
from .forms import (CollectionPointForm, DirectoryFilterForm, FarmApplicationForm, ProducerForm, SlotRuleForm,
                    VerifiedProducerForm)
from .models import CollectionPoint, Producer, Review, SlotRule


@login_required
def setup(request):
    if services.get_producer(request.user):
        return redirect('producers:edit')
    form = ProducerForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        services.create_producer(request.user, **form.cleaned_data)
        messages.success(request, 'Your producer profile is ready. Next, add where buyers collect their orders.')
        return redirect('producers:points')
    return render(request, 'producers/setup.html', {'form': form})


@producer_required
def edit(request, producer):
    form_class = VerifiedProducerForm if producer.verified else ProducerForm
    form = form_class(request.POST or None, instance=producer)
    if request.method == 'POST' and form.is_valid():
        updated = form.save(commit=False)
        updated.slug = services.unique_slug(updated.name, exclude_pk=producer.pk)
        updated.save()
        messages.success(request, 'Your profile has been saved.')
        return redirect('producers:edit')
    return render(request, 'producers/edit.html', {'form': form, 'producer': producer})


@producer_required
def apply(request, producer):
    pending = services.pending_application(producer)
    form = FarmApplicationForm(request.POST or None, initial={'farm_name': producer.name, 'county': producer.county})
    if request.method == 'POST' and not producer.verified and not pending and form.is_valid():
        try:
            services.apply_for_verification(producer, **form.cleaned_data)
        except services.ProducerError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, 'Thanks! Your application has been sent to the Harvest team.')
        return redirect('producers:apply')
    latest = producer.applications.first()
    return render(request, 'producers/apply.html',
                  {'form': form, 'producer': producer, 'pending': pending, 'latest': latest})


@producer_required
def points(request, producer):
    collection_points = producer.points.prefetch_related('rules')
    return render(request, 'producers/points.html', {'producer': producer, 'points': collection_points})


@producer_required
def point_form(request, producer, pk=None):
    point = get_object_or_404(CollectionPoint, pk=pk, producer=producer) if pk else None
    form = CollectionPointForm(request.POST or None, instance=point, initial={'county': producer.county})
    if request.method == 'POST' and form.is_valid():
        saved = form.save(commit=False)
        saved.producer = producer
        saved.save()
        services.generate_slots(point=saved)
        messages.success(request, 'Collection point saved.')
        return redirect('producers:points')
    return render(request, 'producers/point_form.html', {'form': form, 'point': point})


@require_POST
@producer_required
def point_delete(request, producer, pk):
    point = get_object_or_404(CollectionPoint, pk=pk, producer=producer)
    try:
        services.delete_point(point)
    except services.ProducerError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, 'Collection point deleted.')
    return redirect('producers:points')


@producer_required
def rule_form(request, producer, point_pk=None, pk=None):
    rule = get_object_or_404(SlotRule, pk=pk, point__producer=producer) if pk else None
    point = rule.point if rule else get_object_or_404(CollectionPoint, pk=point_pk, producer=producer)
    form = SlotRuleForm(request.POST or None, instance=rule)
    if request.method == 'POST' and form.is_valid():
        saved = form.save(commit=False)
        saved.point = point
        saved.save()
        services.regenerate_rule_slots(saved)
        messages.success(request, 'Collection times saved.')
        return redirect('producers:points')
    return render(request, 'producers/rule_form.html', {'form': form, 'point': point, 'rule': rule})


@require_POST
@producer_required
def rule_delete(request, producer, pk):
    rule = get_object_or_404(SlotRule, pk=pk, point__producer=producer)
    try:
        services.delete_rule(rule)
    except services.ProducerError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, 'Collection times deleted.')
    return redirect('producers:points')


def directory(request):
    form = DirectoryFilterForm(request.GET or None)
    producers = Producer.objects.verified().annotate(avg_rating=Avg('reviews__rating'), review_count=Count('reviews'))
    if form.is_valid() and form.cleaned_data['county']:
        producers = producers.filter(county=form.cleaned_data['county'])
    page = Paginator(producers, 24).get_page(request.GET.get('page'))
    return render(request, 'producers/directory.html', {'form': form, 'page_obj': page})


def detail(request, slug):
    producer = get_object_or_404(Producer, slug=slug, verified=True)
    average, count = services.rating_summary(producer)
    own_review = producer.reviews.filter(author=request.user).first() if request.user.is_authenticated else None
    return render(request, 'producers/detail.html', {
        'producer': producer, 'average': average, 'review_count': count,
        'reviews': producer.reviews.select_related('author'),
        'can_review': services.can_review(request.user, producer), 'own_review': own_review,
        'is_owner': request.user.is_authenticated and producer.user_id == request.user.pk,
    })


@require_POST
@login_required
def review(request, slug):
    producer = get_object_or_404(Producer, slug=slug, verified=True)
    try:
        rating = int(request.POST.get('rating', ''))
    except ValueError:
        rating = 0
    try:
        services.save_review(request.user, producer, rating, request.POST.get('text', ''))
    except services.ProducerError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, 'Thanks for your review.')
    return redirect(producer.get_absolute_url())


@require_POST
@producer_required
def review_reply(request, producer, pk):
    review_obj = get_object_or_404(Review, pk=pk, producer=producer)
    try:
        services.reply(review_obj, request.user, request.POST.get('reply', ''))
    except services.ProducerError as error:
        messages.error(request, str(error))
    return redirect(producer.get_absolute_url())
