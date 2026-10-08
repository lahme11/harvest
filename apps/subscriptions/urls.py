from django.urls import path

from . import views

app_name = 'subscriptions'

urlpatterns = [
    path('subscriptions/', views.mine, name='mine'),
    path('subscriptions/join/<int:box_pk>/', views.subscribe, name='subscribe'),
    path('subscriptions/<int:pk>/pause/', views.control, {'action': 'pause'}, name='pause'),
    path('subscriptions/<int:pk>/resume/', views.control, {'action': 'resume'}, name='resume'),
    path('subscriptions/<int:pk>/cancel/', views.control, {'action': 'cancel'}, name='cancel'),
    path('subscriptions/<int:pk>/skip/', views.control, {'action': 'skip'}, name='skip'),
    path('sell/subscribers/', views.producer, name='producer'),
]
