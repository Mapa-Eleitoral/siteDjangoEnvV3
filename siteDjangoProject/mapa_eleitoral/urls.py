# urls.py - Adicione estas rotas ao seu arquivo urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('get_candidatos_ajax/', views.get_candidatos_ajax, name='get_candidatos_ajax'),
    path('get_partidos_ajax/', views.get_partidos_ajax, name='get_partidos_ajax'),
    path('get_anos_ajax/', views.get_anos_ajax, name='get_anos_ajax'),
]

