# mapa_eleitoral/views.py
from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Sum, F, Prefetch
from django.db import connection
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
import json
import os
from django.conf import settings
import folium as fl
from django.utils.safestring import mark_safe
from django.core.cache import cache
from decimal import Decimal
from .models import DadoEleitoral
import branca.colormap as cm
import logging

logger = logging.getLogger(__name__)

def load_geojson():
    """Carregar dados do GeoJSON com cache otimizado"""
    cache_key = 'geojson_data_v2'
    geojson_data = cache.get(cache_key)
    
    if geojson_data is None:
        geojson_path = os.path.join(settings.BASE_DIR, 'mapa_eleitoral', 'data', 'Limite_Bairro.geojson')
        try:
            with open(geojson_path, 'r', encoding='utf-8') as f:
                geojson_data = json.load(f)
            # Cache por 24 horas (dados geográficos raramente mudam)
            cache.set(cache_key, geojson_data, 86400)
        except FileNotFoundError:
            logger.error(f"Arquivo GeoJSON não encontrado: {geojson_path}")
            return None
        except json.JSONDecodeError:
            logger.error(f"Erro ao decodificar JSON: {geojson_path}")
            return None
    
    return geojson_data

def get_cached_dropdown_data():
    """Busca dados dos dropdowns com cache otimizado"""
    cache_key = 'dropdown_data_v2'
    cached_data = cache.get(cache_key)
    
    if cached_data is None:
        # Query otimizada usando SQL raw para melhor performance
        with connection.cursor() as cursor:
            # Buscar anos únicos
            cursor.execute("""
                SELECT DISTINCT ano_eleicao 
                FROM eleicoes_rio 
                ORDER BY ano_eleicao DESC
            """)
            anos = [row[0] for row in cursor.fetchall()]
            
            # Buscar combinações únicas de ano/partido
            cursor.execute("""
                SELECT DISTINCT ano_eleicao, sg_partido 
                FROM eleicoes_rio 
                ORDER BY ano_eleicao DESC, sg_partido
            """)
            partidos_por_ano = {}
            for ano, partido in cursor.fetchall():
                if ano not in partidos_por_ano:
                    partidos_por_ano[ano] = []
                partidos_por_ano[ano].append(partido)
            
            # Buscar combinações únicas de ano/partido/candidato
            cursor.execute("""
                SELECT DISTINCT ano_eleicao, sg_partido, nm_urna_candidato 
                FROM eleicoes_rio 
                ORDER BY ano_eleicao DESC, sg_partido, nm_urna_candidato
            """)
            candidatos_por_partido_ano = {}
            for ano, partido, candidato in cursor.fetchall():
                key = f"{ano}_{partido}"
                if key not in candidatos_por_partido_ano:
                    candidatos_por_partido_ano[key] = []
                candidatos_por_partido_ano[key].append(candidato)
        
        cached_data = {
            'anos': anos,
            'partidos_por_ano': partidos_por_ano,
            'candidatos_por_partido_ano': candidatos_por_partido_ano
        }
        
        # Cache por 1 hora
        cache.set(cache_key, cached_data, 3600)
    
    return cached_data

