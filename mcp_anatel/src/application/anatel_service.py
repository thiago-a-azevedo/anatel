from typing import Any

import polars as pl

from src.config import settings
from src.domain.entities import FonteMetadados, RespostaPadraoAnatel
from src.domain.glossary import get_glossary_content
from src.domain.normalizer import (
    normalize_indicator,
    normalize_municipality,
    normalize_operator,
    normalize_service,
    normalize_uf,
)
from src.infrastructure.anatel_http_client import anatel_http_client


def _clamp_limit(limite: int | None) -> int:
    if limite is None or limite <= 0:
        return settings.default_max_rows
    return min(limite, settings.max_allowed_rows)


def _records_to_markdown_table(records: list[dict[str, Any]], max_rows: int = 15) -> str:
    """Renders a list of dicts as a compact, readable Markdown table (user-facing, pt-BR)."""
    if not records:
        return "_Nenhum registro encontrado para os filtros informados._"
    sample = records[:max_rows]
    headers = list(sample[0].keys())
    header_line = "| " + " | ".join(headers) + " |"
    separator_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    body_lines = []
    for row in sample:
        vals = [str(row.get(h, "")) for h in headers]
        body_lines.append("| " + " | ".join(vals) + " |")
    return "\n".join([header_line, separator_line, *body_lines])


