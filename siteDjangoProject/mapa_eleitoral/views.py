# mapa_eleitoral/views.py - VERSÃO OTIMIZADA COMPLETA
from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Sum, F, Prefetch
from django.views.decorators.cache import cache_page
from django.core.cache import cache
from django.utils.cache import get_cache_key
from django.utils.decorators import method_decorator
from django.views.decorators.vary import vary_on_headers
from django.templatetags.static import static
import json
import os
from django.conf import settings
import folium as fl
from django.utils.safestring import mark_safe
from decimal import Decimal
from .models import DadoEleitoral
import branca.colormap as cm
import hashlib
import time

# ==================== CONFIGURAÇÕES OTIMIZADAS ====================

# Cache TTL otimizado (em segundos)
CACHE_TIMES = {
    'geojson_data': 86400 * 7,      # 7 dias (era 24h)
    'anos_eleicao': 86400,          # 24 horas (era 1h)
    'partidos': 43200,              # 12 horas (era 30min)
    'candidatos': 43200,            # 12 horas (era 30min)
    'votos_bairro': 21600,          # 6 horas (era 15min) - CRÍTICO
    'map_html': 86400,              # 24 horas (era 10min) - CRÍTICO
    'candidato_info': 86400,        # 24 horas (era 1h)
    'complete_data': 43200,         # 12 horas - NOVO
}

def generate_safe_cache_key(prefix, *args):
    """Gera chave de cache segura e consistente"""
    raw = "_".join(str(arg) for arg in args)
    hashed = hashlib.md5(raw.encode()).hexdigest()
    return f"{prefix}_{hashed}"

# ==================== CACHE OTIMIZADO ====================

def load_geojson():
    """Carrega GeoJSON com cache estendido"""
    cache_key = 'geojson_data'
    geojson_data = cache.get(cache_key)

    if geojson_data is None:
        geojson_path = os.path.join(settings.BASE_DIR, 'mapa_eleitoral', 'data', 'Limite_Bairro.geojson')
        with open(geojson_path, 'r', encoding='utf-8') as f:
            geojson_data = json.load(f)
        cache.set(cache_key, geojson_data, CACHE_TIMES['geojson_data'])  # 7 dias

    return geojson_data

def get_cached_anos():
    """Cache de anos com TTL otimizado"""
    cache_key = 'anos_eleicao'
    anos = cache.get(cache_key)

    if anos is None:
        anos = list(
            DadoEleitoral.objects
            .values_list('ano_eleicao', flat=True)
            .distinct()
            .order_by('-ano_eleicao')
        )
        cache.set(cache_key, anos, CACHE_TIMES['anos_eleicao'])  # 24h

    return anos

def get_cached_partidos(ano=None):
    """Cache de partidos otimizado"""
    cache_key = generate_safe_cache_key('partidos', ano if ano else 'all')
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
        cache.set(cache_key, partidos, CACHE_TIMES['partidos'])  # 12h

    return partidos

def get_cached_candidatos(partido=None, ano=None):
    """Cache de candidatos otimizado"""
    cache_key = generate_safe_cache_key('candidatos', partido, ano)
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
        cache.set(cache_key, candidatos, CACHE_TIMES['candidatos'])  # 12h

    return candidatos

# ==================== QUERY OTIMIZADA ====================

def get_complete_candidate_data(candidato, partido, ano):
    """
    NOVA FUNÇÃO: Busca todos os dados necessários em uma única query otimizada
    Substitui múltiplas funções separadas por uma única consulta eficiente
    """
    cache_key = generate_safe_cache_key('complete_data', candidato, partido, ano)
    cached_data = cache.get(cache_key)
    
    if cached_data is None:
        # Query única otimizada com select_related e prefetch
        dados = list(
            DadoEleitoral.objects
            .filter(
                ano_eleicao=ano,
                sg_partido=partido,
                nm_urna_candidato=candidato
            )
            .values('nm_bairro', 'qt_votos', 'ds_cargo', 'nm_urna_candidato')
            .order_by('nm_bairro')
        )
        
        if not dados:
            return None
            
        # Processa dados uma única vez
        votos_dict = {}
        total_votos = 0
        candidato_info = {
            'nome': dados[0]['nm_urna_candidato'],
            'cargo': dados[0]['ds_cargo'],
            'ano': ano
        }
        
        for item in dados:
            bairro = item['nm_bairro']
            votos = int(item['qt_votos']) if isinstance(item['qt_votos'], (Decimal, int, float)) else 0
            
            if bairro in votos_dict:
                votos_dict[bairro] += votos
            else:
                votos_dict[bairro] = votos
            
            total_votos += votos
        
        candidato_info['votos_total'] = total_votos
        
        cached_data = {
            'votos_dict': votos_dict,
            'total_votos': total_votos,
            'candidato_info': candidato_info
        }
        
        # Cache por 12 horas
        cache.set(cache_key, cached_data, CACHE_TIMES['complete_data'])
    
    return cached_data

