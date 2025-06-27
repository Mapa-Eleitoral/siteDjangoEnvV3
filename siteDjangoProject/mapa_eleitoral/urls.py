# mapa_eleitoral/urls.py
from django.urls import path
from . import views

app_name = 'mapa_eleitoral'

urlpatterns = [
    # View principal
    path('', views.home_view, name='home'),
    
    # APIs AJAX originais
    path('get_anos_ajax/', views.get_anos_ajax, name='get_anos_ajax'),
    path('get_partidos_ajax/', views.get_partidos_ajax, name='get_partidos_ajax'),
    path('get_candidatos_ajax/', views.get_candidatos_ajax, name='get_candidatos_ajax'),
    
    # Nova API unificada
    path('get_filter_data_ajax/', views.get_filter_data_ajax, name='get_filter_data_ajax'),
    
    # Views de manutenção (apenas para admins)
    path('admin/clear-cache/', views.clear_cache_view, name='clear_cache'),
    path('admin/cache-stats/', views.cache_stats_view, name='cache_stats'),
]