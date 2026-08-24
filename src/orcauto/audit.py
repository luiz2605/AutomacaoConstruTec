# -*- coding: utf-8 -*-
"""Registro das inserções, para conferir no terminal o que foi escrito onde.

Cada coeficiente gravado passa por aqui antes de ir para a célula, com o que
havia lá antes. Serve para auditar sem abrir a planilha — e para provar que a
inserção só acontece no cruzamento certo de linha (o serviço) e coluna (o
insumo).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("orcauto.insercoes")

VAZIO = "Vazio"


def _resumir(valor, limite: int = 46) -> str:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return VAZIO
    texto = str(valor).strip()
    return texto if len(texto) <= limite else texto[:limite - 1] + "…"


@dataclass
class Registro:
    aba: str
    codigo: str
    insumo: str
    celula: str
    anterior: str
    novo: str

    def linha(self) -> str:
        return (f"[INSERÇÃO] Aba: {self.aba} | Código: {self.codigo} | "
                f"Insumo: {self.insumo} | Valor Anterior: {self.anterior} -> "
                f"Novo Valor: {self.novo} | Linha/Coluna: {self.celula}")


@dataclass
class Auditoria:
    """Coleciona as inserções de uma execução."""
    registros: list[Registro] = field(default_factory=list)

    def inserir(self, *, aba: str, codigo: str, insumo: str, celula: str,
                anterior, novo) -> Registro:
        registro = Registro(aba=aba, codigo=codigo, insumo=insumo, celula=celula,
                            anterior=_resumir(anterior), novo=_resumir(novo))
        self.registros.append(registro)
        logger.info(registro.linha())
        return registro

    def por_aba(self) -> dict[str, int]:
        contagem: dict[str, int] = {}
        for registro in self.registros:
            contagem[registro.aba] = contagem.get(registro.aba, 0) + 1
        return contagem

    def __len__(self) -> int:
        return len(self.registros)


def configurar_terminal(ativo: bool = True) -> None:
    """Liga a saída das inserções no terminal, sem prefixo de logging."""
    logger.handlers.clear()
    if not ativo:
        logger.setLevel(logging.WARNING)
        return
    manipulador = logging.StreamHandler()
    manipulador.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(manipulador)
    logger.setLevel(logging.INFO)
    logger.propagate = False
