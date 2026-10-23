"""In-memory (RAM) reference snapshot of Anatel data (RQUAL/IQS, network indicators,
complaints/IDA and the satisfaction survey).

Used as an instant fallback (SLA < 3 s for Gemini Enterprise actions) whenever Anatel's
HTTP/FTP portal is slow or unavailable. Values are illustrative reference figures; the
response metadata marks them as ``origem_leitura="fallback_seed_ram"``.
"""

from typing import Any

import polars as pl


def _compute_selo(iqs: float) -> str:
    if iqs >= 8.50:
        return "A"
    if iqs >= 7.50:
        return "B"
    if iqs >= 6.00:
        return "C"
    if iqs >= 4.50:
        return "D"
    return "E"


def build_fallback_rqual_iqs() -> pl.DataFrame:
    """Builds the RQUAL seal / IQS DataFrame by operator, service, state and municipality."""
    base_profiles = [
        # (operadora, grupo, servicos, ufs_principais, base_iqs)
        ("VIVO", "TELEFONICA BRASIL", ["SMP", "SCM", "STFC"], ["BR", "SP", "RJ", "MG", "PR", "SC", "RS", "BA", "PE", "CE", "DF", "GO", "PA", "AM"], 8.55),
        ("CLARO", "CLARO S.A.", ["SMP", "SCM", "STFC"], ["BR", "SP", "RJ", "MG", "PR", "SC", "RS", "BA", "PE", "CE", "DF", "GO", "PA", "AM"], 8.40),
        ("TIM", "TIM S.A.", ["SMP", "SCM", "STFC"], ["BR", "SP", "RJ", "MG", "PR", "SC", "RS", "BA", "PE", "CE", "DF", "GO", "PA", "AM"], 8.25),
        ("OI", "OI / NIO", ["SCM", "STFC"], ["BR", "RJ", "MG", "PR", "RS", "BA", "PE", "CE", "DF", "GO", "PA"], 7.45),
        ("BRISANET", "BRISANET", ["SCM", "SMP"], ["BR", "CE", "PE", "BA", "RN", "PB"], 8.75),
        ("ALGAR", "ALGAR TELECOM", ["SCM", "SMP", "STFC"], ["BR", "MG", "SP", "GO", "DF"], 8.62),
        ("UNIFIQUE", "UNIFIQUE", ["SCM", "SMP"], ["BR", "SC", "RS", "PR"], 8.88),
        ("DESKTOP", "DESKTOP S.A.", ["SCM"], ["BR", "SP"], 8.32),
        ("VERO", "VERO AMERICANET", ["SCM"], ["BR", "MG", "SP", "RS", "PR", "GO"], 8.38),
    ]

    municipios_por_uf: dict[str, list[tuple[str, str, float]]] = {
        "BR": [("NACIONAL (CONSOLIDADO)", "0000000", 0.0)],
        "SP": [
            ("ESTADUAL (CONSOLIDADO)", "3500000", 0.0),
            ("SAO PAULO", "3550308", 0.08),
            ("CAMPINAS", "3509502", 0.12),
            ("RIBEIRAO PRETO", "3543402", 0.05),
            ("SANTOS", "3548500", -0.04),
        ],
        "RJ": [
            ("ESTADUAL (CONSOLIDADO)", "3300000", 0.0),
            ("RIO DE JANEIRO", "3304557", -0.05),
            ("NITEROI", "3303302", 0.14),
        ],
        "MG": [
            ("ESTADUAL (CONSOLIDADO)", "3100000", 0.0),
            ("BELO HORIZONTE", "3106200", 0.09),
            ("UBERLANDIA", "3170206", 0.18),
        ],
        "PR": [
            ("ESTADUAL (CONSOLIDADO)", "4100000", 0.0),
            ("CURITIBA", "4106902", 0.15),
            ("LONDRINA", "4113700", 0.10),
        ],
        "SC": [
            ("ESTADUAL (CONSOLIDADO)", "4200000", 0.0),
            ("FLORIANOPOLIS", "4205407", 0.16),
            ("JOINVILLE", "4209102", 0.20),
            ("BLUMENAU", "4202404", 0.22),
        ],
        "RS": [
            ("ESTADUAL (CONSOLIDADO)", "4300000", 0.0),
            ("PORTO ALEGRE", "4314902", 0.07),
            ("CAXIAS DO SUL", "4305108", 0.14),
        ],
        "BA": [
            ("ESTADUAL (CONSOLIDADO)", "2900000", 0.0),
            ("SALVADOR", "2927408", 0.04),
            ("FEIRA DE SANTANA", "2910800", -0.06),
        ],
        "PE": [
            ("ESTADUAL (CONSOLIDADO)", "2600000", 0.0),
            ("RECIFE", "2611606", 0.06),
            ("CARUARU", "2604106", 0.11),
        ],
        "CE": [
            ("ESTADUAL (CONSOLIDADO)", "2300000", 0.0),
            ("FORTALEZA", "2304400", 0.12),
            ("JUAZEIRO DO NORTE", "2307304", 0.19),
        ],
        "DF": [
            ("ESTADUAL (CONSOLIDADO)", "5300000", 0.0),
            ("BRASILIA", "5300108", 0.14),
        ],
        "GO": [
            ("ESTADUAL (CONSOLIDADO)", "5200000", 0.0),
            ("GOIANIA", "5208707", 0.08),
        ],
        "PA": [
            ("ESTADUAL (CONSOLIDADO)", "1500000", 0.0),
            ("BELEM", "1501402", -0.18),
        ],
        "AM": [
            ("ESTADUAL (CONSOLIDADO)", "1300000", 0.0),
            ("MANAUS", "1302603", -0.22),
        ],
    }

    periodos = [("2025-06", -0.12), ("2025-12", -0.05), ("2026-06", 0.0)]
    service_deltas = {"SCM": 0.15, "SMP": 0.0, "STFC": -0.65}

    rows: list[dict[str, Any]] = []
    for operadora, grupo, servicos, ufs, base_iqs in base_profiles:
        for servico in servicos:
            s_delta = service_deltas.get(servico, 0.0)
            for uf in ufs:
                muns = municipios_por_uf.get(uf, [("ESTADUAL (CONSOLIDADO)", "0000000", 0.0)])
                for mun_nome, cod_ibge, m_delta in muns:
                    for ano_mes, p_delta in periodos:
                        iqs = round(min(9.85, max(3.80, base_iqs + s_delta + m_delta + p_delta)), 2)
                        rows.append(
                            {
                                "ano_mes": ano_mes,
                                "servico": servico,
                                "operadora": operadora,
                                "grupo_economico": grupo,
                                "uf": uf,
                                "municipio": mun_nome,
                                "codigo_ibge": cod_ibge,
                                "nota_iqs": iqs,
                                "selo_rqual": _compute_selo(iqs),
                            }
                        )
    return pl.DataFrame(rows)


