# -*- coding: utf-8 -*-
"""Camada de serviço: uma função de processamento, sem nada de HTTP nem de CLI.

O `orcauto` já era importável; o que faltava era um ponto único que
resolvesse a planilha-base, a configuração e o arquivo de saída, para que a
web e a linha de comando compartilhem exatamente o mesmo caminho de código.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from orcauto import Config
from orcauto.pipeline import run

# A planilha-base é o padrão da empresa, não algo que o funcionário envia:
# é dela que saem as composições, a tabela de insumos e o MODELO BASE.
BASE_ENV = "ORCAUTO_BASE_XLSX"
CONFIG_ENV = "ORCAUTO_CONFIG"
DEFAULT_BASE = Path(__file__).resolve().parent / "base" / "PLANILHA_BASE.xlsx"
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "planilha-base.toml"


class ProcessingError(RuntimeError):
    """Falha que faz sentido mostrar ao usuário final."""


@dataclass
class Resultado:
    caminho: Path
    nome_sugerido: str
    abas_criadas: int
    abas_preenchidas: int
    linhas: int
    nao_aplicados: int
    avisos: list[str]


def caminho_base(override: str | os.PathLike | None = None) -> Path:
    base = Path(override or os.environ.get(BASE_ENV) or DEFAULT_BASE)
    if not base.is_file():
        raise ProcessingError(
            "A planilha-base não foi encontrada no servidor. Ela é o arquivo com as "
            "abas de composição e o MODELO BASE, e precisa estar publicada junto da "
            f"aplicação (esperada em {base})."
        )
    return base


def carregar_config() -> Config:
    caminho = os.environ.get(CONFIG_ENV) or (
        str(DEFAULT_CONFIG) if DEFAULT_CONFIG.is_file() else None)
    return Config.load(caminho)


def processar_orcamento(pdf_path: str | os.PathLike,
                        destino: str | os.PathLike | None = None,
                        planilha_base: str | os.PathLike | None = None,
                        config: Config | None = None,
                        nome_origem: str | None = None) -> Resultado:
    """Recebe o PDF do orçamento e devolve a planilha de levantamento gerada."""
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise ProcessingError("O arquivo enviado não chegou completo. Tente de novo.")

    base = caminho_base(planilha_base)
    config = config or carregar_config()
    if destino is None:
        destino = Path(tempfile.mkdtemp(prefix="orcauto-")) / "LEVANTAMENTO (AUTO).xlsx"
    destino = Path(destino)

    try:
        resultado = run(base, pdf_path, destino, config)
    except ValueError as erro:
        raise ProcessingError(str(erro)) from erro
    except Exception as erro:                       # pdfplumber, openpyxl, zipfile...
        raise ProcessingError(
            "Não foi possível ler o PDF enviado. Confira se é o Orçamento Analítico "
            f"exportado do sistema, e não outro documento. (detalhe técnico: {erro})"
        ) from erro

    criadas = [p for p in resultado.synth if p.created]
    avisos = [f"{p.topic_name}: {p.reason}" for p in resultado.synth if not p.created]
    if not criadas and not resultado.plans:
        # Dois problemas diferentes caíam na mesma frase, e a que existia
        # mandava conferir a planilha-base mesmo quando o defeito era de
        # leitura do PDF — foi o que aconteceu com a Planilha Orçamentária.
        itens = sum(len(t.items) for t in resultado.topics)
        if itens == 0:
            raise ProcessingError(
                "O formato deste PDF não foi reconhecido. Confira se é um Orçamento "
                "Analítico ou uma Planilha Orçamentária exportada do Excel."
            )
        raise ProcessingError(
            "O PDF foi lido, mas nenhum item dele encontrou composição na planilha-base. "
            "Verifique se o orçamento e a planilha são do mesmo cliente/tabela."
        )
    return Resultado(
        caminho=destino,
        nome_sugerido=_nome_saida(Path(nome_origem or pdf_path)),
        abas_criadas=len(criadas),
        abas_preenchidas=len(resultado.plans),
        linhas=(sum(len(p.rows) for p in criadas)
                + sum(len(p.rows) for p in resultado.plans)),
        nao_aplicados=(sum(len(p.skipped) for p in resultado.synth)
                       + sum(len(p.skipped) for p in resultado.plans)),
        avisos=avisos,
    )


def _nome_saida(pdf_path: Path) -> str:
    limpo = "".join(c for c in pdf_path.stem if c.isalnum() or c in " -_")[:60].strip()
    return f"LEVANTAMENTO - {limpo or 'ORCAMENTO'}.xlsx"
