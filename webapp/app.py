# -*- coding: utf-8 -*-
"""Aplicação web do orcauto: envia o PDF do orçamento, baixa o levantamento."""
from __future__ import annotations

import logging
import os
import secrets
import shutil
import tempfile
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask
from starlette.requests import Request

from .jobs import ERRO, PRONTO, Fila
from .relatos import (FalhaNoEnvio, RelatoNaoConfigurado, configurado,
                      enviar_relato)
from .service import caminho_base

logger = logging.getLogger(__name__)

PASTA = Path(__file__).resolve().parent
TAMANHO_MAXIMO = int(os.environ.get("ORCAUTO_MAX_MB", "40")) * 1024 * 1024
PEDACO = 1024 * 1024

app = FastAPI(title="ConstruTec — Levantamento automático", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(PASTA / "templates"))
fila = Fila()

# ---------------------------------------------------------------------------
# Autenticação
#
# O endereço passa a ser público (Render), então toda rota que mostra ou
# entrega dado de orçamento exige login. A senha vive só na variável de
# ambiente `ORCAUTO_SENHA` — nunca no repositório.
#
# `auto_error=False`: sem isso, uma requisição sem credenciais receberia 401
# antes de esta função rodar, e um servidor publicado SEM a senha configurada
# ficaria pedindo login para sempre, sem nunca dizer que o problema é de
# configuração. Com o controle na mão, dá para distinguir "não configurado"
# (503) de "credencial errada" (401).
# ---------------------------------------------------------------------------
security = HTTPBasic(auto_error=False)
DESAFIO = {"WWW-Authenticate": "Basic"}


def exigir_login(credenciais: HTTPBasicCredentials | None = Depends(security)) -> str:
    usuario_esperado = os.environ.get("ORCAUTO_USUARIO", "orcamentos")
    senha_esperada = os.environ.get("ORCAUTO_SENHA")
    if not senha_esperada:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Autenticação não configurada no servidor.")
    if credenciais is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas",
                            headers=DESAFIO)
    # compare_digest em bytes: em str ele recusa caractere fora do ASCII, e uma
    # senha com acento derrubaria a rota com 500 em vez de responder 401.
    # Os dois lados são comparados sempre, para não vazar por tempo de resposta
    # se o que errou foi o usuário ou a senha.
    usuario_ok = secrets.compare_digest(credenciais.username.encode("utf-8"),
                                        usuario_esperado.encode("utf-8"))
    senha_ok = secrets.compare_digest(credenciais.password.encode("utf-8"),
                                      senha_esperada.encode("utf-8"))
    if not (usuario_ok and senha_ok):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas",
                            headers=DESAFIO)
    return credenciais.username


@app.get("/", response_class=HTMLResponse)
def pagina(request: Request, usuario: str = Depends(exigir_login)):
    try:
        caminho_base()
        indisponivel = None
    except Exception as erro:
        indisponivel = str(erro)
    return templates.TemplateResponse(request, "index.html", {
        "indisponivel": indisponivel,
        "tamanho_maximo_mb": TAMANHO_MAXIMO // (1024 * 1024),
        "relato_disponivel": configurado(),
    })


@app.post("/processar")
async def processar(arquivo: UploadFile,
                    usuario: str = Depends(exigir_login)):
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
def estado(job_id: str, usuario: str = Depends(exigir_login)):
    job = fila.obter(job_id)
    if job is None:
        raise HTTPException(404, "Este processamento expirou. Envie o PDF de novo.")
    return JSONResponse(job.json())


@app.get("/baixar/{job_id}")
def baixar(job_id: str, usuario: str = Depends(exigir_login)):
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


@app.post("/relatar")
async def relatar(descricao: str = Form(""), job_id: str | None = Form(None),
                  usuario: str = Depends(exigir_login)):
    """Relato de problema escrito pelo funcionário, na própria tela.

    O PDF enviado já foi apagado quando o processamento terminou (ver
    `jobs.py::executar`), então o relato leva só o texto e o `job_id` como
    referência — não há arquivo no servidor para anexar.
    """
    # `Form("")` em vez de `Form(...)`: com o campo obrigatório, uma descrição
    # vazia devolve o 422 do validador, com o corpo de erro do Pydantic. Quem
    # está na tela precisa da frase abaixo, e a regra de negócio ("descreva
    # antes de enviar") é a mesma para campo ausente e campo em branco.
    if not descricao.strip():
        raise HTTPException(400, "Descreva o problema antes de enviar.")

    contexto = {"usuario": usuario}
    if job_id:
        contexto["job_id"] = job_id
        job = fila.obter(job_id)
        if job is not None:
            # o que o suporte precisa para reproduzir, e que o funcionário não
            # tem como digitar: nome do PDF, estado e o erro exato, se houve
            contexto["arquivo"] = job.nome_original
            contexto["estado"] = job.estado
            if job.erro:
                contexto["erro"] = job.erro

    try:
        enviar_relato(descricao.strip(), contexto)
    except RelatoNaoConfigurado:
        logger.exception("Relato de problema não configurado")
        raise HTTPException(503, "O envio de relatos ainda não foi configurado neste "
                                 "servidor. Avise a equipe responsável.")
    except FalhaNoEnvio:
        logger.exception("Falha ao enviar relato")
        raise HTTPException(502, "Não foi possível enviar o relato agora. "
                                 "Tente de novo em instantes.")
    return JSONResponse({"ok": True})


@app.get("/saude")
def saude():
    """Sem autenticação de propósito: é o health check do Render e não
    devolve nada de orçamento — só se a planilha-base está no lugar."""
    try:
        base = caminho_base()
        pronto = True
    except Exception:
        base, pronto = None, False
    fila.limpar_expirados()
    return {"ok": pronto, "planilha_base": str(base) if base else None,
            "trabalhos_ativos": len(fila)}