def get_votos_data(ano, partido, candidato):
    """Busca dados de votos com query otimizada"""
    cache_key = f'votos_{ano}_{partido}_{candidato}_v2'
    cached_votos = cache.get(cache_key)
    
    if cached_votos is None:
        # Query otimizada com agregação no banco
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    nm_bairro,
                    SUM(qt_votos) as total_votos,
                    MAX(ds_cargo) as cargo,
                    MAX(nm_urna_candidato) as nome_candidato
                FROM eleicoes_rio 
                WHERE ano_eleicao = %s 
                    AND sg_partido = %s 
                    AND nm_urna_candidato = %s
                GROUP BY nm_bairro
                ORDER BY nm_bairro
            """, [ano, partido, candidato])
            
            results = cursor.fetchall()
            
            votos_dict = {}
            total_votos = 0
            cargo = None
            nome_candidato = None
            
            for row in results:
                bairro, votos, cargo_temp, nome_temp = row
                votos_int = int(votos) if votos else 0
                votos_dict[bairro] = votos_int
                total_votos += votos_int
                if not cargo:
                    cargo = cargo_temp
                if not nome_candidato:
                    nome_candidato = nome_temp
            
            cached_votos = {
                'votos_dict': votos_dict,
                'total_votos': total_votos,
                'cargo': cargo,
                'nome_candidato': nome_candidato
            }
        
        # Cache por 30 minutos
        cache.set(cache_key, cached_votos, 1800)
    
    return cached_votos

def create_folium_map(votos_dict, total_votos, candidato_info, selected_ano):
    """Cria o mapa Folium otimizado"""
    cache_key = f'map_{hash(str(votos_dict))}_{selected_ano}_v2'
    cached_map = cache.get(cache_key)
    
    if cached_map is None:
        # Criar mapa base
        mapa = fl.Map(
            location=[-22.928777, -43.423878], 
            zoom_start=10, 
            tiles='CartoDB positron',
            prefer_canvas=True
        )
        
        # Preparar dados para o Choropleth
        if votos_dict:
            dados_list = [[bairro, votos] for bairro, votos in votos_dict.items()]
            
            # Caminho do GeoJSON
            geojson_path = os.path.join(settings.BASE_DIR, 'mapa_eleitoral', 'data', 'Limite_Bairro.geojson')
            
            try:
                # Criar choropleth
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
                    bins=10
                ).add_to(mapa)
                
                # Adicionar tooltips otimizados
                geojson_data = load_geojson()
                if geojson_data:
                    # Preparar dados de tooltip de forma mais eficiente
                    tooltip_data = {}
                    for bairro_nome, votos in votos_dict.items():
                        votos_formatado = f"{votos:,}".replace(",", ".")
                        porcentagem = (votos / total_votos * 100) if total_votos > 0 else 0
                        tooltip_data[bairro_nome] = {
                            'votos_formatado': votos_formatado,
                            'porcentagem': f"{porcentagem:.1f}%"
                        }
                    
                    # Adicionar propriedades de tooltip de forma batch
                    for feature in geojson_data['features']:
                        bairro_nome = feature['properties']['NOME']
                        tooltip_info = tooltip_data.get(bairro_nome, {'votos_formatado': '0', 'porcentagem': '0.0%'})
                        
                        feature['properties']['tooltip_content'] = f"""
                            <div style='font-family: Arial; font-size: 12px; color: #333;'>
                                <b>Bairro:</b> {bairro_nome}<br>
                                <b>Total de votos:</b> {tooltip_info['votos_formatado']}<br>
                                <b>Porcentagem:</b> {tooltip_info['porcentagem']}<br>
                                <b>Ano:</b> {selected_ano}
                            </div>
                        """
                    
                    # Adicionar GeoJson com tooltip
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
                
            except Exception as e:
                logger.error(f"Erro ao criar Choropleth: {e}")
        
        # Converter para HTML e fazer cache
        map_html = mark_safe(mapa.get_root().render())
        cache.set(cache_key, map_html, 1800)  # Cache por 30 minutos
        cached_map = map_html
    
    return cached_map

@vary_on_headers('X-Requested-With')
def home_view(request):
    """View principal otimizada do mapa eleitoral"""
    
    # Buscar dados dos dropdowns com cache
    dropdown_data = get_cached_dropdown_data()
    anos = dropdown_data['anos']
    partidos_por_ano = dropdown_data['partidos_por_ano']
    candidatos_por_partido_ano = dropdown_data['candidatos_por_partido_ano']
    
    # Parâmetros selecionados com validação
    selected_ano = request.GET.get('ano', str(anos[0]) if anos else '')
    if selected_ano and int(selected_ano) not in anos:
        selected_ano = str(anos[0]) if anos else ''
    
    partidos = partidos_por_ano.get(int(selected_ano), []) if selected_ano else []
    selected_partido = request.GET.get('partido')
    if not selected_partido or selected_partido not in partidos:
        selected_partido = 'PRB' if 'PRB' in partidos else (partidos[0] if partidos else '')
    
    candidatos_key = f"{selected_ano}_{selected_partido}"
    candidatos = candidatos_por_partido_ano.get(candidatos_key, [])
    selected_candidato = request.GET.get('candidato')
    if not selected_candidato or selected_candidato not in candidatos:
        selected_candidato = 'CRIVELLA' if 'CRIVELLA' in candidatos else (candidatos[0] if candidatos else '')
    
    # Dados do mapa
    map_html = ""
    candidato_info = {}
    
    if selected_candidato and selected_ano and selected_partido:
        # Buscar dados de votos com cache
        votos_data = get_votos_data(selected_ano, selected_partido, selected_candidato)
        
        if votos_data['votos_dict']:
            candidato_info = {
                'nome': votos_data['nome_candidato'],
                'cargo': votos_data['cargo'],
                'votos_total': votos_data['total_votos'],
                'ano': selected_ano
            }
            
            # Criar mapa com cache
            map_html = create_folium_map(
                votos_data['votos_dict'], 
                votos_data['total_votos'], 
                candidato_info, 
                selected_ano
            )
    
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

# Views AJAX otimizadas com cache
@cache_page(3600)  # Cache por 1 hora
def get_candidatos_ajax(request):
    """View AJAX otimizada para obter candidatos"""
    partido = request.GET.get('partido')
    ano = request.GET.get('ano')
    
    if not partido or not ano:
        return JsonResponse({'candidatos': []})
    
    dropdown_data = get_cached_dropdown_data()
    candidatos_key = f"{ano}_{partido}"
    candidatos = dropdown_data['candidatos_por_partido_ano'].get(candidatos_key, [])
    
    return JsonResponse({'candidatos': candidatos})

@cache_page(3600)  # Cache por 1 hora
def get_partidos_ajax(request):
    """View AJAX otimizada para obter partidos"""
    ano = request.GET.get('ano')
    
    if not ano:
        return JsonResponse({'partidos': []})
    
    dropdown_data = get_cached_dropdown_data()
    partidos = dropdown_data['partidos_por_ano'].get(int(ano), [])
    
    return JsonResponse({'partidos': partidos})

@cache_page(3600)  # Cache por 1 hora
def get_anos_ajax(request):
    """View AJAX otimizada para obter anos"""
    dropdown_data = get_cached_dropdown_data()
    return JsonResponse({'anos': dropdown_data['anos']})