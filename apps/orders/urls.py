from django.urls import path

from . import views

app_name = 'orders'

urlpatterns = [
    path('basket/', views.basket, name='basket'),
    path('basket/add/<int:product_pk>/', views.add, name='add'),
    path('basket/update/<int:product_pk>/', views.update, name='update'),
    path('basket/remove/<int:product_pk>/', views.remove, name='remove'),
    path('checkout/<int:producer_pk>/', views.checkout, name='checkout'),
    path('checkout/<int:producer_pk>/<int:slot_pk>/', views.confirm, name='confirm'),
    path('orders/', views.my_orders, name='mine'),
    path('sell/', views.dashboard, name='dashboard'),
    path('sell/orders/', views.producer_orders, name='producer_orders'),
    path('sell/orders/pick-list/', views.pick_list, name='pick_list'),
    path('orders/<str:number>/act/', views.act, name='act'),
    path('orders/<str:number>/', views.detail, name='detail'),
]
