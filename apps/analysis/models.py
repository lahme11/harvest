from django.db import models


class Additive(models.Model):
    """One entry in the reference list the analyser matches ingredients against."""

    class Kind(models.TextChoices):
        COLOUR = 'colour', 'Colour'
        PRESERVATIVE = 'preservative', 'Preservative'
        ANTIOXIDANT = 'antioxidant', 'Antioxidant'
        EMULSIFIER = 'emulsifier', 'Emulsifier'
        STABILISER = 'stabiliser', 'Stabiliser'
        THICKENER = 'thickener', 'Thickener'
        GELLING_AGENT = 'gelling_agent', 'Gelling agent'
        SWEETENER = 'sweetener', 'Sweetener'
        FLAVOUR_ENHANCER = 'flavour_enhancer', 'Flavour enhancer'
        FLAVOURING = 'flavouring', 'Flavouring'
        ACIDITY_REGULATOR = 'acidity_regulator', 'Acidity regulator'
        RAISING_AGENT = 'raising_agent', 'Raising agent'
        ANTI_CAKING = 'anti_caking', 'Anti-caking agent'
        GLAZING_AGENT = 'glazing_agent', 'Glazing agent'
        HUMECTANT = 'humectant', 'Humectant'
        MODIFIED_STARCH = 'modified_starch', 'Modified starch'
        BULKING_AGENT = 'bulking_agent', 'Bulking agent'
        FOAMING_AGENT = 'foaming_agent', 'Foaming agent'
        ANTI_FOAMING = 'anti_foaming', 'Anti-foaming agent'
        CARRIER = 'carrier', 'Carrier'
        PROTEIN_ISOLATE = 'protein_isolate', 'Industrial protein'
        SUGAR_VARIANT = 'sugar_variant', 'Industrial sugar'
        MODIFIED_FAT = 'modified_fat', 'Modified fat'
        OTHER = 'other', 'Other'

    code = models.CharField(max_length=8, unique=True, null=True, blank=True,
                            help_text='E-number in the form E471 or E160A; leave blank for markers without one.')
    name = models.CharField(max_length=120)
    aliases = models.TextField(blank=True, help_text='Other names on labels, separated by commas.')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    marker = models.BooleanField(help_text='A marker of ultra-processing (NOVA group 4).')

    class Meta:
        ordering = ['code', 'name']

    def __str__(self):
        return f'{self.code} {self.name}' if self.code else self.name

    def alias_list(self):
        return [alias.strip() for alias in self.aliases.split(',') if alias.strip()]

    def as_entry(self):
        return {'code': self.code, 'name': self.name, 'aliases': self.alias_list(), 'kind': self.kind,
                'marker': self.marker}


class BarcodeLookup(models.Model):
    """A cached Open Food Facts response, including "not found", so each barcode is fetched at most monthly."""

    barcode = models.CharField(max_length=14, unique=True)
    found = models.BooleanField()
    data = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField()

    def __str__(self):
        return f"{self.barcode} ({'found' if self.found else 'not found'})"