# ==================== GERAÇÃO DE MAPA OTIMIZADA ====================

def generate_optimized_map_html(votos_dict, total_votos, candidato_info):
    """Gera mapa HTML otimizado com cache estendido"""
    data_hash = hashlib.md5(
        f"{str(sorted(votos_dict.items()))}_{total_votos}_{candidato_info}".encode()
    ).hexdigest()

    cache_key = f'map_html_{data_hash}'
    map_html = cache.get(cache_key)

    if map_html is None:
        start_time = time.time()
        
        # Configuração otimizada do mapa
        mapa = fl.Map(
            location=[-22.928777, -43.423878],
            zoom_start=10,
            tiles='CartoDB positron',
            prefer_canvas=True,
            control_scale=False,          # Remove controle desnecessário
            attribution_control=False,    # Remove atribuição para performance
        )

        dados_list = [
            [bairro, votos]
            for bairro, votos in votos_dict.items()
        ]

        geojson_path = os.path.join(settings.BASE_DIR, 'mapa_eleitoral', 'data', 'Limite_Bairro.geojson')

        try:
            # Choropleth otimizado
            choropleth = fl.Choropleth(
                geo_data=geojson_path,
                name='choropleth',
                data=dados_list,
                columns=['Bairro', 'Votos'],
                key_on='feature.properties.NOME',
                fill_color='YlGn',
                nan_fill_color='#ff7575',
                fill_opacity=0.7,
                line_opacity=0.1,             # Reduzido para performance
                legend_name='Total de Votos',
                highlight=True,
                smooth_factor=2,              # Maior simplificação
                bins=8,                       # Menos bins para performance
            ).add_to(mapa)

        except Exception as e:
            print(f"Erro no Choropleth: {e}")

        # GeoJSON com tooltips otimizados
        geojson_data = load_geojson()
        for feature in geojson_data['features']:
            bairro_nome = feature['properties']['NOME']
            votos = votos_dict.get(bairro_nome, 0)
            votos_formatado = f"{votos:,}".replace(",", ".")
            porcentagem = (votos / total_votos * 100) if total_votos > 0 else 0

            # Tooltip simplificado para melhor performance
            feature['properties']['tooltip_content'] = f"""
                <b>{bairro_nome}</b><br>
                Votos: {votos_formatado}<br>
                {porcentagem:.1f}%
            """

        fl.GeoJson(
            geojson_data,
            name='Detalhes',
            style_function=lambda feature: {
                'fillColor': 'transparent',
                'color': 'black',
                'weight': 0.5,                # Linha mais fina
                'fillOpacity': 0,
            },
            tooltip=fl.GeoJsonTooltip(
                fields=['tooltip_content'],
                aliases=[''],
                localize=True,
                sticky=False,                 # Melhor performance
                labels=False,
                style="""
                    background-color: white;
                    color: #333333;
                    font-family: Arial;
                    font-size: 12px;
                    padding: 8px;
                    border: 1px solid #ccc;
                    border-radius: 3px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.2);
                """
            )
        ).add_to(mapa)

        map_html = mark_safe(mapa._repr_html_())
        
        # Cache por 24 horas (era 10 minutos!)
        cache.set(cache_key, map_html, CACHE_TIMES['map_html'])
        
        generation_time = time.time() - start_time
        print(f"Mapa gerado em {generation_time:.2f}s")

    return map_html

# ==================== VIEW PRINCIPAL OTIMIZADA ====================

