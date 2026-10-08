from django.contrib import admin

from . import services
from .models import Product, ProductPhoto


class ProductPhotoInline(admin.TabularInline):
    model = ProductPhoto
    extra = 0
    fields = ('thumbnail', 'position', 'is_cover')
    readonly_fields = ('thumbnail',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'producer', 'category', 'price', 'stock', 'status', 'nova_group', 'grade')
    list_filter = ('status', 'category', 'nova_group', 'kind', 'organic')
    search_fields = ('name', 'producer__name', 'ingredients')
    readonly_fields = ('nova_group', 'clean_score', 'grade', 'analysis_json', 'view_count', 'created_at',
                       'updated_at', 'published_at')
    inlines = [ProductPhotoInline]
    actions = ['reanalyse']

    @admin.action(description='Re-run the ingredient analyser')
    def reanalyse(self, request, queryset):
        for product in queryset:
            services.refresh_analysis(product)
            product.save(update_fields=['nova_group', 'clean_score', 'grade', 'analysis_json'])
        self.message_user(request, f'{queryset.count()} product(s) re-analysed.')
