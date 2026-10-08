from django.contrib import admin, messages

from . import services
from .models import CollectionPoint, CollectionSlot, FarmApplication, Producer, Review, SlotRule


@admin.register(Producer)
class ProducerAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'county', 'verified', 'created_at')
    list_filter = ('verified', 'county')
    search_fields = ('name', 'user__username', 'user__email')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(FarmApplication)
class FarmApplicationAdmin(admin.ModelAdmin):
    list_display = ('farm_name', 'producer', 'registration_no', 'county', 'status', 'created_at')
    list_filter = ('status', 'county')
    search_fields = ('farm_name', 'registration_no', 'producer__name')
    readonly_fields = ('decided_at', 'decided_by', 'created_at')
    actions = ['approve', 'reject']

    @admin.action(description='Approve selected applications')
    def approve(self, request, queryset):
        done = 0
        for application in queryset:
            try:
                services.approve_application(application, request.user)
                done += 1
            except services.ProducerError as error:
                self.message_user(request, f'{application}: {error}', messages.WARNING)
        self.message_user(request, f'{done} application(s) approved.')

    @admin.action(description='Reject selected applications (using the reason entered on each)')
    def reject(self, request, queryset):
        done = 0
        for application in queryset:
            try:
                services.reject_application(application, application.reason, request.user)
                done += 1
            except services.ProducerError as error:
                self.message_user(request, f'{application}: {error}', messages.WARNING)
        self.message_user(request, f'{done} application(s) rejected.')


class SlotRuleInline(admin.TabularInline):
    model = SlotRule
    extra = 0


@admin.register(CollectionPoint)
class CollectionPointAdmin(admin.ModelAdmin):
    list_display = ('name', 'producer', 'county', 'cutoff_hours', 'active')
    list_filter = ('active', 'county')
    inlines = [SlotRuleInline]


@admin.register(CollectionSlot)
class CollectionSlotAdmin(admin.ModelAdmin):
    list_display = ('point', 'start', 'end', 'capacity')
    list_filter = ('point__producer',)
    date_hierarchy = 'start'


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('producer', 'author', 'rating', 'updated_at')
    list_filter = ('rating',)
    search_fields = ('producer__name', 'author__username', 'text')