def home_view(request):
    """View principal otimizada com menos queries e mapa via iframe"""
    start_time = time.time()

    # Dados básicos
    anos = get_cached_anos()
    selected_ano = request.GET.get('ano', str(anos[0]) if anos else '')
    partidos = get_cached_partidos(selected_ano)
    selected_partido = request.GET.get('partido', 'PRB' if 'PRB' in partidos else (partidos[0] if partidos else ''))
    selected_candidato = request.GET.get('candidato', '')
    candidatos = get_cached_candidatos(selected_partido, selected_ano)

    if not selected_candidato or selected_candidato not in candidatos:
        selected_candidato = 'CRIVELLA' if 'CRIVELLA' in candidatos else (candidatos[0] if candidatos else '')

    map_url = ""
    candidato_info = {}

    if selected_candidato and selected_ano:
        complete_data = get_complete_candidate_data(selected_candidato, selected_partido, selected_ano)

        if complete_data:
            votos_dict = complete_data['votos_dict']
            total_votos = complete_data['total_votos']
            candidato_info = complete_data['candidato_info']

            if candidato_info and votos_dict:
                map_url = generate_static_map_html(votos_dict, total_votos, candidato_info)

    context = {
        'anos': anos,
        'partidos': partidos,
        'candidatos': candidatos,
        'selected_ano': selected_ano,
        'selected_partido': selected_partido,
        'selected_candidato': selected_candidato,
        'candidato_info': candidato_info,
        'map_url': map_url,
    }

    total_time = time.time() - start_time
    if total_time > 1:
        print(f"View lenta detectada: {total_time:.2f}s")

    return render(request, 'home.html', context)


# ==================== APIS AJAX OTIMIZADAS ====================

@cache_page(60 * 60)  # 60 minutos
def get_anos_ajax(request):
    """API otimizada para anos"""
    anos = get_cached_anos()
    return JsonResponse({'anos': anos})

@cache_page(60 * 30)  # 30 minutos (era 5)
def get_candidatos_ajax(request):
    """API otimizada para candidatos"""
    partido = request.GET.get('partido')
    ano = request.GET.get('ano')

    if not partido:
        return JsonResponse({'candidatos': []})

    candidatos = get_cached_candidatos(partido, ano)
    return JsonResponse({'candidatos': candidatos})

@cache_page(60 * 60)  # 60 minutos (era 10)
def get_partidos_ajax(request):
    """API otimizada para partidos"""
    ano = request.GET.get('ano')

    if not ano:
        return JsonResponse({'partidos': []})

    partidos = get_cached_partidos(ano)
    return JsonResponse({'partidos': partidos})

# ==================== NOVA API UNIFICADA ====================

@cache_page(60 * 15)  # 15 minutos
def get_filter_data_ajax(request):
    """
    NOVA API: Retorna todos os dados de filtro de uma vez
    Reduz de 3 requests AJAX para 1 único request
    """
    ano = request.GET.get('ano')
    partido = request.GET.get('partido')
    
    data = {
        'partidos': get_cached_partidos(ano) if ano else [],
        'candidatos': get_cached_candidatos(partido, ano) if partido and ano else [],
        'anos': get_cached_anos()
    }
    
    return JsonResponse(data)

# ==================== UTILITÁRIOS DE CACHE ====================

def clear_cache_by_pattern(pattern):
    """
    Limpa cache por padrão - útil para manutenção
    """
    try:
        from django.core.cache.utils import make_template_fragment_key
        cache.delete_pattern(f"*{pattern}*")
        return True
    except:
        return False

def get_cache_stats():
    """
    Retorna estatísticas do cache para monitoramento
    """
    stats = {
        'cache_keys': [],
        'total_size': 0,
        'hit_ratio': 0.0
    }
    
    try:
        # Implementar coleta de estatísticas baseado no backend de cache
        pass
    except:
        pass
    
    return stats

# ==================== VIEWS DE MANUTENÇÃO ====================

def clear_cache_view(request):
    """
    View para limpar cache manualmente (apenas para admins)
    """
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Acesso negado'}, status=403)
    
    try:
        cache.clear()
        return JsonResponse({'success': 'Cache limpo com sucesso'})
    except Exception as e:
        return JsonResponse({'error': f'Erro ao limpar cache: {str(e)}'}, status=500)

def cache_stats_view(request):
    """
    View para monitorar estatísticas do cache
    """
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Acesso negado'}, status=403)
    
    stats = get_cache_stats()
    return JsonResponse(stats)

# ==================== MIDDLEWARE DE PERFORMANCE ====================

