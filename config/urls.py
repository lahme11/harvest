from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = 'Harvest admin'
admin.site.site_title = 'Harvest admin'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('', include('apps.producers.urls')),
    path('', include('apps.catalogue.urls')),
    path('', include('apps.orders.urls')),
    path('', include('apps.subscriptions.urls')),
    path('', include('apps.messaging.urls')),
    path('', include('apps.saved.urls')),
    path('', include('apps.reports.urls')),
    path('', include('apps.core.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
