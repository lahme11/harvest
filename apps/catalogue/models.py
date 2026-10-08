from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Prefetch, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from apps.core.choices import ALLERGEN_LABELS
from apps.producers.models import Producer

WHOLE_FOOD_CATEGORIES = ('vegetables', 'fruit', 'meat', 'fish', 'eggs')


class ProductQuerySet(models.QuerySet):
    def live(self):
        return self.filter(status=Product.Status.LIVE, producer__user__is_active=True)

    def in_season(self, month=None):
        month = month or timezone.localdate().month
        return self.filter(Q(season_months='') | Q(season_months__regex=rf'(^|,){month}(,|$)'))

    def for_cards(self):
        return self.select_related('producer').prefetch_related(
            Prefetch('photos', queryset=ProductPhoto.objects.order_by('-is_cover', 'position')))


class Product(models.Model):
    class Category(models.TextChoices):
        VEGETABLES = 'vegetables', 'Vegetables'
        FRUIT = 'fruit', 'Fruit'
        MEAT = 'meat', 'Meat'
        FISH = 'fish', 'Fish'
        DAIRY = 'dairy', 'Dairy'
        EGGS = 'eggs', 'Eggs'
        BAKERY = 'bakery', 'Bakery'
        PANTRY = 'pantry', 'Pantry'
        DRINKS = 'drinks', 'Drinks'

    class Unit(models.TextChoices):
        EACH = 'each', 'each'
        KG = 'kg', 'per kg'
        G500 = '500g', 'per 500 g'
        G250 = '250g', 'per 250 g'
        DOZEN = 'dozen', 'per dozen'
        HALF_DOZEN = 'half_dozen', 'per half dozen'
        LITRE = 'litre', 'per litre'
        BUNCH = 'bunch', 'per bunch'
        JAR = 'jar', 'per jar'
        BOX = 'box', 'per box'

    class Kind(models.TextChoices):
        STANDARD = 'standard', 'Product'
        BOX = 'box', 'Veg-box subscription'

    class Frequency(models.TextChoices):
        WEEKLY = 'weekly', 'Weekly'
        FORTNIGHTLY = 'fortnightly', 'Every two weeks'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        LIVE = 'live', 'Live'
        PAUSED = 'paused', 'Paused'
        ARCHIVED = 'archived', 'Archived'

    producer = models.ForeignKey(Producer, on_delete=models.CASCADE, related_name='products')
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=110, blank=True)
    category = models.CharField(max_length=12, choices=Category.choices)
    unit = models.CharField(max_length=12, choices=Unit.choices, default=Unit.EACH)
    price = models.DecimalField(max_digits=7, decimal_places=2,
                                validators=[MinValueValidator(0.10), MaxValueValidator(500)])
    stock = models.PositiveIntegerField(default=0, help_text='How many units you have to sell.')
    season_months = models.CharField(max_length=40, blank=True, help_text='Months in season; empty means all year.')
    description = models.TextField(blank=True)
    ingredients = models.TextField(blank=True,
                                   help_text='Exactly as on the label. Leave empty for a single whole food.')
    allergens = models.CharField(max_length=200, blank=True)
    organic = models.BooleanField('certified organic', default=False)
    barcode = models.CharField(max_length=14, blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.STANDARD)
    box_frequency = models.CharField(max_length=12, choices=Frequency.choices, blank=True)
    max_subscribers = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    nova_group = models.PositiveSmallIntegerField(null=True, blank=True)
    clean_score = models.PositiveSmallIntegerField(null=True, blank=True)
    grade = models.CharField(max_length=1, blank=True)
    analysis_json = models.JSONField(default=dict, blank=True)
    off_nova_group = models.PositiveSmallIntegerField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ['-published_at', '-created_at']
        indexes = [models.Index(fields=['status', 'category']), models.Index(fields=['status', 'nova_group'])]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)[:110] or 'product'
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('catalogue:detail', args=[self.pk, self.slug])

    @property
    def is_live(self):
        return self.status == self.Status.LIVE

    @property
    def is_box(self):
        return self.kind == self.Kind.BOX

    @property
    def is_sold_out(self):
        return self.is_live and not self.is_box and self.stock == 0

    @property
    def allergen_list(self):
        return [slug for slug in self.allergens.split(',') if slug]

    @property
    def allergen_labels(self):
        return [ALLERGEN_LABELS.get(slug, slug) for slug in self.allergen_list]

    @property
    def season_list(self):
        return [int(month) for month in self.season_months.split(',') if month]

    def in_season(self, month=None):
        month = month or timezone.localdate().month
        return not self.season_list or month in self.season_list

    @property
    def cover_photo(self):
        photos = list(self.photos.all())
        for photo in photos:
            if photo.is_cover:
                return photo
        return photos[0] if photos else None

    @property
    def reasons(self):
        return self.analysis_json.get('reasons', [])


class ProductPhoto(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='products/%Y/%m/')
    thumbnail = models.ImageField(upload_to='products/%Y/%m/')
    position = models.PositiveSmallIntegerField(default=0)
    is_cover = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['position', 'pk']

    def __str__(self):
        return f'Photo {self.position + 1} of {self.product}'
