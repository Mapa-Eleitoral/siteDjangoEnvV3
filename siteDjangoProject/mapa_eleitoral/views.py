# mapa_eleitoral/views.py
from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Sum, F
from django.views.decorators.cache import cache_page
from django.core.cache import cache
from django.utils.cache import get_cache_key
from django.utils.decorators import method_decorator
from django.views.decorators.vary import vary_on_headers
import json
import os
from django.conf import settings
import folium as fl
from django.utils.safestring import mark_safe
from decimal import Decimal
from .models import DadoEleitoral  # ou DadoEleitoralRaw
import branca.colormap as cm
import hashlib


def load_geojson():
    """Carregar dados do GeoJSON (mantém como estava)"""
    cache_key = 'geojson_data'
    geojson_data = cache.get(cache_key)
    
    if geojson_data is None:
        geojson_path = os.path.join(settings.BASE_DIR, 'mapa_eleitoral', 'data', 'Limite_Bairro.geojson')
        with open(geojson_path, 'r', encoding='utf-8') as f:
            geojson_data = json.load(f)
        cache.set(cache_key, geojson_data, 86400)  # Cache por 24 horas
    
    return geojson_data


def get_cached_anos():
    """Cache para lista de anos"""
    cache_key = 'anos_eleicao'
    anos = cache.get(cache_key)
    
    if anos is None:
        anos = list(
            DadoEleitoral.objects
            .values_list('ano_eleicao', flat=True)
            .distinct()
            .order_by('-ano_eleicao')
        )
        # Cache por 1 hora - dados raramente mudam
        cache.set(cache_key, anos, 3600)
    
    return anos


def get_cached_partidos(ano=None):
    """Cache para lista de partidos por ano"""
    cache_key = f'partidos_{ano}' if ano else 'partidos_all'
    partidos = cache.get(cache_key)
    
    if partidos is None:
        partidos_query = DadoEleitoral.objects
        if ano:
            partidos_query = partidos_query.filter(ano_eleicao=ano)
        
        partidos = list(
            partidos_query
            .values_list('sg_partido', flat=True)
            .distinct()
            .order_by('sg_partido')
        )
        # Cache por 30 minutos
        cache.set(cache_key, partidos, 1800)
    
    return partidos


def get_cached_candidatos(partido=None, ano=None):
    """Cache para lista de candidatos por partido e ano"""
    cache_key = f'candidatos_{partido}_{ano}'
    candidatos = cache.get(cache_key)
    
    if candidatos is None:
        candidatos_query = DadoEleitoral.objects
        if ano:
            candidatos_query = candidatos_query.filter(ano_eleicao=ano)
        if partido:
            candidatos_query = candidatos_query.filter(sg_partido=partido)
        
        candidatos = list(
            candidatos_query
            .values_list('nm_urna_candidato', flat=True)
            .distinct()
            .order_by('nm_urna_candidato')
        )
        # Cache por 30 minutos
        cache.set(cache_key, candidatos, 1800)
    
    return candidatos


def get_cached_votos_por_bairro(candidato, partido, ano):
    """Cache para dados de votos por bairro"""
    # Criar hash da combinação para evitar chaves muito longas
    params_hash = hashlib.md5(f"{candidato}_{partido}_{ano}".encode()).hexdigest()
    cache_key = f'votos_bairro_{params_hash}'
    
    cached_data = cache.get(cache_key)
    
    if cached_data is None:
        # Buscar e somar votos por bairro
        votos_por_bairro = (
            DadoEleitoral.objects
            .filter(
                ano_eleicao=ano,
                sg_partido=partido,
                nm_urna_candidato=candidato
            )
            .values('nm_bairro')
            .annotate(
                total_votos=Sum('qt_votos')
            )
            .order_by('nm_bairro')
        )
        
        # Converter para dicionário
        votos_dict = {
            item['nm_bairro']: int(item['total_votos']) if isinstance(item['total_votos'], (Decimal, int, float)) else 0 
            for item in votos_por_bairro
        }
        
        # Calcular total
        total_votos = sum(votos_dict.values())
        
        cached_data = {
            'votos_dict': votos_dict,
            'total_votos': total_votos
        }
        
        # Cache por 15 minutos (dados podem ser atualizados com mais frequência)
        cache.set(cache_key, cached_data, 900)
    
    return cached_data


