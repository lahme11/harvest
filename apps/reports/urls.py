from django.urls import path

from . import views

app_name = 'reports'

urlpatterns = [
    path('report/<int:product_pk>/', views.create, name='create'),
]
