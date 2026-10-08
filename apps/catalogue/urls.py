from django.urls import path

from . import views

app_name = 'catalogue'

urlpatterns = [
    path('products/', views.browse, name='browse'),
    path('products/api/', views.api, name='api'),
    path('in-season/', views.season, name='season'),
    path('products/<int:pk>/<slug:slug>/', views.detail, name='detail'),
    path('sell/products/', views.mine, name='mine'),
    path('sell/products/new/', views.product_form, name='create'),
    path('sell/products/<int:pk>/', views.product_form, name='edit'),
    path('sell/products/<int:pk>/publish/', views.publish, name='publish'),
    path('sell/products/<int:pk>/pause/', views.pause, name='pause'),
    path('sell/products/<int:pk>/archive/', views.archive, name='archive'),
    path('sell/products/<int:pk>/stock/', views.stock, name='stock'),
    path('sell/products/<int:pk>/price/', views.price, name='price'),
    path('sell/products/<int:pk>/photos/', views.photos, name='photos'),
    path('sell/photos/<int:pk>/cover/', views.photo_cover, name='photo_cover'),
    path('sell/photos/<int:pk>/delete/', views.photo_delete, name='photo_delete'),
    path('sell/barcode/', views.barcode, name='barcode'),
]