def get_cached_candidato_info(candidato, partido, ano):
    """Cache para informações do candidato"""
    cache_key = f'candidato_info_{candidato}_{partido}_{ano}'
    candidato_info = cache.get(cache_key)
    
    if candidato_info is None:
        primeiro_registro = (
            DadoEleitoral.objects
            .filter(
                ano_eleicao=ano,
                sg_partido=partido,
                nm_urna_candidato=candidato
            )
            .first()
        )
        
        if primeiro_registro:
            candidato_info = {
                'nome': primeiro_registro.nm_urna_candidato,
                'cargo': primeiro_registro.ds_cargo,
                'ano': ano
            }
        else:
            candidato_info = {}
        
        # Cache por 1 hora
        cache.set(cache_key, candidato_info, 3600)
    
    return candidato_info


def generate_map_html(votos_dict, total_votos, candidato_info):
    """Gerar HTML do mapa - função separada para facilitar cache"""
    # Criar hash dos dados para cache do mapa
    data_hash = hashlib.md5(
        f"{str(votos_dict)}_{total_votos}_{candidato_info}".encode()
    ).hexdigest()
    
    cache_key = f'map_html_{data_hash}'
    map_html = cache.get(cache_key)
    
    if map_html is None:
        # Criar mapa
        mapa = fl.Map(
            location=[-22.928777, -43.423878], 
            zoom_start=10, 
            tiles='CartoDB positron',
            prefer_canvas=True
        )
        
        # Preparar dados para o Choropleth
        dados_list = [
            [bairro, votos] 
            for bairro, votos in votos_dict.items()
        ]
        
        # Caminho do GeoJSON
        geojson_path = os.path.join(settings.BASE_DIR, 'mapa_eleitoral', 'data', 'Limite_Bairro.geojson')
        
        try:
            # Criar choropleth usando lista de listas
            choropleth = fl.Choropleth(
                geo_data=geojson_path,
                name='choropleth',
                data=dados_list,
                columns=['Bairro', 'Votos'],
                key_on='feature.properties.NOME',
                fill_color='YlGn',
                nan_fill_color='#ff7575',
                fill_opacity=0.7,
                line_opacity=0.2,
                legend_name='Total de Votos',
                highlight=True,
                smooth_factor=0,
                bins=10,
                format_numbers=lambda x: f'{int(float(x)):,d}'.replace(',', '.'),
                legend_position='bottomright'
            ).add_to(mapa)
            
            # Personalizar a legenda com 10 tons de verde
            for key in choropleth._children:
                if key.startswith('color_map'):
                    choropleth._children[key].color_scale = [
                        '#f7fcf5', '#edf8e9', '#e5f5e0', '#c7e9c0', '#a1d99b',
                        '#74c476', '#41ab5d', '#238b45', '#006d2c', '#00441b'
                    ]
            
        except Exception as e:
            print(f"Erro no Choropleth: {e}")
        
        # Adicionar tooltips com informações de votos
        geojson_data = load_geojson()
        for feature in geojson_data['features']:
            bairro_nome = feature['properties']['NOME']
            votos = votos_dict.get(bairro_nome, 0)
            votos_formatado = f"{votos:,}".replace(",", ".")
            
            # Calcular porcentagem em relação ao total
            porcentagem = (votos / total_votos * 100) if total_votos > 0 else 0
            
            feature['properties']['tooltip_content'] = f"""
                <div style='font-family: Arial; font-size: 12px; color: #333;'>
                    <b>Bairro:</b> {bairro_nome}<br>
                    <b>Total de votos:</b> {votos_formatado}<br>
                    <b>Porcentagem:</b> {porcentagem:.1f}%<br>
                    <b>Ano:</b> {candidato_info.get('ano', '')}
                </div>
            """
        
        # Adicionar GeoJson com tooltip detalhado
        fl.GeoJson(
            geojson_data,
            name='Detalhes',
            style_function=lambda feature: {
                'fillColor': 'transparent',
                'color': 'black',
                'weight': 1,
                'fillOpacity': 0,
            },
            tooltip=fl.GeoJsonTooltip(
                fields=['tooltip_content'],
                aliases=[''],
                localize=True,
                sticky=True,
                labels=False,
                style="""
                    background-color: white;
                    color: #333333;
                    font-family: Arial;
                    font-size: 12px;
                    padding: 10px;
                    border: 1px solid #cccccc;
                    border-radius: 3px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.2);
                """
            )
        ).add_to(mapa)
        
        # Converter mapa para HTML
        map_html = mark_safe(mapa._repr_html_())
        
        # Cache por 10 minutos (mapas podem ser pesados)
        cache.set(cache_key, map_html, 600)
    
    return map_html


