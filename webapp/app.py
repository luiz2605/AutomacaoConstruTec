# -*- coding: utf-8 -*-
"""Aplicação web do orcauto: envia o PDF do orçamento, baixa o levantamento."""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask
from starlette.requests import Request

from .jobs import ERRO, PRONTO, Fila
from .service import caminho_base

PASTA = Path(__file__).resolve().parent
TAMANHO_MAXIMO = int(os.environ.get("ORCAUTO_MAX_MB", "40")) * 1024 * 1024
PEDACO = 1024 * 1024

app = FastAPI(title="ConstruTec — Levantamento automático", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(PASTA / "templates"))
fila = Fila()


@app.get("/", response_class=HTMLResponse)
def pagina(request: Request):
    try:
        caminho_base()
        indisponivel = None
    except Exception as erro:
        indisponivel = str(erro)
    return templates.TemplateResponse(request, "index.html", {
        "indisponivel": indisponivel,
        "tamanho_maximo_mb": TAMANHO_MAXIMO // (1024 * 1024),
    })


@app.post("/processar")
async def processar(arquivo: UploadFile):
    if not (arquivo.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Envie o orçamento em PDF. Outros formatos não são lidos.")

    pasta = Path(tempfile.mkdtemp(prefix="orcauto-job-"))
    nome = "orcamento.pdf"
    destino = pasta / nome
    tamanho = 0
    try:
        with destino.open("wb") as saida:
            while pedaco := await arquivo.read(PEDACO):
                tamanho += len(pedaco)
                if tamanho > TAMANHO_MAXIMO:
                    raise HTTPException(
                        413, f"O arquivo passa de {TAMANHO_MAXIMO // (1024*1024)} MB. "
                             "Confirme se enviou o orçamento certo.")
                saida.write(pedaco)
    except HTTPException:
        shutil.rmtree(pasta, ignore_errors=True)
        raise
    if tamanho == 0:
        shutil.rmtree(pasta, ignore_errors=True)
        raise HTTPException(400, "O arquivo chegou vazio. Tente enviar de novo.")

    job = fila.criar(pasta, nome, nome_original=arquivo.filename or nome)
    # thread em vez de BackgroundTasks: o processamento é síncrono e pesado, e
    # não pode ocupar o laço de eventos enquanto a página consulta o estado
    threading.Thread(target=fila.executar, args=(job.id,), daemon=True).start()
    return JSONResponse({"id": job.id}, status_code=202)


@app.get("/estado/{job_id}")
def estado(job_id: str):
    job = fila.obter(job_id)
    if job is None:
        raise HTTPException(404, "Este processamento expirou. Envie o PDF de novo.")
    return JSONResponse(job.json())


@app.get("/baixar/{job_id}")
def baixar(job_id: str):
    job = fila.obter(job_id)
    if job is None:
        raise HTTPException(404, "Este processamento expirou. Envie o PDF de novo.")
    if job.estado == ERRO:
        raise HTTPException(400, job.erro or "Falha no processamento.")
    if job.estado != PRONTO or job.resultado is None:
        raise HTTPException(409, "Ainda processando. Aguarde a conclusão.")
    return FileResponse(
        job.resultado.caminho,
        filename=job.resultado.nome_sugerido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        # entregue o arquivo e apague tudo: o servidor não guarda nada
        background=BackgroundTask(fila.descartar, job.id),
    )


@app.get("/saude")
def saude():
    try:
        base = caminho_base()
        pronto = True
    except Exception:
        base, pronto = None, False
    fila.limpar_expirados()
    return {"ok": pronto, "planilha_base": str(base) if base else None,
            "trabalhos_ativos": len(fila)}
