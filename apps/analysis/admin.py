from django.contrib import admin

from .models import Additive, BarcodeLookup


@admin.register(Additive)
class AdditiveAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'kind', 'marker')
    list_filter = ('marker', 'kind')
    search_fields = ('code', 'name', 'aliases')
    list_editable = ('marker',)


@admin.register(BarcodeLookup)
class BarcodeLookupAdmin(admin.ModelAdmin):
    list_display = ('barcode', 'found', 'fetched_at')
    list_filter = ('found',)
    search_fields = ('barcode',)