def home_view(request):
    """View principal do mapa eleitoral usando MySQL com cache otimizado"""
    
    # Obter dados com cache
    anos = get_cached_anos()
    
    # Obter parâmetros da requisição
    selected_ano = request.GET.get('ano', str(anos[0]) if anos else '')
    
    # Obter partidos com cache
    partidos = get_cached_partidos(selected_ano)
    
    # Partido e candidato selecionados
    selected_partido = request.GET.get('partido', 'PRB' if 'PRB' in partidos else (partidos[0] if partidos else ''))
    selected_candidato = request.GET.get('candidato', '')
    
    # Obter candidatos com cache
    candidatos = get_cached_candidatos(selected_partido, selected_ano)
    
    # Se não há candidato selecionado, usar o primeiro ou o padrão
    if not selected_candidato or selected_candidato not in candidatos:
        selected_candidato = 'CRIVELLA' if 'CRIVELLA' in candidatos else (candidatos[0] if candidatos else '')
    
    # Dados do mapa
    map_html = ""
    candidato_info = {}
    
    if selected_candidato and selected_ano:
        # Obter dados de votos com cache
        votos_data = get_cached_votos_por_bairro(selected_candidato, selected_partido, selected_ano)
        votos_dict = votos_data['votos_dict']
        total_votos = votos_data['total_votos']
        
        # Obter informações do candidato com cache
        candidato_info = get_cached_candidato_info(selected_candidato, selected_partido, selected_ano)
        candidato_info['votos_total'] = total_votos
        
        if candidato_info and votos_dict:
            # Gerar mapa com cache
            map_html = generate_map_html(votos_dict, total_votos, candidato_info)
    
    context = {
        'anos': anos,
        'partidos': partidos,
        'candidatos': candidatos,
        'selected_ano': selected_ano,
        'selected_partido': selected_partido,
        'selected_candidato': selected_candidato,
        'candidato_info': candidato_info,
        'map_html': map_html,
    }
    
    return render(request, 'home.html', context)


@cache_page(60 * 5)  # Cache por 5 minutos
def get_candidatos_ajax(request):
    """View AJAX para obter candidatos baseado no partido e ano selecionados"""
    partido = request.GET.get('partido')
    ano = request.GET.get('ano')
    
    if not partido:
        return JsonResponse({'candidatos': []})
    
    # Usar função com cache
    candidatos = get_cached_candidatos(partido, ano)
    
    return JsonResponse({'candidatos': candidatos})


@cache_page(60 * 10)  # Cache por 10 minutos
def get_partidos_ajax(request):
    """View AJAX para obter partidos baseado no ano selecionado"""
    ano = request.GET.get('ano')
    
    if not ano:
        return JsonResponse({'partidos': []})
    
    # Usar função com cache
    partidos = get_cached_partidos(ano)
    
    return JsonResponse({'partidos': partidos})


@cache_page(60 * 30)  # Cache por 30 minutos
def get_anos_ajax(request):
    """View AJAX para obter todos os anos disponíveis"""
    # Usar função com cache
    anos = get_cached_anos()
    
    return JsonResponse({'anos': anos})


# Função utilitária para limpar cache quando necessário
def clear_electoral_cache():
    """Limpar todo o cache relacionado aos dados eleitorais"""
    from django.core.cache import cache
    
    # Limpar caches específicos
    cache.delete_many([
        'geojson_data',
        'anos_eleicao',
    ])
    
    # Limpar caches com padrões (requer implementação mais específica)
    # Em um ambiente de produção, considere usar tags de cache
    print("Cache eleitoral limpo!")


# Middleware ou signal para invalidar cache quando dados são atualizados
# from django.db.models.signals import post_save, post_delete
# from django.dispatch import receiver
# 
# @receiver([post_save, post_delete], sender=DadoEleitoral)
# def invalidate_electoral_cache(sender, **kwargs):
#     """Invalidar cache quando dados eleitorais são modificados"""
#     clear_electoral_cache()