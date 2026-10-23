import unicodedata


def _strip_accents(text: str) -> str:
    """Strips accents, trims and upper-cases ``text``."""
    normalized = unicodedata.normalize("NFKD", text.strip())
    return "".join(c for c in normalized if not unicodedata.combining(c)).upper()


SERVICE_ALIASES: dict[str, str] = {
    "SMP": "SMP",
    "MOVEL": "SMP",
    "CELULAR": "SMP",
    "TELEFONIA MOVEL": "SMP",
    "4G": "SMP",
    "5G": "SMP",
    "CHIP": "SMP",
    "SCM": "SCM",
    "BANDA LARGA": "SCM",
    "BANDA LARGA FIXA": "SCM",
    "INTERNET FIXA": "SCM",
    "FIBRA": "SCM",
    "FIBRA OPTICA": "SCM",
    "WIFI": "SCM",
    "WI-FI": "SCM",
    "STFC": "STFC",
    "FIXO": "STFC",
    "TELEFONIA FIXA": "STFC",
    "TELEFONE FIXO": "STFC",
    "VOZ FIXA": "STFC",
    "SEAC": "SeAC",
    "TV": "SeAC",
    "TV POR ASSINATURA": "SeAC",
    "TV PAGA": "SeAC",
}

SERVICE_DESCRIPTIONS: dict[str, str] = {
    "SMP": "SMP (Serviço Móvel Pessoal - Telefonia Móvel 4G/5G)",
    "SCM": "SCM (Serviço de Comunicação Multimídia - Banda Larga Fixa / Fibra)",
    "STFC": "STFC (Serviço Telefônico Fixo Comutado - Telefonia Fixa)",
    "SeAC": "SeAC (Serviço de Acesso Condicionado - TV por Assinatura)",
}

OPERATOR_ALIASES: dict[str, str] = {
    "VIVO": "VIVO",
    "TELEFONICA": "VIVO",
    "TELEFONICA BRASIL": "VIVO",
    "TELEFONICA BRASIL S.A.": "VIVO",
    "TERRA": "VIVO",
    "CLARO": "CLARO",
    "CLARO S.A.": "CLARO",
    "CLARO NXT": "CLARO",
    "NET": "CLARO",
    "EMBRATEL": "CLARO",
    "TIM": "TIM",
    "TIM S.A.": "TIM",
    "TIM S/A": "TIM",
    "TIM BRASIL": "TIM",
    "OI": "OI",
    "OI S.A.": "OI",
    "OI FIBRA": "OI",
    "NIO": "OI",
    "BRISANET": "BRISANET",
    "BRISANET TELECOMUNICACOES": "BRISANET",
    "ALGAR": "ALGAR",
    "ALGAR TELECOM": "ALGAR",
    "CTBC": "ALGAR",
    "UNIFIQUE": "UNIFIQUE",
    "UNIFIQUE TELECOMUNICACOES": "UNIFIQUE",
    "DESKTOP": "DESKTOP",
    "DESKTOP SIGMANET": "DESKTOP",
    "VERO": "VERO",
    "AMERICANET": "VERO",
    "VERO AMERICANET": "VERO",
    "LIGGA": "LIGGA",
    "COPEL": "LIGGA",
    "COPEL TELECOM": "LIGGA",
    "SKY": "SKY",
    "GIGA+ FIBRA": "ALLOHA (GIGA+)",
    "ALLOHA": "ALLOHA (GIGA+)",
    "MOB": "ALLOHA (GIGA+)",
}

UF_ALIASES: dict[str, str] = {
    "AC": "AC", "ACRE": "AC",
    "AL": "AL", "ALAGOAS": "AL",
    "AM": "AM", "AMAZONAS": "AM",
    "AP": "AP", "AMAPA": "AP",
    "BA": "BA", "BAHIA": "BA",
    "CE": "CE", "CEARA": "CE",
    "DF": "DF", "DISTRITO FEDERAL": "DF", "BRASILIA": "DF",
    "ES": "ES", "ESPIRITO SANTO": "ES",
    "GO": "GO", "GOIAS": "GO",
    "MA": "MA", "MARANHAO": "MA",
    "MG": "MG", "MINAS GERAIS": "MG",
    "MS": "MS", "MATO GROSSO DO SUL": "MS",
    "MT": "MT", "MATO GROSSO": "MT",
    "PA": "PA", "PARA": "PA",
    "PB": "PB", "PARAIBA": "PB",
    "PE": "PE", "PERNAMBUCO": "PE",
    "PI": "PI", "PIAUI": "PI",
    "PR": "PR", "PARANA": "PR",
    "RJ": "RJ", "RIO DE JANEIRO": "RJ",
    "RN": "RN", "RIO GRANDE DO NORTE": "RN",
    "RO": "RO", "RONDONIA": "RO",
    "RR": "RR", "RORAIMA": "RR",
    "RS": "RS", "RIO GRANDE DO SUL": "RS",
    "SC": "SC", "SANTA CATARINA": "SC",
    "SE": "SE", "SERGIPE": "SE",
    "SP": "SP", "SAO PAULO": "SP",
    "TO": "TO", "TOCANTINS": "TO",
    "BR": "BR", "BRASIL": "BR", "NACIONAL": "BR",
}

