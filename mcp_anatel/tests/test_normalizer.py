from src.domain.normalizer import (
    normalize_indicator,
    normalize_municipality,
    normalize_operator,
    normalize_service,
    normalize_uf,
)


def test_normalize_service_aliases() -> None:
    assert normalize_service("fibra") == "SCM"
    assert normalize_service("Banda Larga Fixa") == "SCM"
    assert normalize_service("celular") == "SMP"
    assert normalize_service("5G") == "SMP"
    assert normalize_service("telefone fixo") == "STFC"
    assert normalize_service("todos") is None
    assert normalize_service(None) is None


def test_normalize_operator_aliases() -> None:
    assert normalize_operator("Telefonica Brasil S.A.") == "VIVO"
    assert normalize_operator("vivo") == "VIVO"
    assert normalize_operator("Claro NXT") == "CLARO"
    assert normalize_operator("NET") == "CLARO"
    assert normalize_operator("TIM S/A") == "TIM"
    assert normalize_operator("Oi Fibra") == "OI"
    assert normalize_operator("Brisanet") == "BRISANET"
    assert normalize_operator("Unifique") == "UNIFIQUE"
    assert normalize_operator("Algar Telecom") == "ALGAR"


def test_normalize_uf_aliases() -> None:
    assert normalize_uf("São Paulo") == "SP"
    assert normalize_uf("sp") == "SP"
    assert normalize_uf("Rio de Janeiro") == "RJ"
    assert normalize_uf("Nacional") == "BR"
    assert normalize_uf("Brasil") == "BR"


def test_normalize_indicator_aliases() -> None:
    assert normalize_indicator("download") == "velocidade_download"
    assert normalize_indicator("upload") == "velocidade_upload"
    assert normalize_indicator("ping") == "latencia"
    assert normalize_indicator("quedas") == "disponibilidade"
    assert normalize_indicator("todos") is None


def test_normalize_municipality() -> None:
    assert normalize_municipality("São Paulo") == "SAO PAULO"
    assert normalize_municipality("Florianópolis") == "FLORIANOPOLIS"
    assert normalize_municipality("todos") is None
