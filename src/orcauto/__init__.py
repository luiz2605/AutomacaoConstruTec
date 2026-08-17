# -*- coding: utf-8 -*-
"""orcauto — cruza um orçamento analítico em PDF com as composições de custo de
uma planilha Excel e gera versões automatizadas das abas de levantamento."""
from .config import Config
from .pipeline import Result, run

__version__ = "1.0.0"
__all__ = ["Config", "Result", "run"]
