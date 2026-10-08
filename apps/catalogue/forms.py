from django import forms

from apps.core.choices import ALLERGENS, MONTHS
from apps.core.mixins import BootstrapFormMixin

from . import services
from .models import Product

VERIFIED_ONLY = ('organic', 'kind', 'box_frequency', 'max_subscribers')


class ProductForm(BootstrapFormMixin, forms.ModelForm):
    allergens = forms.MultipleChoiceField(choices=ALLERGENS, required=False, widget=forms.CheckboxSelectMultiple,
                                          help_text='Tick every one of the 14 allergens the product contains.')
    season_months = forms.TypedMultipleChoiceField(
        choices=MONTHS, coerce=int, required=False, widget=forms.CheckboxSelectMultiple,
        label='In season', help_text='Leave all unticked if it is available all year.')
    off_nova_group = forms.IntegerField(required=False, widget=forms.HiddenInput, min_value=1, max_value=4)

    class Meta:
        model = Product
        fields = ('name', 'category', 'unit', 'price', 'stock', 'description', 'ingredients', 'barcode', 'organic',
                  'kind', 'box_frequency', 'max_subscribers')
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'ingredients': forms.Textarea(attrs={'rows': 3, 'placeholder': 'e.g. wheat flour, water, sea salt'}),
            'barcode': forms.TextInput(attrs={'inputmode': 'numeric', 'placeholder': 'Optional, e.g. 5000159484695'}),
        }

    def __init__(self, *args, producer, **kwargs):
        self.producer = producer
        instance = kwargs.get('instance')
        if instance is not None:
            kwargs.setdefault('initial', {})
            kwargs['initial'].update({'allergens': instance.allergen_list, 'season_months': instance.season_list,
                                      'off_nova_group': instance.off_nova_group})
        super().__init__(*args, **kwargs)
        if not producer.verified:
            for name in VERIFIED_ONLY:
                self.fields.pop(name)

    def clean(self):
        cleaned = super().clean()
        for field, message in services.rule_errors(self.producer, cleaned).items():
            if field in self.fields and field not in self.errors:
                self.add_error(field, message)
        return cleaned


class StockForm(forms.Form):
    stock = forms.IntegerField(min_value=0, max_value=100000)


class PriceForm(forms.Form):
    price = forms.DecimalField(min_value=0.10, max_value=500, decimal_places=2)


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """A file field that accepts several files at once and cleans to a list."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(item, initial) for item in data] or [single(None, initial)]
        return [single(data, initial)]


class PhotoUploadForm(forms.Form):
    photos = MultipleFileField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['photos'].widget.attrs['class'] = 'form-control'

    def clean_photos(self):
        from django.conf import settings
        from PIL import Image

        files = self.cleaned_data['photos']
        limit = settings.MAX_PHOTO_SIZE_MB * 1024 * 1024
        for upload in files:
            if upload.size > limit:
                raise forms.ValidationError(f'{upload.name} is over {settings.MAX_PHOTO_SIZE_MB} MB.')
            try:
                with Image.open(upload) as image:
                    image.verify()
                    if image.format not in ('JPEG', 'PNG', 'WEBP'):
                        raise forms.ValidationError(f'{upload.name} must be a JPEG, PNG or WebP image.')
            except forms.ValidationError:
                raise
            except Exception:
                raise forms.ValidationError(f'{upload.name} is not an image we can read.')
            upload.seek(0)
        return files


SORT_CHOICES = [
    ('newest', 'Newest'),
    ('score', 'Cleanest first'),
    ('price', 'Price: low to high'),
    ('-price', 'Price: high to low'),
    ('name', 'Name'),
]


class ProductSearchForm(BootstrapFormMixin, forms.Form):
    from apps.core.choices import COUNTIES as _COUNTIES

    q = forms.CharField(required=False, label='Search', max_length=200)
    category = forms.ChoiceField(choices=[('', 'Any category')] + list(Product.Category.choices), required=False)
    county = forms.ChoiceField(choices=[('', 'Any county')] + _COUNTIES, required=False)
    max_nova = forms.TypedChoiceField(
        choices=[('', 'Any processing'), (1, 'Unprocessed only (NOVA 1)'), (2, 'Up to NOVA 2'), (3, 'Up to NOVA 3')],
        coerce=int, required=False, empty_value=None, label='Processing')
    min_score = forms.IntegerField(required=False, min_value=0, max_value=100, label='Minimum clean score')
    free_from = forms.MultipleChoiceField(choices=ALLERGENS, required=False, widget=forms.CheckboxSelectMultiple,
                                          label='Free from')
    organic = forms.BooleanField(required=False, label='Certified organic')
    in_season = forms.BooleanField(required=False, label='In season now')
    verified = forms.BooleanField(required=False, label='Verified farms only')
    price_min = forms.DecimalField(required=False, min_value=0, decimal_places=2, label='Min €')
    price_max = forms.DecimalField(required=False, min_value=0, decimal_places=2, label='Max €')
    sort = forms.ChoiceField(choices=SORT_CHOICES, required=False)

    def cleaned_or_ignored(self):
        """Valid fields only: an invalid filter is ignored rather than failing the whole search."""
        self.is_valid()
        return {name: value for name, value in getattr(self, 'cleaned_data', {}).items()
                if name not in self.errors}