def build_fallback_indicadores_rede() -> pl.DataFrame:
    """Builds the network-quality indicators DataFrame (RQUAL / ESAQ)."""
    operadoras_perf = [
        ("UNIFIQUE", ["SCM", "SMP"], ["BR", "SC", "RS", "PR"], 98.4, 98.1, 14.2, 4.1, 0.18, 99.65),
        ("BRISANET", ["SCM", "SMP"], ["BR", "CE", "PE", "BA"], 97.9, 97.5, 18.5, 5.2, 0.24, 99.52),
        ("ALGAR", ["SCM", "SMP"], ["BR", "MG", "SP", "GO", "DF"], 97.6, 97.2, 16.8, 4.8, 0.22, 99.48),
        ("VIVO", ["SCM", "SMP"], ["BR", "SP", "RJ", "MG", "PR", "SC", "RS", "BA", "PE", "CE", "DF", "GO"], 97.2, 96.8, 17.4, 5.5, 0.28, 99.42),
        ("CLARO", ["SCM", "SMP"], ["BR", "SP", "RJ", "MG", "PR", "SC", "RS", "BA", "PE", "CE", "DF", "GO"], 96.8, 95.9, 19.8, 6.4, 0.35, 99.31),
        ("TIM", ["SCM", "SMP"], ["BR", "SP", "RJ", "MG", "PR", "SC", "RS", "BA", "PE", "CE", "DF", "GO"], 96.3, 95.6, 21.2, 6.9, 0.39, 99.25),
        ("VERO", ["SCM"], ["BR", "MG", "SP", "RS", "PR", "GO"], 96.7, 96.3, 18.1, 5.4, 0.31, 99.36),
        ("DESKTOP", ["SCM"], ["BR", "SP"], 96.4, 96.0, 17.9, 5.6, 0.33, 99.30),
        ("OI", ["SCM"], ["BR", "RJ", "MG", "PR", "RS", "BA", "PE", "CE", "DF", "GO"], 94.1, 93.5, 27.6, 9.8, 0.78, 98.75),
    ]

    city_map = {
        "BR": "NACIONAL (CONSOLIDADO)",
        "SP": "SAO PAULO",
        "RJ": "RIO DE JANEIRO",
        "MG": "BELO HORIZONTE",
        "PR": "CURITIBA",
        "SC": "FLORIANOPOLIS",
        "RS": "PORTO ALEGRE",
        "BA": "SALVADOR",
        "PE": "RECIFE",
        "CE": "FORTALEZA",
        "DF": "BRASILIA",
        "GO": "GOIANIA",
    }

    periodos = [("2026-07", -0.2), ("2026-08", -0.1), ("2026-09", 0.0)]
    rows: list[dict[str, Any]] = []

    for op, servicos, ufs, dl_base, ul_base, lat_base, jit_base, loss_base, disp_base in operadoras_perf:
        for servico in servicos:
            is_smp = servico == "SMP"
            for uf in ufs:
                municipio = city_map.get(uf, "ESTADUAL (CONSOLIDADO)")
                for ano_mes, p_adj in periodos:
                    dl_val = round(dl_base - (1.1 if is_smp else 0.0) + p_adj, 2)
                    ul_val = round(ul_base - (1.4 if is_smp else 0.0) + p_adj, 2)
                    lat_val = round(lat_base + (6.5 if is_smp else 0.0) - p_adj * 2, 2)
                    jit_val = round(jit_base + (2.3 if is_smp else 0.0) - p_adj, 2)
                    loss_val = round(max(0.05, loss_base + (0.15 if is_smp else 0.0)), 2)
                    disp_val = round(min(99.95, disp_base - (0.15 if is_smp else 0.0) + p_adj * 0.1), 2)

                    metric_specs = [
                        ("velocidade_download", dl_val, 95.0, "%", dl_val >= 95.0),
                        ("velocidade_upload", ul_val, 95.0, "%", ul_val >= 95.0),
                        ("latencia", lat_val, 50.0, "ms", lat_val <= 50.0),
                        ("jitter", jit_val, 25.0, "ms", jit_val <= 25.0),
                        ("perda_pacotes", loss_val, 1.0, "%", loss_val <= 1.0),
                        ("disponibilidade", disp_val, 99.0, "%", disp_val >= 99.0),
                    ]
                    for ind_name, val, meta, unit, cumpriu in metric_specs:
                        rows.append(
                            {
                                "ano_mes": ano_mes,
                                "servico": servico,
                                "operadora": op,
                                "uf": uf,
                                "municipio": municipio,
                                "indicador": ind_name,
                                "valor_medido": val,
                                "meta_referencia": meta,
                                "unidade": unit,
                                "cumpriu_meta": cumpriu,
                            }
                        )
    return pl.DataFrame(rows)


