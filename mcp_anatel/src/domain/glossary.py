from typing import Any

ANATEL_GLOSSARY: dict[str, dict[str, Any]] = {
    "rqual_iqs": {
        "titulo": "RQUAL (Regulamento de Qualidade dos Serviços de Telecomunicações) e IQS",
        "base_legal": "Resolução Anatel nº 717/2019",
        "descricao": (
            "O RQUAL substituiu o modelo punitivo tradicional por um modelo de regulação responsiva "
            "baseado em transparência e competição, atribuindo Selos de Qualidade (A, B, C, D ou E) "
            "a partir do IQS (Índice de Qualidade do Serviço), além do IQR (Reclamações) e IQP (Qualidade Percebida)."
        ),
        "escala_selos": {
            "A": "Excelente (IQS >= 8.50) — Alto padrão de cumprimento de metas técnicas e satisfação.",
            "B": "Bom (7.50 <= IQS < 8.50) — Desempenho acima da média regulatória.",
            "C": "Regular (6.00 <= IQS < 7.50) — Cumprimento básico, com pontos de atenção em horários de pico.",
            "D": "Insuficiente (4.50 <= IQS < 6.00) — Descumprimento recorrente de indicadores em municípios/UFs.",
            "E": "Crítico (IQS < 4.50) — Sujeito a medidas cautelares e planos de ação obrigatórios da Anatel.",
        },
        "periodicidade": "Semestral para os Selos RQUAL e mensal para coleta dos indicadores operacionais.",
    },
    "indicadores_rede": {
        "titulo": "Indicadores Operacionais de Qualidade de Rede (RQUAL / ESAQ)",
        "entidade_aferidora": "ESAQ (Entidade de Suporte à Aferição da Qualidade) / Medições Anatel",
        "indicadores": {
            "velocidade_download": {
                "nome": "Cumprimento da Velocidade de Download (%)",
                "meta_referencia": 95.0,
                "unidade": "% de medições conformes",
                "explicacao": "Percentual de medições de download que atingem o patamar contratado/regulatório.",
            },
            "velocidade_upload": {
                "nome": "Cumprimento da Velocidade de Upload (%)",
                "meta_referencia": 95.0,
                "unidade": "% de medições conformes",
                "explicacao": "Percentual de medições de upload que atingem o patamar contratado/regulatório.",
            },
            "latencia": {
                "nome": "Latência Bidirecional (ms)",
                "meta_referencia": 50.0,
                "unidade": "ms (menor é melhor)",
                "explicacao": "Tempo de ida e volta de pacotes (RTT). Meta típica <= 50ms em SCM/SMP.",
            },
            "jitter": {
                "nome": "Jitter / Variação de Latência (ms)",
                "meta_referencia": 25.0,
                "unidade": "ms (menor é melhor)",
                "explicacao": "Estabilidade da latência para aplicações de tempo real (voz, vídeo, jogos).",
            },
            "perda_pacotes": {
                "nome": "Perda de Pacotes (%)",
                "meta_referencia": 1.0,
                "unidade": "% (menor é melhor)",
                "explicacao": "Fração de pacotes não entregues na transmissão fim a fim. Meta <= 1,0%.",
            },
            "disponibilidade": {
                "nome": "Disponibilidade da Rede / Infraestrutura (%)",
                "meta_referencia": 99.0,
                "unidade": "% de tempo ativo",
                "explicacao": "Percentual do tempo em que a rede permanece ativa sem interrupções críticas.",
            },
        },
    },
    "reclamacoes_ida": {
        "titulo": "Anatel Consumidor (Reclamações) e IDA (Índice de Desempenho no Atendimento)",
        "base_legal": "Resolução Anatel nº 632/2014 (RGC) e Novo RGC (Resolução nº 765/2023)",
        "metricas": {
            "indice_reclamacoes_1000_acessos": (
                "Volume mensal de reclamações registradas na Anatel dividido por cada 1.000 acessos "
                "em serviço da operadora na UF/serviço (menor é melhor)."
            ),
            "taxa_resolucao_pct": (
                "Percentual de demandas resolvidas na primeira resposta sem necessidade de reabertura."
            ),
            "prazo_medio_dias": (
                "Tempo médio (em dias corridos) que a prestadora leva para responder ao consumidor (prazo RGC: até 10 dias)."
            ),
            "nota_ida": (
                "Nota de 0 a 100 do Índice de Desempenho no Atendimento da Anatel, combinando volume de "
                "reclamações, índice de resolução, taxa de reabertura e tempo médio de resposta."
            ),
        },
        "principais_motivos": [
            "Cobrança indevida / Faturamento",
            "Qualidade, funcionamento e reparo técnico",
            "Cancelamento de serviço não atendido",
            "Oferta, promoção e fidelização",
            "Portabilidade numérica e bloqueio",
        ],
    },
    "pesquisa_satisfacao": {
        "titulo": "Pesquisa de Satisfação e Qualidade Percebida da Anatel",
        "descricao": (
            "Pesquisa anual realizada pela Anatel entrevistando dezenas de milhares de consumidores "
            "em todas as 27 UFs para aferir a percepção real sobre as prestadoras (escala de 0 a 10)."
        ),
        "dimensoes": {
            "nota_isg": "ISG (Índice de Satisfação Geral) — Nota de 0 a 10 da satisfação global do cliente.",
            "nota_funcionamento": "Qualidade do funcionamento (estabilidade do sinal/fibra, velocidade e chamadas).",
            "nota_atendimento": "Qualidade do atendimento telefônico e canais digitais (app, WhatsApp, site).",
            "nota_cobranca": "Clareza e correção na fatura (pós-pago/banda larga) ou validade de recarga (pré-pago).",
        },
    },
    "servicos_operadoras": {
        "titulo": "Siglas de Serviços e Grupos Econômicos na Anatel",
        "servicos": {
            "SMP": "Serviço Móvel Pessoal (Telefonia Móvel / Celular 4G e 5G)",
            "SCM": "Serviço de Comunicação Multimídia (Banda Larga Fixa / Fibra Óptica)",
            "STFC": "Serviço Telefônico Fixo Comutado (Telefonia Fixa)",
            "SeAC": "Serviço de Acesso Condicionado (TV por Assinatura)",
        },
        "mapeamento_operadoras": {
            "VIVO": "Telefônica Brasil S.A. (Vivo / Fibra / Móvel)",
            "CLARO": "Claro S.A. (Claro / NET / Embratel)",
            "TIM": "TIM S.A. (TIM Brasil / TIM UltraFibra)",
            "OI": "Oi S.A. / Nio (Operação de Fibra e Legado)",
            "BRISANET": "Brisanet Telecomunicações S.A. (Forte presença no Nordeste em SCM e SMP 5G)",
            "ALGAR": "Algar Telecom S.A. (MG, SP, GO, MS e corporativo nacional)",
            "UNIFIQUE": "Unifique Telecomunicações S.A. (Região Sul - SC, RS, PR)",
            "DESKTOP": "Desktop S.A. (Interior e Região Metropolitana de SP)",
            "VERO": "Vero S.A. / Americanet (MG, Sul, SP e Centro-Oeste)",
        },
    },
}


def get_glossary_content(topico: str | None = None) -> dict[str, Any]:
    """Returns the full regulatory glossary or the entry for one Anatel topic."""
    if not topico or topico.strip().lower() in ("geral", "todos", "all", "*"):
        return ANATEL_GLOSSARY
    key = topico.strip().lower()
    if key in ANATEL_GLOSSARY:
        return {key: ANATEL_GLOSSARY[key]}
    # Partial match on the topic id
    matched = {k: v for k, v in ANATEL_GLOSSARY.items() if key in k or key in v.get("titulo", "").lower()}
    return matched if matched else ANATEL_GLOSSARY
