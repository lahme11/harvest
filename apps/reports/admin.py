from django.contrib import admin

from . import services
from .models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('product', 'reason', 'reporter', 'status', 'created_at')
    list_filter = ('status', 'reason')
    search_fields = ('product__name', 'details', 'reporter__username')
    readonly_fields = ('product', 'reporter', 'reason', 'details', 'created_at', 'resolved_at', 'resolved_by')
    actions = ['dismiss', 'unlist']

    @admin.action(description='Dismiss selected reports')
    def dismiss(self, request, queryset):
        for report in queryset.filter(status=Report.Status.OPEN):
            services.dismiss(report, request.user)
        self.message_user(request, 'Reports dismissed.')

    @admin.action(description='Unlist the reported products')
    def unlist(self, request, queryset):
        for report in queryset.filter(status=Report.Status.OPEN):
            report.refresh_from_db()
            if report.status == Report.Status.OPEN:
                services.unlist(report, request.user)
        self.message_user(request, 'Products unlisted and their reports closed.')