def build_fallback_reclamacoes_ida() -> pl.DataFrame:
    """Builds the complaints (Anatel Consumidor) and IDA DataFrame."""
    perfis_reclamacoes = [
        # (operadora, servicos, ufs, base_vol, ind_1000, motivo_principal, resolucao_pct, prazo_dias, nota_ida)
        ("UNIFIQUE", ["SCM", "SMP"], ["BR", "SC", "RS", "PR"], 180, 0.42, "Qualidade, funcionamento e reparo técnico", 91.8, 3.1, 93.4),
        ("BRISANET", ["SCM", "SMP"], ["BR", "CE", "PE", "BA"], 340, 0.51, "Qualidade, funcionamento e reparo técnico", 89.6, 3.6, 91.2),
        ("ALGAR", ["SCM", "SMP", "STFC"], ["BR", "MG", "SP", "GO", "DF"], 420, 0.58, "Cobrança indevida / Faturamento", 88.4, 3.9, 89.8),
        ("VERO", ["SCM"], ["BR", "MG", "SP", "RS", "PR", "GO"], 390, 0.64, "Qualidade, funcionamento e reparo técnico", 86.5, 4.2, 87.9),
        ("DESKTOP", ["SCM"], ["BR", "SP"], 510, 0.72, "Qualidade, funcionamento e reparo técnico", 85.1, 4.5, 86.4),
        ("VIVO", ["SMP", "SCM", "STFC"], ["BR", "SP", "RJ", "MG", "PR", "SC", "RS", "BA", "PE", "CE", "DF", "GO"], 14200, 0.85, "Cobrança indevida / Faturamento", 83.2, 4.9, 84.7),
        ("TIM", ["SMP", "SCM", "STFC"], ["BR", "SP", "RJ", "MG", "PR", "SC", "RS", "BA", "PE", "CE", "DF", "GO"], 11800, 0.91, "Cobrança indevida / Faturamento", 81.9, 5.2, 83.1),
        ("CLARO", ["SMP", "SCM", "STFC"], ["BR", "SP", "RJ", "MG", "PR", "SC", "RS", "BA", "PE", "CE", "DF", "GO"], 15600, 0.96, "Cancelamento de serviço não atendido", 81.4, 5.4, 82.5),
        ("OI", ["SCM", "STFC"], ["BR", "RJ", "MG", "PR", "RS", "BA", "PE", "CE", "DF", "GO"], 6900, 1.48, "Qualidade, funcionamento e reparo técnico", 74.6, 6.8, 75.2),
    ]

    uf_scale = {
        "BR": 1.0,
        "SP": 0.32,
        "RJ": 0.14,
        "MG": 0.12,
        "PR": 0.07,
        "RS": 0.06,
        "SC": 0.05,
        "BA": 0.06,
        "PE": 0.05,
        "CE": 0.05,
        "DF": 0.04,
        "GO": 0.04,
    }

    periodos = [("2026-07", 1.03), ("2026-08", 1.01), ("2026-09", 0.98)]
    rows: list[dict[str, Any]] = []

    for op, servicos, ufs, base_vol, ind_1000, motivo, res_pct, prazo, ida in perfis_reclamacoes:
        for servico in servicos:
            serv_mult = 1.0 if servico == "SMP" else (0.65 if servico == "SCM" else 0.25)
            for uf in ufs:
                scale = uf_scale.get(uf, 0.04)
                for ano_mes, p_factor in periodos:
                    vol = max(12, int(base_vol * scale * serv_mult * p_factor))
                    rows.append(
                        {
                            "ano_mes": ano_mes,
                            "servico": servico,
                            "operadora": op,
                            "uf": uf,
                            "total_reclamacoes": vol,
                            "indice_reclamacoes_1000_acessos": round(ind_1000 * p_factor, 2),
                            "principal_motivo": motivo,
                            "taxa_resolucao_pct": round(min(98.0, res_pct / p_factor), 2),
                            "prazo_medio_dias": round(prazo * p_factor, 2),
                            "nota_ida": round(min(99.0, ida / p_factor), 2),
                        }
                    )
    return pl.DataFrame(rows)