class PerformanceMiddleware:
    """
    Middleware para monitorar performance das views
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.time()
        
        response = self.get_response(request)
        
        total_time = time.time() - start_time
        
        # Log views lentas
        if total_time > 2.0:
            print(f"View lenta: {request.path} - {total_time:.2f}s")
        
        # Adiciona header de performance
        response['X-Response-Time'] = f"{total_time:.3f}s"
        
        return response

# ==================== FUNÇÕES DE MONITORAMENTO ====================

def monitor_cache_performance(func):
    """
    Decorator para monitorar performance de funções com cache
    """
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        
        print(f"{func.__name__} executado em {end_time - start_time:.3f}s")
        return result
    
    return wrapper

# ==================== CONFIGURAÇÕES ADICIONAIS ====================

# Configuração para DEBUG
if settings.DEBUG:
    # Em desenvolvimento, use TTLs menores
    for key in CACHE_TIMES:
        CACHE_TIMES[key] = min(CACHE_TIMES[key], 300)  # Máximo 5 minutos

# Configuração de logging para performance
import logging

performance_logger = logging.getLogger('performance')
performance_logger.setLevel(logging.INFO)

def log_slow_operation(operation_name, duration, threshold=1.0):
    """
    Log operações lentas
    """
    if duration > threshold:
        performance_logger.warning(
            f"Operação lenta detectada: {operation_name} - {duration:.2f}s"
        )

# Correção da função generate_static_map_html para salvar em static/maps/ corretamente

def generate_static_map_html(votos_dict, total_votos, candidato_info):
    """Gera arquivo HTML do mapa salvo em static/maps e retorna a URL"""
    import os

    data_hash = hashlib.md5(
        f"{str(sorted(votos_dict.items()))}_{total_votos}_{candidato_info}".encode()
    ).hexdigest()

    file_name = f"{data_hash}.html"
    file_dir = os.path.join(settings.BASE_DIR, 'static', 'maps')  # novo local
    file_path = os.path.join(file_dir, file_name)
    file_url = settings.STATIC_URL + f"maps/{file_name}"

    os.makedirs(file_dir, exist_ok=True)  # garante que a pasta exista

    if not os.path.exists(file_path):
        mapa = fl.Map(
            location=[-22.928777, -43.423878],
            zoom_start=10,
            tiles='CartoDB positron',
            prefer_canvas=True,
            control_scale=False,
            attribution_control=False,
        )

        dados_list = [[bairro, votos] for bairro, votos in votos_dict.items()]
        geojson_path = os.path.join(settings.BASE_DIR, 'mapa_eleitoral', 'data', 'Limite_Bairro.geojson')

        try:
            fl.Choropleth(
                geo_data=geojson_path,
                name='choropleth',
                data=dados_list,
                columns=['Bairro', 'Votos'],
                key_on='feature.properties.NOME',
                fill_color='YlGn',
                nan_fill_color='#ff7575',
                fill_opacity=0.7,
                line_opacity=0.1,
                legend_name='Total de Votos',
                highlight=True,
                smooth_factor=2,
                bins=8,
            ).add_to(mapa)
        except Exception as e:
            print(f"Erro no Choropleth: {e}")

        geojson_data = load_geojson()
        for feature in geojson_data['features']:
            bairro_nome = feature['properties']['NOME']
            votos = votos_dict.get(bairro_nome, 0)
            votos_formatado = f"{votos:,}".replace(",", ".")
            porcentagem = (votos / total_votos * 100) if total_votos > 0 else 0

            feature['properties']['tooltip_content'] = f"""
                <b>{bairro_nome}</b><br>
                Votos: {votos_formatado}<br>
                {porcentagem:.1f}%
            """

        fl.GeoJson(
            geojson_data,
            name='Detalhes',
            style_function=lambda feature: {
                'fillColor': 'transparent',
                'color': 'black',
                'weight': 0.5,
                'fillOpacity': 0,
            },
            tooltip=fl.GeoJsonTooltip(
                fields=['tooltip_content'],
                aliases=[''],
                localize=True,
                sticky=False,
                labels=False,
                style="""
                    background-color: white;
                    color: #333333;
                    font-family: Arial;
                    font-size: 12px;
                    padding: 8px;
                    border: 1px solid #ccc;
                    border-radius: 3px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.2);
                """
            )
        ).add_to(mapa)

        fl.LayerControl().add_to(mapa)
        mapa.save(file_path)

        print(f"Mapa salvo em {file_path}")

    return file_url
# ==================== FIM DO CÓDIGO OTIMIZADO ====================
