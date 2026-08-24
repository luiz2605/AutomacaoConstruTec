# -*- coding: utf-8 -*-
"""Fila de processamento em memória.

O processamento leva ~20 s numa máquina modesta e cresce com o tamanho do
orçamento. Responder na mesma requisição significaria segurar a conexão todo
esse tempo — sujeito ao tempo-limite do proxy da hospedagem e sem como mostrar
progresso. Aqui o upload devolve um identificador na hora e a página pergunta o
estado até ficar pronto.

A fila é em memória de propósito: um processo, sem banco nem Redis. Isso atende
o uso real (poucos envios por dia, um funcionário por vez) e mantém o deploy
trivial. Se um dia precisar de mais de um processo, isto vira o ponto de troca.
"""
from __future__ import annotations

import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .service import ProcessingError, Resultado, processar_orcamento

PENDENTE, PROCESSANDO, PRONTO, ERRO = "pendente", "processando", "pronto", "erro"

# Um trabalho vive por tempo suficiente para o usuário baixar, e não mais:
# arquivo de entrada e de saída somem junto com ele.
VIDA_UTIL_SEGUNDOS = 30 * 60


@dataclass
class Job:
    id: str
    pasta: Path
    nome_pdf: str
    nome_original: str = ""
    estado: str = PENDENTE
    criado_em: float = field(default_factory=time.time)
    concluido_em: float | None = None
    erro: str | None = None
    resultado: Resultado | None = None

    @property
    def duracao(self) -> float:
        return (self.concluido_em or time.time()) - self.criado_em

    def json(self) -> dict:
        dados = {"id": self.id, "estado": self.estado,
                 "segundos": round(self.duracao, 1)}
        if self.estado == ERRO:
            dados["erro"] = self.erro
        if self.estado == PRONTO and self.resultado:
            dados.update({
                "abas_criadas": self.resultado.abas_criadas,
                "abas_preenchidas": self.resultado.abas_preenchidas,
                "linhas": self.resultado.linhas,
                "nao_aplicados": self.resultado.nao_aplicados,
                "avisos": self.resultado.avisos,
                "nome": self.resultado.nome_sugerido,
            })
        return dados


class Fila:
    def __init__(self, vida_util: int = VIDA_UTIL_SEGUNDOS):
        self._jobs: dict[str, Job] = {}
        self._trava = threading.Lock()
        self.vida_util = vida_util

    def criar(self, pasta: Path, nome_pdf: str, nome_original: str = "") -> Job:
        self.limpar_expirados()
        job = Job(id=uuid.uuid4().hex, pasta=pasta, nome_pdf=nome_pdf,
                  nome_original=nome_original or nome_pdf)
        with self._trava:
            self._jobs[job.id] = job
        return job

    def obter(self, job_id: str) -> Job | None:
        with self._trava:
            return self._jobs.get(job_id)

    def executar(self, job_id: str) -> None:
        """Roda o processamento. Chamado numa thread de trabalho."""
        job = self.obter(job_id)
        if job is None:
            return
        job.estado = PROCESSANDO
        try:
            job.resultado = processar_orcamento(job.pasta / job.nome_pdf,
                                                job.pasta / "saida.xlsx",
                                                nome_origem=job.nome_original)
            job.estado = PRONTO
        except ProcessingError as erro:
            job.estado, job.erro = ERRO, str(erro)
        except Exception as erro:                              # pragma: no cover
            job.estado = ERRO
            job.erro = ("Ocorreu uma falha inesperada no processamento. "
                        f"(detalhe técnico: {erro})")
        finally:
            job.concluido_em = time.time()
            # o PDF não serve para mais nada depois do processamento
            _apagar(job.pasta / job.nome_pdf)

    def descartar(self, job_id: str) -> None:
        """Remove o trabalho e tudo que ele deixou em disco."""
        with self._trava:
            job = self._jobs.pop(job_id, None)
        if job is not None:
            shutil.rmtree(job.pasta, ignore_errors=True)

    def limpar_expirados(self) -> int:
        limite = time.time() - self.vida_util
        with self._trava:
            vencidos = [i for i, j in self._jobs.items() if j.criado_em < limite]
        for job_id in vencidos:
            self.descartar(job_id)
        return len(vencidos)

    def __len__(self) -> int:
        with self._trava:
            return len(self._jobs)


def _apagar(caminho: Path) -> None:
    try:
        caminho.unlink(missing_ok=True)
    except OSError:                                            # pragma: no cover
        pass
