# VIEWS.PY COMPLETO E MAIS SUCINTO (OTIMIZADO)

from django.shortcuts import render
from django.http import JsonResponse
from django.core.cache import cache
from django.views.decorators.cache import cache_page
from django.conf import settings
from django.templatetags.static import static
import os, json, time, hashlib, logging
from decimal import Decimal
import folium as fl
from folium.features import GeoJsonTooltip
from .models import DadoEleitoral

# === CONFIGURAÇÃO CACHE ===
CACHE_TIMES = {k: 86400 for k in ['geojson_data', 'map_html', 'candidato_info']} | {
    'anos_eleicao': 86400,
    'partidos': 43200,
    'candidatos': 43200,
    'votos_bairro': 21600,
    'complete_data': 43200
}
if settings.DEBUG:
    for k in CACHE_TIMES: CACHE_TIMES[k] = min(CACHE_TIMES[k], 300)

# === CACHE UTIL ===
def safe_key(prefix, *args):
    return f"{prefix}_" + hashlib.md5("_".join(map(str, args)).encode()).hexdigest()

def cached_qs(query, key, ttl):
    res = cache.get(key)
    if res is None:
        res = list(query)
        cache.set(key, res, ttl)
    return res

def load_geojson():
    key = 'geojson_data'
    g = cache.get(key)
    if g is None:
        with open(os.path.join(settings.BASE_DIR, 'mapa_eleitoral', 'data', 'Limite_Bairro.geojson'), 'r', encoding='utf-8') as f:
            g = json.load(f)
        cache.set(key, g, CACHE_TIMES[key])
    return g

# === GETTERS OTIMIZADOS ===

def get_cached_anos():
    return cached_qs(
        DadoEleitoral.objects.values_list('ano_eleicao', flat=True).distinct().order_by('-ano_eleicao'),
        'anos_eleicao', CACHE_TIMES['anos_eleicao'])

def get_cached_partidos(ano):
    q = DadoEleitoral.objects.filter(ano_eleicao=ano) if ano else DadoEleitoral.objects
    return cached_qs(
        q.values_list('sg_partido', flat=True).distinct().order_by('sg_partido'),
        safe_key('partidos', ano or 'all'), CACHE_TIMES['partidos'])

def get_cached_candidatos(partido, ano):
    q = DadoEleitoral.objects.all()
    if ano: q = q.filter(ano_eleicao=ano)
    if partido: q = q.filter(sg_partido=partido)
    return cached_qs(
        q.values_list('nm_urna_candidato', flat=True).distinct().order_by('nm_urna_candidato'),
        safe_key('candidatos', partido, ano), CACHE_TIMES['candidatos'])

def get_complete_candidate_data(candidato, partido, ano):
    key = safe_key('complete_data', candidato, partido, ano)
    data = cache.get(key)
    if data:
        return data

    q = DadoEleitoral.objects.filter(
        ano_eleicao=ano, sg_partido=partido, nm_urna_candidato=candidato
    )
    valores = q.values('nm_bairro', 'qt_votos', 'ds_cargo', 'nm_urna_candidato').order_by('nm_bairro')

    if not valores:
        return None  # evita erro se não houver registros

    votos_dict, total = {}, 0
    for item in valores:
        b = item['nm_bairro']
        v = int(item['qt_votos']) if isinstance(item['qt_votos'], (Decimal, int, float)) else 0
        votos_dict[b] = votos_dict.get(b, 0) + v
        total += v

    info = {
        'nome': valores[0]['nm_urna_candidato'],
        'cargo': valores[0]['ds_cargo'],
        'ano': ano,
        'votos_total': total
    }
    data = {'votos_dict': votos_dict, 'total_votos': total, 'candidato_info': info}
    cache.set(key, data, CACHE_TIMES['complete_data'])
    return data