class AnatelService:
    """Orchestrates in-memory (Polars) queries over Anatel's Consumer & Quality pillars:

    1. RQUAL quality seal and IQS
    2. Operational network-quality indicators
    3. Complaints (Anatel Consumidor) and IDA
    4. Satisfaction / perceived-quality survey (ISG)
    5. Consolidated operator comparison (join of the 4 pillars)

    Every method returns ``RespostaPadraoAnatel.model_dump()``; summaries and tables are
    written in Portuguese because they are shown to Brazilian end users.
    """

    async def consultar_rqual_iqs(
        self,
        operadora: str | None = None,
        servico: str | None = None,
        uf: str | None = None,
        municipio: str | None = None,
        ano_mes: str | None = None,
        limite: int = 25,
    ) -> dict[str, Any]:
        df, origin = await anatel_http_client.get_rqual_iqs_df()
        op_norm = normalize_operator(operadora)
        srv_norm = normalize_service(servico)
        uf_norm = normalize_uf(uf)
        mun_norm = normalize_municipality(municipio)
        row_limit = _clamp_limit(limite)

        filtered = df
        if op_norm:
            filtered = filtered.filter(pl.col("operadora").str.to_uppercase().str.contains(op_norm))
        if srv_norm:
            filtered = filtered.filter(pl.col("servico") == srv_norm)
        if uf_norm:
            filtered = filtered.filter(pl.col("uf") == uf_norm)
        if mun_norm:
            filtered = filtered.filter(pl.col("municipio").str.to_uppercase().str.contains(mun_norm))
        if ano_mes and ano_mes.strip():
            filtered = filtered.filter(pl.col("ano_mes") == ano_mes.strip())

        filtered = filtered.sort(["ano_mes", "nota_iqs"], descending=[True, True])
        total_found = filtered.height
        records = filtered.head(row_limit).to_dicts()

        if total_found > 0:
            avg_iqs = round(float(filtered["nota_iqs"].mean() or 0.0), 2)
            max_row = filtered.row(0, named=True)
            min_row = filtered.sort("nota_iqs", descending=False).row(0, named=True)
            selo_counts = (
                filtered.group_by("selo_rqual")
                .len()
                .sort("selo_rqual")
                .to_dicts()
            )
            dist_selos = {r["selo_rqual"]: r["len"] for r in selo_counts}
            resumo = (
                f"Encontrados {total_found} registros de RQUAL/IQS. "
                f"Média geral de IQS: {avg_iqs}/10. "
                f"Melhor avaliação: {max_row['operadora']} ({max_row['servico']} - {max_row['uf']}/{max_row['municipio']}) "
                f"com IQS {max_row['nota_iqs']} (Selo {max_row['selo_rqual']})."
            )
            stats = {
                "media_nota_iqs": avg_iqs,
                "melhor_operadora": {
                    "operadora": max_row["operadora"],
                    "servico": max_row["servico"],
                    "uf": max_row["uf"],
                    "municipio": max_row["municipio"],
                    "nota_iqs": max_row["nota_iqs"],
                    "selo_rqual": max_row["selo_rqual"],
                },
                "menor_operadora": {
                    "operadora": min_row["operadora"],
                    "servico": min_row["servico"],
                    "uf": min_row["uf"],
                    "municipio": min_row["municipio"],
                    "nota_iqs": min_row["nota_iqs"],
                    "selo_rqual": min_row["selo_rqual"],
                },
                "distribuicao_selos": dist_selos,
            }
        else:
            resumo = "Nenhum registro de Selo RQUAL/IQS encontrado para os filtros especificados."
            stats = {"media_nota_iqs": None, "distribuicao_selos": {}}

        resposta = RespostaPadraoAnatel(
            resumo_executivo=resumo,
            estatisticas_agregadas=stats,
            registros=records,
            tabela_markdown=_records_to_markdown_table(records),
            metadados_fonte=FonteMetadados(
                pilar="RQUAL - Selo de Qualidade e IQS",
                url_oficial_anatel=settings.anatel_rqual_zip_url,
                origem_leitura=origin,
                filtros_aplicados={
                    "operadora": op_norm,
                    "servico": srv_norm,
                    "uf": uf_norm,
                    "municipio": mun_norm,
                    "ano_mes": ano_mes,
                },
                total_registros_encontrados=total_found,
                registros_retornados=len(records),
            ),
        )
        return resposta.model_dump()

    async def consultar_indicadores_rede(
        self,
        operadora: str | None = None,
        servico: str | None = None,
        indicador: str | None = None,
        uf: str | None = None,
        municipio: str | None = None,
        ano_mes: str | None = None,
        limite: int = 25,
    ) -> dict[str, Any]:
        df, origin = await anatel_http_client.get_indicadores_rede_df()
        op_norm = normalize_operator(operadora)
        srv_norm = normalize_service(servico)
        ind_norm = normalize_indicator(indicador)
        uf_norm = normalize_uf(uf)
        mun_norm = normalize_municipality(municipio)
        row_limit = _clamp_limit(limite)

        filtered = df
        if op_norm:
            filtered = filtered.filter(pl.col("operadora").str.to_uppercase().str.contains(op_norm))
        if srv_norm:
            filtered = filtered.filter(pl.col("servico") == srv_norm)
        if ind_norm:
            filtered = filtered.filter(pl.col("indicador") == ind_norm)
        if uf_norm:
            filtered = filtered.filter(pl.col("uf") == uf_norm)
        if mun_norm:
            filtered = filtered.filter(pl.col("municipio").str.to_uppercase().str.contains(mun_norm))
        if ano_mes and ano_mes.strip():
            filtered = filtered.filter(pl.col("ano_mes") == ano_mes.strip())

        filtered = filtered.sort(["ano_mes", "operadora", "indicador"], descending=[True, False, False])
        total_found = filtered.height
        records = filtered.head(row_limit).to_dicts()

        if total_found > 0:
            taxa_cumprimento = round(
                float(filtered["cumpriu_meta"].cast(pl.Float64).mean() or 0.0) * 100.0, 2
            )
            por_indicador = (
                filtered.group_by(["indicador", "unidade", "meta_referencia"])
                .agg(
                    pl.col("valor_medido").mean().round(2).alias("media_valor_medido"),
                    (pl.col("cumpriu_meta").cast(pl.Float64).mean() * 100.0)
                    .round(1)
                    .alias("pct_cumprimento_meta"),
                )
                .sort("indicador")
                .to_dicts()
            )
            resumo = (
                f"Consultados {total_found} indicadores operacionais de rede RQUAL. "
                f"Taxa global de cumprimento das metas regulatórias: {taxa_cumprimento}%."
            )
            stats = {
                "taxa_cumprimento_metas_pct": taxa_cumprimento,
                "medias_por_indicador": por_indicador,
            }
        else:
            resumo = "Nenhum indicador operacional de rede encontrado para os filtros informados."
            stats = {"taxa_cumprimento_metas_pct": None, "medias_por_indicador": []}

        resposta = RespostaPadraoAnatel(
            resumo_executivo=resumo,
            estatisticas_agregadas=stats,
            registros=records,
            tabela_markdown=_records_to_markdown_table(records),
            metadados_fonte=FonteMetadados(
                pilar="RQUAL - Indicadores Operacionais de Qualidade de Rede",
                url_oficial_anatel=settings.anatel_rqual_zip_url,
                origem_leitura=origin,
                filtros_aplicados={
                    "operadora": op_norm,
                    "servico": srv_norm,
                    "indicador": ind_norm,
                    "uf": uf_norm,
                    "municipio": mun_norm,
                    "ano_mes": ano_mes,
                },
                total_registros_encontrados=total_found,
                registros_retornados=len(records),
            ),
        )
        return resposta.model_dump()

    async def consultar_reclamacoes_ida(
        self,
        operadora: str | None = None,
        servico: str | None = None,
        uf: str | None = None,
        motivo: str | None = None,
        ano_mes: str | None = None,
        limite: int = 25,
    ) -> dict[str, Any]:
        df, origin = await anatel_http_client.get_reclamacoes_ida_df()
        op_norm = normalize_operator(operadora)
        srv_norm = normalize_service(servico)
        uf_norm = normalize_uf(uf)
        row_limit = _clamp_limit(limite)

        filtered = df
        if op_norm:
            filtered = filtered.filter(pl.col("operadora").str.to_uppercase().str.contains(op_norm))
        if srv_norm:
            filtered = filtered.filter(pl.col("servico") == srv_norm)
        if uf_norm:
            filtered = filtered.filter(pl.col("uf") == uf_norm)
        if motivo and motivo.strip():
            filtered = filtered.filter(
                pl.col("principal_motivo").str.to_lowercase().str.contains(motivo.strip().lower())
            )
        if ano_mes and ano_mes.strip():
            filtered = filtered.filter(pl.col("ano_mes") == ano_mes.strip())

        filtered = filtered.sort(["ano_mes", "nota_ida"], descending=[True, True])
        total_found = filtered.height
        records = filtered.head(row_limit).to_dicts()

        if total_found > 0:
            media_ida = round(float(filtered["nota_ida"].mean() or 0.0), 2)
            media_ind_rec = round(float(filtered["indice_reclamacoes_1000_acessos"].mean() or 0.0), 2)
            media_res = round(float(filtered["taxa_resolucao_pct"].mean() or 0.0), 2)
            top_ida = filtered.row(0, named=True)
            resumo = (
                f"Analisados {total_found} registros do Anatel Consumidor / IDA. "
                f"Nota IDA média: {media_ida}/100 | Taxa média de resolução: {media_res}% | "
                f"Índice médio de reclamações: {media_ind_rec} por 1.000 acessos. "
                f"Líder em atendimento no recorte: {top_ida['operadora']} ({top_ida['servico']}/{top_ida['uf']}) com IDA {top_ida['nota_ida']}."
            )
            stats = {
                "media_nota_ida": media_ida,
                "media_indice_reclamacoes_1000_acessos": media_ind_rec,
                "media_taxa_resolucao_pct": media_res,
                "lider_ida_recorte": {
                    "operadora": top_ida["operadora"],
                    "servico": top_ida["servico"],
                    "uf": top_ida["uf"],
                    "nota_ida": top_ida["nota_ida"],
                },
            }
        else:
            resumo = "Nenhum registro de reclamações ou IDA encontrado para os filtros informados."
            stats = {"media_nota_ida": None}

        resposta = RespostaPadraoAnatel(
            resumo_executivo=resumo,
            estatisticas_agregadas=stats,
            registros=records,
            tabela_markdown=_records_to_markdown_table(records),
            metadados_fonte=FonteMetadados(
                pilar="Anatel Consumidor - Reclamações e IDA",
                url_oficial_anatel=settings.anatel_reclamacoes_zip_url,
                origem_leitura=origin,
                filtros_aplicados={
                    "operadora": op_norm,
                    "servico": srv_norm,
                    "uf": uf_norm,
                    "motivo": motivo,
                    "ano_mes": ano_mes,
                },
                total_registros_encontrados=total_found,
                registros_retornados=len(records),
            ),
        )
        return resposta.model_dump()

    async def consultar_pesquisa_satisfacao(
        self,
        operadora: str | None = None,
        servico: str | None = None,
        uf: str | None = None,
        ano: int | None = None,
        limite: int = 25,
    ) -> dict[str, Any]:
        df, origin = await anatel_http_client.get_pesquisa_satisfacao_df()
        op_norm = normalize_operator(operadora)
        srv_norm = normalize_service(servico)
        uf_norm = normalize_uf(uf)
        row_limit = _clamp_limit(limite)

        filtered = df
        if op_norm:
            filtered = filtered.filter(pl.col("operadora").str.to_uppercase().str.contains(op_norm))
        if srv_norm:
            filtered = filtered.filter(pl.col("servico") == srv_norm)
        if uf_norm:
            filtered = filtered.filter(pl.col("uf") == uf_norm)
        if ano is not None:
            filtered = filtered.filter(pl.col("ano") == int(ano))

        filtered = filtered.sort(["ano", "nota_isg"], descending=[True, True])
        total_found = filtered.height
        records = filtered.head(row_limit).to_dicts()

        if total_found > 0:
            media_isg = round(float(filtered["nota_isg"].mean() or 0.0), 2)
            media_func = round(float(filtered["nota_funcionamento"].mean() or 0.0), 2)
            media_atend = round(float(filtered["nota_atendimento"].mean() or 0.0), 2)
            media_cob = round(float(filtered["nota_cobranca"].mean() or 0.0), 2)
            lider = filtered.row(0, named=True)
            resumo = (
                f"Consultados {total_found} resultados da Pesquisa de Satisfação e Qualidade Percebida. "
                f"ISG médio: {media_isg}/10 (Funcionamento: {media_func}, Atendimento: {media_atend}, Cobrança: {media_cob}). "
                f"Maior satisfação no recorte: {lider['operadora']} ({lider['servico']}/{lider['uf']} em {lider['ano']}) com ISG {lider['nota_isg']}."
            )
            stats = {
                "media_nota_isg": media_isg,
                "media_nota_funcionamento": media_func,
                "media_nota_atendimento": media_atend,
                "media_nota_cobranca": media_cob,
                "lider_satisfacao": {
                    "operadora": lider["operadora"],
                    "servico": lider["servico"],
                    "uf": lider["uf"],
                    "ano": lider["ano"],
                    "nota_isg": lider["nota_isg"],
                },
            }
        else:
            resumo = "Nenhum resultado da Pesquisa de Satisfação encontrado para os filtros informados."
            stats = {"media_nota_isg": None}

        resposta = RespostaPadraoAnatel(
            resumo_executivo=resumo,
            estatisticas_agregadas=stats,
            registros=records,
            tabela_markdown=_records_to_markdown_table(records),
            metadados_fonte=FonteMetadados(
                pilar="Pesquisa de Satisfação e Qualidade Percebida (ISG)",
                url_oficial_anatel=settings.anatel_satisfacao_zip_url,
                origem_leitura=origin,
                filtros_aplicados={
                    "operadora": op_norm,
                    "servico": srv_norm,
                    "uf": uf_norm,
                    "ano": ano,
                },
                total_registros_encontrados=total_found,
                registros_retornados=len(records),
            ),
        )
        return resposta.model_dump()

    async def comparar_operadoras(
        self,
        servico: str = "SCM",
        uf: str = "BR",
        municipio: str | None = None,
        operadoras: list[str] | None = None,
    ) -> dict[str, Any]:
        """Joins the 4 Anatel pillars (RQUAL/IQS + network indicators + complaints/IDA +
        satisfaction ISG) in memory to rank and compare operators for one state and service."""
        srv_norm = normalize_service(servico) or "SCM"
        uf_norm = normalize_uf(uf) or "BR"
        mun_norm = normalize_municipality(municipio)
        ops_norm = [normalize_operator(op) for op in (operadoras or []) if normalize_operator(op)]

        df_iqs, origin_iqs = await anatel_http_client.get_rqual_iqs_df()
        df_rede, _ = await anatel_http_client.get_indicadores_rede_df()
        df_ida, _ = await anatel_http_client.get_reclamacoes_ida_df()
        df_sat, _ = await anatel_http_client.get_pesquisa_satisfacao_df()

        # 1. Latest IQS per operator
        iqs_sub = df_iqs.filter((pl.col("servico") == srv_norm) & (pl.col("uf") == uf_norm))
        if mun_norm:
            iqs_mun = iqs_sub.filter(pl.col("municipio").str.to_uppercase().str.contains(mun_norm))
            if iqs_mun.height > 0:
                iqs_sub = iqs_mun
        if ops_norm:
            iqs_sub = iqs_sub.filter(pl.col("operadora").is_in(ops_norm))

        iqs_agg = (
            iqs_sub.sort("ano_mes", descending=True)
            .group_by("operadora")
            .agg(
                pl.col("nota_iqs").first().alias("nota_iqs"),
                pl.col("selo_rqual").first().alias("selo_rqual"),
            )
        )

        # 2. Network indicators (download speed, latency, availability)
        rede_sub = df_rede.filter((pl.col("servico") == srv_norm) & (pl.col("uf") == uf_norm))
        rede_agg = (
            rede_sub.sort("ano_mes", descending=True)
            .group_by("operadora")
            .agg(
                pl.col("valor_medido")
                .filter(pl.col("indicador") == "velocidade_download")
                .first()
                .alias("download_cumprimento_pct"),
                pl.col("valor_medido")
                .filter(pl.col("indicador") == "latencia")
                .first()
                .alias("latencia_ms"),
                pl.col("valor_medido")
                .filter(pl.col("indicador") == "disponibilidade")
                .first()
                .alias("disponibilidade_pct"),
            )
        )

        # 3. IDA and complaints
        ida_sub = df_ida.filter((pl.col("servico") == srv_norm) & (pl.col("uf") == uf_norm))
        ida_agg = (
            ida_sub.sort("ano_mes", descending=True)
            .group_by("operadora")
            .agg(
                pl.col("nota_ida").first().alias("nota_ida"),
                pl.col("indice_reclamacoes_1000_acessos").first().alias("reclamacoes_por_1000"),
                pl.col("taxa_resolucao_pct").first().alias("taxa_resolucao_pct"),
            )
        )

        # 4. Satisfaction survey (ISG)
        sat_sub = df_sat.filter((pl.col("servico") == srv_norm) & (pl.col("uf") == uf_norm))
        sat_agg = (
            sat_sub.sort("ano", descending=True)
            .group_by("operadora")
            .agg(
                pl.col("nota_isg").first().alias("nota_isg_satisfacao"),
                pl.col("nota_funcionamento").first().alias("nota_funcionamento"),
            )
        )

        joined = (
            iqs_agg.join(rede_agg, on="operadora", how="left")
            .join(ida_agg, on="operadora", how="left")
            .join(sat_agg, on="operadora", how="left")
            .with_columns(
                (
                    pl.col("nota_iqs").fill_null(7.5) * 0.35
                    + (pl.col("nota_ida").fill_null(80.0) / 10.0) * 0.30
                    + pl.col("nota_isg_satisfacao").fill_null(7.5) * 0.35
                )
                .round(2)
                .alias("score_consolidado_0_10")
            )
            .sort("score_consolidado_0_10", descending=True)
        )

        records = joined.to_dicts()
        for idx, row in enumerate(records, start=1):
            row["posicao_ranking"] = idx

        if records:
            top = records[0]
            resumo = (
                f"Comparativo consolidado de {len(records)} operadoras para {srv_norm} em {uf_norm}: "
                f"1º lugar: {top['operadora']} (Score {top['score_consolidado_0_10']}/10 | "
                f"Selo RQUAL {top['selo_rqual']} | IQS {top['nota_iqs']} | IDA {top.get('nota_ida')} | ISG {top.get('nota_isg_satisfacao')})."
            )
            stats = {
                "servico_comparado": srv_norm,
                "uf_comparada": uf_norm,
                "municipio_filtro": mun_norm,
                "total_operadoras_comparadas": len(records),
                "lider_ranking": top,
                "pesos_score_consolidado": {
                    "nota_iqs_rqual": "35%",
                    "nota_ida_consumidor": "30%",
                    "nota_isg_satisfacao": "35%",
                },
            }
        else:
            resumo = f"Nenhuma operadora encontrada para o comparativo de {srv_norm} em {uf_norm}."
            stats = {"servico_comparado": srv_norm, "uf_comparada": uf_norm, "total_operadoras_comparadas": 0}

        resposta = RespostaPadraoAnatel(
            resumo_executivo=resumo,
            estatisticas_agregadas=stats,
            registros=records,
            tabela_markdown=_records_to_markdown_table(records),
            metadados_fonte=FonteMetadados(
                pilar="Comparativo Consolidado 4 Pilares (RQUAL/IQS + Rede + IDA + Satisfação)",
                url_oficial_anatel=settings.anatel_paineis_base_url,
                origem_leitura=origin_iqs,
                filtros_aplicados={
                    "servico": srv_norm,
                    "uf": uf_norm,
                    "municipio": mun_norm,
                    "operadoras": ops_norm,
                },
                total_registros_encontrados=len(records),
                registros_retornados=len(records),
            ),
        )
        return resposta.model_dump()

    async def buscar_datasets_ckan_anatel(
        self,
        termo_busca: str = "qualidade rqual consumidor",
        limite: int = 10,
    ) -> dict[str, Any]:
        row_limit = min(max(1, limite), 25)
        packages, origin = await anatel_http_client.search_ckan_datasets(
            termo_busca=termo_busca, limite=row_limit
        )
        resumo = (
            f"Encontrados {len(packages)} conjuntos de dados da Anatel para o termo '{termo_busca}'."
        )
        resposta = RespostaPadraoAnatel(
            resumo_executivo=resumo,
            estatisticas_agregadas={"termo_busca": termo_busca, "total_pacotes": len(packages)},
            registros=packages,
            tabela_markdown=_records_to_markdown_table(packages),
            metadados_fonte=FonteMetadados(
                pilar="Catálogo CKAN / Dados Abertos Anatel",
                url_oficial_anatel=settings.anatel_ckan_api_url,
                origem_leitura=origin,
                filtros_aplicados={"termo_busca": termo_busca, "limite": row_limit},
                total_registros_encontrados=len(packages),
                registros_retornados=len(packages),
            ),
        )
        return resposta.model_dump()

    async def consultar_glossario_metodologia_anatel(
        self,
        topico: str | None = "geral",
    ) -> dict[str, Any]:
        conteudo = get_glossary_content(topico)
        topicos_retornados = list(conteudo.keys())
        registros = [{"topico": k, **v} for k, v in conteudo.items()]
        resumo = (
            f"Glossário e metodologia regulatória da Anatel carregados para os tópicos: {', '.join(topicos_retornados)}."
        )
        resposta = RespostaPadraoAnatel(
            resumo_executivo=resumo,
            estatisticas_agregadas={
                "topico_solicitado": topico or "geral",
                "topicos_retornados": topicos_retornados,
            },
            registros=registros,
            tabela_markdown=_records_to_markdown_table(
                [{"topico": k, "titulo": v.get("titulo", "")} for k, v in conteudo.items()]
            ),
            metadados_fonte=FonteMetadados(
                pilar="Glossário e Metodologia Regulatória Anatel (Res. 717/2019 e Res. 632/2014)",
                url_oficial_anatel=settings.anatel_paineis_base_url,
                origem_leitura="memoria_interna",
                filtros_aplicados={"topico": topico},
                total_registros_encontrados=len(registros),
                registros_retornados=len(registros),
            ),
        )
        return resposta.model_dump()


anatel_service = AnatelService()
