# mapa_eleitoral/views.py
from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Sum, F
import json
import os
from django.conf import settings
import folium as fl
from django.utils.safestring import mark_safe
from django.core.cache import cache
from decimal import Decimal
from .models import DadoEleitoral  # ou DadoEleitoralRaw
import branca.colormap as cm

def load_geojson():
    """Carregar dados do GeoJSON (mantém como estava)"""
    cache_key = 'geojson_data'
    geojson_data = cache.get(cache_key)
    
    if geojson_data is None:
        geojson_path = os.path.join(settings.BASE_DIR, 'mapa_eleitoral', 'data', 'Limite_Bairro.geojson')
        with open(geojson_path, 'r', encoding='utf-8') as f:
            geojson_data = json.load(f)
        cache.set(cache_key, geojson_data, 3600)  # Cache por 1 hora
    
    return geojson_data

def home_view(request):
    """View principal do mapa eleitoral usando MySQL"""
    
    # Obter lista de anos únicos do banco
    anos = list(
        DadoEleitoral.objects
        .values_list('ano_eleicao', flat=True)
        .distinct()
        .order_by('-ano_eleicao')  # Ordenar do mais recente para o mais antigo
    )
    
    # Obter lista de partidos únicos do banco (filtrado por ano se selecionado)
    selected_ano = request.GET.get('ano', str(anos[0]) if anos else '')
    
    partidos_query = DadoEleitoral.objects
    if selected_ano:
        partidos_query = partidos_query.filter(ano_eleicao=selected_ano)
    
    partidos = list(
        partidos_query
        .values_list('sg_partido', flat=True)
        .distinct()
        .order_by('sg_partido')
    )
    
    # Partido e candidato selecionados
    selected_partido = request.GET.get('partido', 'PRB' if 'PRB' in partidos else (partidos[0] if partidos else ''))
    selected_candidato = request.GET.get('candidato', '')
    
    # Obter candidatos do partido selecionado (filtrado por ano)
    candidatos_query = DadoEleitoral.objects
    if selected_ano:
        candidatos_query = candidatos_query.filter(ano_eleicao=selected_ano)
    if selected_partido:
        candidatos_query = candidatos_query.filter(sg_partido=selected_partido)
    
    candidatos = list(
        candidatos_query
        .values_list('nm_urna_candidato', flat=True)
        .distinct()
        .order_by('nm_urna_candidato')
    )
    
    # Se não há candidato selecionado, usar o primeiro ou o padrão
    if not selected_candidato or selected_candidato not in candidatos:
        selected_candidato = 'CRIVELLA' if 'CRIVELLA' in candidatos else (candidatos[0] if candidatos else '')
    
    # Dados do mapa
    map_html = ""
    candidato_info = {}
    
    if selected_candidato and selected_ano:
        # Buscar e somar votos por bairro para o candidato selecionado no ano específico
        votos_por_bairro = (
            DadoEleitoral.objects
            .filter(
                ano_eleicao=selected_ano,
                sg_partido=selected_partido,
                nm_urna_candidato=selected_candidato
            )
            .values('nm_bairro')
            .annotate(
                total_votos=Sum('qt_votos')
            )
            .order_by('nm_bairro')
        )
        
        # Debug para verificar os dados
        print(f"Dados por bairro para {selected_candidato} em {selected_ano}:")
        for vpb in votos_por_bairro:
            print(f"Bairro: {vpb['nm_bairro']}, Votos: {vpb['total_votos']}")
        
        # Converter para dicionário e garantir que são inteiros
        votos_dict = {
            item['nm_bairro']: int(item['total_votos']) if isinstance(item['total_votos'], (Decimal, int, float)) else 0 
            for item in votos_por_bairro
        }
        
        # Calcular total geral de votos do candidato
        total_votos = sum(votos_dict.values())
        
        # Informações do candidato
        primeiro_registro = (
            DadoEleitoral.objects
            .filter(
                ano_eleicao=selected_ano,
                sg_partido=selected_partido,
                nm_urna_candidato=selected_candidato
            )
            .first()
        )
        
        if primeiro_registro:
            candidato_info = {
                'nome': primeiro_registro.nm_urna_candidato,
                'cargo': primeiro_registro.ds_cargo,
                'votos_total': total_votos,
                'ano': selected_ano
            }
            
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
                # Definindo a escala de cores manualmente
                for key in choropleth._children:
                    if key.startswith('color_map'):
                        choropleth._children[key].color_scale = [
                            '#f7fcf5',  # Verde muito claro
                            '#edf8e9',
                            '#e5f5e0',
                            '#c7e9c0',
                            '#a1d99b',
                            '#74c476',
                            '#41ab5d',
                            '#238b45',
                            '#006d2c',
                            '#00441b'   # Verde muito escuro
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
                        <b>Ano:</b> {selected_ano}
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

def get_candidatos_ajax(request):
    """View AJAX para obter candidatos baseado no partido e ano selecionados"""
    partido = request.GET.get('partido')
    ano = request.GET.get('ano')
    
    if not partido:
        return JsonResponse({'candidatos': []})
    
    candidatos_query = DadoEleitoral.objects.filter(sg_partido=partido)
    
    if ano:
        candidatos_query = candidatos_query.filter(ano_eleicao=ano)
    
    candidatos = list(
        candidatos_query
        .values_list('nm_urna_candidato', flat=True)
        .distinct()
        .order_by('nm_urna_candidato')
    )
    
    return JsonResponse({'candidatos': candidatos})

def get_partidos_ajax(request):
    """View AJAX para obter partidos baseado no ano selecionado"""
    ano = request.GET.get('ano')
    
    if not ano:
        return JsonResponse({'partidos': []})
    
    partidos = list(
        DadoEleitoral.objects
        .filter(ano_eleicao=ano)
        .values_list('sg_partido', flat=True)
        .distinct()
        .order_by('sg_partido')
    )
    
    return JsonResponse({'partidos': partidos})

def get_anos_ajax(request):
    """View AJAX para obter todos os anos disponíveis"""
    anos = list(
        DadoEleitoral.objects
        .values_list('ano_eleicao', flat=True)
        .distinct()
        .order_by('-ano_eleicao')  # Ordenar do mais recente para o mais antigo
    )
    
    return JsonResponse({'anos': anos})