INDICATOR_ALIASES: dict[str, str] = {
    "DOWNLOAD": "velocidade_download",
    "VELOCIDADE_DOWNLOAD": "velocidade_download",
    "VELOCIDADE DE DOWNLOAD": "velocidade_download",
    "VELOCIDADE": "velocidade_download",
    "UPLOAD": "velocidade_upload",
    "VELOCIDADE_UPLOAD": "velocidade_upload",
    "VELOCIDADE DE UPLOAD": "velocidade_upload",
    "LATENCIA": "latencia",
    "PING": "latencia",
    "ATRASO": "latencia",
    "JITTER": "jitter",
    "VARIACAO DE LATENCIA": "jitter",
    "PERDA": "perda_pacotes",
    "PERDA_PACOTES": "perda_pacotes",
    "PERDA DE PACOTES": "perda_pacotes",
    "PACKET LOSS": "perda_pacotes",
    "DISPONIBILIDADE": "disponibilidade",
    "QUEDA": "disponibilidade",
    "QUEDAS": "disponibilidade",
    "UPTIME": "disponibilidade",
    "TODOS": "todos",
    "ALL": "todos",
}


def normalize_service(servico: str | None) -> str | None:
    """Maps natural-language terms ('fibra', 'celular', 'banda larga'...) to the Anatel service code (SCM, SMP, STFC)."""
    if not servico or not servico.strip():
        return None
    cleaned = _strip_accents(servico)
    if cleaned in ("TODOS", "ALL", "*"):
        return None
    if cleaned in SERVICE_ALIASES:
        return SERVICE_ALIASES[cleaned]
    for alias, code in SERVICE_ALIASES.items():
        if alias in cleaned:
            return code
    return cleaned


def normalize_operator(operadora: str | None) -> str | None:
    """Maps commercial or regulatory names ('Telefonica', 'Vivo', 'Claro S.A.'...) to the canonical operator name."""
    if not operadora or not operadora.strip():
        return None
    cleaned = _strip_accents(operadora)
    if cleaned in ("TODAS", "TODOS", "ALL", "*"):
        return None
    if cleaned in OPERATOR_ALIASES:
        return OPERATOR_ALIASES[cleaned]
    for alias, canonical in OPERATOR_ALIASES.items():
        if alias in cleaned:
            return canonical
    return cleaned


def normalize_uf(uf: str | None) -> str | None:
    """Normalizes a Brazilian state code or name ('São Paulo' -> 'SP', 'Nacional' -> 'BR')."""
    if not uf or not uf.strip():
        return None
    cleaned = _strip_accents(uf)
    if cleaned in ("TODAS", "TODOS", "ALL", "*"):
        return None
    return UF_ALIASES.get(cleaned, cleaned)


def normalize_indicator(indicador: str | None) -> str | None:
    """Normalizes an RQUAL network-indicator name to its canonical id."""
    if not indicador or not indicador.strip():
        return None
    cleaned = _strip_accents(indicador)
    if cleaned in ("TODOS", "TODAS", "ALL", "*"):
        return None
    if cleaned in INDICATOR_ALIASES:
        target = INDICATOR_ALIASES[cleaned]
        return None if target == "todos" else target
    for alias, canonical in INDICATOR_ALIASES.items():
        if alias in cleaned:
            return None if canonical == "todos" else canonical
    return cleaned.lower()


def normalize_municipality(municipio: str | None) -> str | None:
    """Strips accents and upper-cases a municipality name for partial matching."""
    if not municipio or not municipio.strip():
        return None
    cleaned = _strip_accents(municipio)
    if cleaned in ("TODOS", "TODAS", "ALL", "*"):
        return None
    return cleaned
