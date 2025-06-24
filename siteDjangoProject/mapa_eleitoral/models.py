# mapa_eleitoral/models.py - VERSÃO OTIMIZADA
from django.db import models

class DadoEleitoral(models.Model):
    """
    Model otimizado com índices para performance
    """
    id = models.AutoField(primary_key=True)
    
    # Campos com índices otimizados
    ano_eleicao = models.CharField(
        max_length=4, 
        db_column='ANO_ELEICAO', 
        verbose_name="Ano da Eleição",
        db_index=True  # Índice para filtros por ano
    )
    sg_uf = models.CharField(max_length=2, db_column='SG_UF', verbose_name="Código UF")
    nm_ue = models.CharField(max_length=64, db_column='NM_UE', verbose_name="Nome da Unidade Eleitoral")
    ds_cargo = models.CharField(max_length=50, db_column='DS_CARGO', verbose_name="Descrição do Cargo")
    nr_candidato = models.CharField(max_length=8, db_column='NR_CANDIDATO', verbose_name="Número do Candidato")
    nm_candidato = models.CharField(max_length=64, db_column='NM_CANDIDATO', verbose_name="Nome do Candidato")
    nm_urna_candidato = models.CharField(
        max_length=64, 
        db_column='NM_URNA_CANDIDATO', 
        verbose_name="Nome na Urna",
        db_index=True  # Índice para buscas por candidato
    )
    nr_cpf_candidato = models.CharField(max_length=11, db_column='NR_CPF_CANDIDATO', verbose_name="CPF do Candidato")
    nr_partido = models.CharField(max_length=100, db_column='NR_PARTIDO', verbose_name="Número do Partido")
    sg_partido = models.CharField(
        max_length=10, 
        db_column='SG_PARTIDO', 
        verbose_name="Sigla do Partido",
        db_index=True  # Índice para filtros por partido
    )
    nr_turno = models.IntegerField(db_column='NR_TURNO', verbose_name="Número do Turno")
    qt_votos = models.DecimalField(max_digits=10, decimal_places=0, db_column='QT_VOTOS', verbose_name="Quantidade de Votos")
    nm_bairro = models.CharField(
        max_length=100, 
        db_column='NM_BAIRRO', 
        verbose_name="Nome do Bairro",
        db_index=True  # Índice para agregações por bairro
    )
    nr_latitude = models.CharField(max_length=100, db_column='NR_LATITUDE', verbose_name="Latitude")
    nr_longitude = models.CharField(max_length=100, db_column='NR_LONGITUDE', verbose_name="Longitude")
    
    class Meta:
        db_table = 'eleicoes_rio'  
        managed = False  # Não gerenciar a tabela (já existe)
        verbose_name = "Dado Eleitoral"
        verbose_name_plural = "Dados Eleitorais"
        
        # Índices compostos para queries frequentes
        indexes = [
            # Índice para a query principal da view
            models.Index(
                fields=['ano_eleicao', 'sg_partido', 'nm_urna_candidato'], 
                name='idx_ano_partido_candidato'
            ),
            # Índice para agregação por bairro
            models.Index(
                fields=['ano_eleicao', 'sg_partido', 'nm_urna_candidato', 'nm_bairro'], 
                name='idx_votos_bairro'
            ),
            # Índice para filtros AJAX
            models.Index(
                fields=['ano_eleicao', 'sg_partido'], 
                name='idx_filtros_ajax'
            ),
            # Índice para ordenação
            models.Index(
                fields=['-ano_eleicao', 'sg_partido'], 
                name='idx_ordenacao'
            ),
        ]
    
    def __str__(self):
        return f"{self.nm_urna_candidato} ({self.sg_partido}) - {self.nm_bairro}: {self.qt_votos} votos"

    @classmethod
    def get_anos_disponiveis(cls):
        """Método otimizado para buscar anos"""
        return cls.objects.values_list('ano_eleicao', flat=True).distinct().order_by('-ano_eleicao')
    
    @classmethod
    def get_partidos_por_ano(cls, ano):
        """Método otimizado para buscar partidos por ano"""
        return cls.objects.filter(ano_eleicao=ano).values_list('sg_partido', flat=True).distinct().order_by('sg_partido')
    
    @classmethod
    def get_candidatos_por_partido_ano(cls, ano, partido):
        """Método otimizado para buscar candidatos"""
        return cls.objects.filter(
            ano_eleicao=ano, 
            sg_partido=partido
        ).values_list('nm_urna_candidato', flat=True).distinct().order_by('nm_urna_candidato')
    
    @classmethod
    def get_votos_por_bairro(cls, ano, partido, candidato):
        """Método otimizado para agregar votos por bairro"""
        from django.db.models import Sum
        return cls.objects.filter(
            ano_eleicao=ano,
            sg_partido=partido,
            nm_urna_candidato=candidato
        ).values('nm_bairro').annotate(
            total_votos=Sum('qt_votos')
        ).order_by('nm_bairro')