from orcauto.textutil import (column_index, column_letter, format_number,
                              normalize, parse_number, similarity)


def test_normalize_remove_acento_e_pontuacao():
    assert normalize("Alvenaria de Pedra (traço 1:4)") == "ALVENARIA DE PEDRA TRACO 1 4"
    assert normalize(None) == ""


def test_parse_number_padrao_brasileiro():
    assert parse_number("1.799,61") == 1799.61
    assert parse_number("4,32") == 4.32
    assert parse_number("8") == 8.0
    assert parse_number(12.5) == 12.5
    assert parse_number("") is None
    assert parse_number(None) is None
    assert parse_number("abc") is None


def test_format_number_sem_zeros_a_direita():
    assert format_number(10.0) == "10"
    assert format_number(0.038) == "0.038"
    assert format_number(0.3) == "0.3"


def test_similarity_reconhece_servico_equivalente():
    alto = similarity("REBOCO C/ ARGAMASSA TRACO 1:5", "REBOCO C/ ARGAMASSA TRACO 1:6")
    baixo = similarity("REBOCO C/ ARGAMASSA TRACO 1:5", "ESCAVACAO MANUAL EM TERRA")
    assert alto > 0.9 > baixo


def test_colunas():
    assert column_letter(1) == "A" and column_letter(27) == "AA"
    assert column_index("A") == 1 and column_index("AA") == 27
