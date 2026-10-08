from django.urls import path

from . import views

app_name = 'saved'

urlpatterns = [
    path('saved/', views.favourites, name='favourites'),
    path('saved/toggle/<int:product_pk>/', views.toggle, name='toggle'),
    path('saved/searches/', views.searches, name='searches'),
    path('saved/searches/new/', views.save_search, name='save_search'),
    path('saved/searches/<int:pk>/delete/', views.delete_search, name='delete_search'),
]
