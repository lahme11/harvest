from django.urls import path

from . import views

app_name = 'producers'

urlpatterns = [
    path('producers/', views.directory, name='directory'),
    path('producers/<slug:slug>/', views.detail, name='detail'),
    path('producers/<slug:slug>/review/', views.review, name='review'),
    path('sell/reviews/<int:pk>/reply/', views.review_reply, name='review_reply'),
    path('sell/setup/', views.setup, name='setup'),
    path('sell/profile/', views.edit, name='edit'),
    path('sell/verification/', views.apply, name='apply'),
    path('sell/collection/', views.points, name='points'),
    path('sell/collection/new/', views.point_form, name='point_create'),
    path('sell/collection/<int:pk>/', views.point_form, name='point_edit'),
    path('sell/collection/<int:pk>/delete/', views.point_delete, name='point_delete'),
    path('sell/collection/<int:point_pk>/times/new/', views.rule_form, name='rule_create'),
    path('sell/collection/times/<int:pk>/', views.rule_form, name='rule_edit'),
    path('sell/collection/times/<int:pk>/delete/', views.rule_delete, name='rule_delete'),
]