def build_fallback_pesquisa_satisfacao() -> pl.DataFrame:
    """Builds the satisfaction / perceived-quality survey (ISG) DataFrame."""
    perfis_satisfacao = [
        # (operadora, servicos, ufs, isg_base, func_base, atend_base, cob_base, amostra)
        ("UNIFIQUE", ["SCM", "SMP"], ["BR", "SC", "RS", "PR"], 8.42, 8.75, 8.30, 8.55, 2400),
        ("BRISANET", ["SCM", "SMP"], ["BR", "CE", "PE", "BA"], 8.18, 8.48, 8.05, 8.22, 3100),
        ("ALGAR", ["SCM", "SMP", "STFC"], ["BR", "MG", "SP", "GO", "DF"], 7.95, 8.20, 7.82, 8.04, 2800),
        ("VERO", ["SCM"], ["BR", "MG", "SP", "RS", "PR", "GO"], 7.84, 8.12, 7.65, 7.90, 2100),
        ("DESKTOP", ["SCM"], ["BR", "SP"], 7.68, 7.96, 7.45, 7.72, 1950),
        ("VIVO", ["SMP", "SCM", "STFC"], ["BR", "SP", "RJ", "MG", "PR", "SC", "RS", "BA", "PE", "CE", "DF", "GO"], 7.62, 7.95, 7.32, 7.58, 18500),
        ("TIM", ["SMP", "SCM", "STFC"], ["BR", "SP", "RJ", "MG", "PR", "SC", "RS", "BA", "PE", "CE", "DF", "GO"], 7.45, 7.74, 7.18, 7.42, 16200),
        ("CLARO", ["SMP", "SCM", "STFC"], ["BR", "SP", "RJ", "MG", "PR", "SC", "RS", "BA", "PE", "CE", "DF", "GO"], 7.40, 7.78, 7.10, 7.31, 17800),
        ("OI", ["SCM", "STFC"], ["BR", "RJ", "MG", "PR", "RS", "BA", "PE", "CE", "DF", "GO"], 6.85, 7.12, 6.54, 6.88, 9400),
    ]

    anos = [(2024, -0.14), (2025, 0.0)]
    rows: list[dict[str, Any]] = []

    for op, servicos, ufs, isg, func, atend, cob, amostra in perfis_satisfacao:
        for servico in servicos:
            s_adj = 0.12 if servico == "SCM" else (0.0 if servico == "SMP" else -0.35)
            for uf in ufs:
                uf_adj = 0.05 if uf in ("SC", "PR", "SP", "DF") else (-0.05 if uf in ("RJ", "BA") else 0.0)
                for ano, a_adj in anos:
                    rows.append(
                        {
                            "ano": ano,
                            "servico": servico,
                            "operadora": op,
                            "uf": uf,
                            "nota_isg": round(isg + s_adj + uf_adj + a_adj, 2),
                            "nota_funcionamento": round(func + s_adj + uf_adj + a_adj, 2),
                            "nota_atendimento": round(atend + s_adj + uf_adj + a_adj, 2),
                            "nota_cobranca": round(cob + s_adj + uf_adj + a_adj, 2),
                            "amostra_entrevistados": amostra if uf == "BR" else max(250, amostra // 10),
                        }
                    )
    return pl.DataFrame(rows)


FALLBACK_CKAN_PACKAGES: list[dict[str, Any]] = [
    {
        "id": "rqual-indicadores-qualidade-telecom",
        "name": "indicadores-de-qualidade-rqual",
        "title": "RQUAL — Indicadores de Qualidade e Selo de Qualidade (IQS, IQR, IQP)",
        "notes": "Conjunto de dados oficial da Anatel contendo notas do IQS, Selos de Qualidade (A a E) e indicadores operacionais de rede (velocidade, latência, jitter, perda de pacotes e disponibilidade) por UF e município.",
        "organization": "Agência Nacional de Telecomunicações (Anatel)",
        "url": "https://www.anatel.gov.br/dadosabertos/paineis_de_dados/qualidade/qualidade_rqual.zip",
        "format": "ZIP/CSV",
        "frequency": "Mensal / Semestral (Selos)",
    },
    {
        "id": "anatel-consumidor-reclamacoes-ida",
        "name": "reclamacoes-anatel-consumidor-ida",
        "title": "Anatel Consumidor — Solicitações, Reclamações e Índice de Desempenho no Atendimento (IDA)",
        "notes": "Histórico mensal de reclamações registradas no Anatel Consumidor, motivos de reclamação, taxa de resolução, prazo médio de resposta e ranking do IDA por operadora, serviço e UF.",
        "organization": "Agência Nacional de Telecomunicações (Anatel)",
        "url": "https://www.anatel.gov.br/dadosabertos/paineis_de_dados/consumidor/reclamacoes_contexto.zip",
        "format": "ZIP/CSV",
        "frequency": "Mensal",
    },
    {
        "id": "anatel-pesquisa-satisfacao-qualidade-percebida",
        "name": "pesquisa-satisfacao-e-qualidade-percebida",
        "title": "Pesquisa de Satisfação e Qualidade Percebida dos Consumidores de Telecomunicações",
        "notes": "Resultados anuais do Índice de Satisfação Geral (ISG) e avaliação de funcionamento, atendimento telefônico/digital e cobrança/recarga para SMP, SCM, STFC e SeAC em todas as UFs.",
        "organization": "Agência Nacional de Telecomunicações (Anatel)",
        "url": "https://www.anatel.gov.br/dadosabertos/paineis_de_dados/consumidor/pesquisa_satisfacao.zip",
        "format": "ZIP/CSV",
        "frequency": "Anual",
    },
]