# === GERA MAPA COMO ARQUIVO HTML ===
def generate_static_map_html(votos_dict, total_votos, info):
    h = hashlib.md5(f"{str(sorted(votos_dict.items()))}_{total_votos}_{info}".encode()).hexdigest()
    fname = f"{h}.html"
    path = os.path.join(settings.BASE_DIR, 'static', 'maps', fname)
    url = settings.STATIC_URL + f"maps/{fname}"
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if not os.path.exists(path):
        m = fl.Map(location=[-22.928777, -43.423878], zoom_start=10, tiles='CartoDB positron', prefer_canvas=True,
                   control_scale=False, width='100%', height='100%', attribution_control=False)
        try:
            fl.Choropleth(
                geo_data=os.path.join(settings.BASE_DIR, 'mapa_eleitoral', 'data', 'Limite_Bairro.geojson'),
                name='choropleth',
                data=[[k, v] for k, v in votos_dict.items()],
                columns=['Bairro', 'Votos'],
                key_on='feature.properties.NOME',
                fill_color='YlGn', nan_fill_color='#ff7575', fill_opacity=0.7,
                line_opacity=0.1, legend_name='Total de Votos', highlight=True, smooth_factor=2, bins=8
            ).add_to(m)
        except Exception as e:
            print(f"Erro no Choropleth: {e}")

        gjson = load_geojson()
        for f in gjson['features']:
            b = f['properties']['NOME']
            v = votos_dict.get(b, 0)
            f['properties']['tooltip_content'] = f"<b>{b}</b><br>Votos: {v:,}<br>{(v / total_votos * 100):.1f}%" if total_votos else ""

        fl.GeoJson(
            gjson,
            name='Detalhes',
            style_function=lambda f: {'fillColor': 'transparent', 'color': 'black', 'weight': 0.5, 'fillOpacity': 0},
            tooltip=GeoJsonTooltip(fields=['tooltip_content'], aliases=[''], localize=True, sticky=False,
                                    labels=False, style="background:white;color:#333;padding:6px;border-radius:4px;")
        ).add_to(m)
        fl.LayerControl().add_to(m)
        m.save(path)
    return url

# === VIEW PRINCIPAL ===
def home_view(request):
    anos = get_cached_anos()
    ano = request.GET.get('ano') or '2024'
    partidos = get_cached_partidos(ano)
    partido = request.GET.get('partido') or ('PSD' if 'PSD' in partidos else (partidos[0] if partidos else ''))
    candidatos = get_cached_candidatos(partido, ano)
    candidato = request.GET.get('candidato') or ('EDUARDO PAES' if 'EDUARDO PAES' in candidatos else (candidatos[0] if candidatos else ''))
    mapa_url = info = ''

    if candidato and ano:
        d = get_complete_candidate_data(candidato, partido, ano)
        if d:
            mapa_url = generate_static_map_html(d['votos_dict'], d['total_votos'], d['candidato_info'])
            info = d['candidato_info']

    return render(request, 'home.html', {
        'anos': anos,
        'partidos': partidos,
        'candidatos': candidatos,
        'selected_ano': ano,
        'selected_partido': partido,
        'selected_candidato': candidato,
        'candidato_info': info,
        'map_url': mapa_url
    })

# === APIs AJAX ===
@cache_page(3600)
def get_anos_ajax(r): return JsonResponse({'anos': get_cached_anos()})

@cache_page(1800)
def get_candidatos_ajax(r):
    p, a = r.GET.get('partido'), r.GET.get('ano')
    return JsonResponse({'candidatos': get_cached_candidatos(p, a) if p else []})

@cache_page(3600)
def get_partidos_ajax(r):
    a = r.GET.get('ano')
    return JsonResponse({'partidos': get_cached_partidos(a) if a else []})

@cache_page(900)
def get_filter_data_ajax(r):
    a, p = r.GET.get('ano'), r.GET.get('partido')
    return JsonResponse({
        'anos': get_cached_anos(),
        'partidos': get_cached_partidos(a) if a else [],
        'candidatos': get_cached_candidatos(p, a) if a and p else []
    })

# === MANUTENÇÃO ===
def clear_cache_view(r):
    if not r.user.is_superuser: return JsonResponse({'error': 'Acesso negado'}, status=403)
    cache.clear(); return JsonResponse({'success': 'Cache limpo com sucesso'})

def cache_stats_view(r):
    if not r.user.is_superuser: return JsonResponse({'error': 'Acesso negado'}, status=403)
    return JsonResponse({'msg': 'Stats ainda não implementadas'})

# === MIDDLEWARE DE PERFORMANCE ===
class PerformanceMiddleware:
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        t0 = time.time()
        resp = self.get_response(request)
        dur = time.time() - t0
        if dur > 2.0: print(f"View lenta: {request.path} - {dur:.2f}s")
        resp['X-Response-Time'] = f"{dur:.3f}s"
