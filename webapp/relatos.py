# -*- coding: utf-8 -*-
"""Envio do relato de problema por e-mail.

Separado de `service.py` de propósito: aquele módulo é o caminho do
processamento do orçamento e não deve ganhar dependência de rede/SMTP. Aqui
não há nada de HTTP nem de FastAPI — é uma função pura de "monte e mande",
o que a torna testável com um SMTP falso.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

ASSUNTO = "orcauto — problema relatado"

# Todas obrigatórias, menos a porta.
HOST_ENV = "ORCAUTO_SMTP_HOST"
PORTA_ENV = "ORCAUTO_SMTP_PORTA"
USUARIO_ENV = "ORCAUTO_SMTP_USUARIO"
SENHA_ENV = "ORCAUTO_SMTP_SENHA"
SUPORTE_ENV = "ORCAUTO_EMAIL_SUPORTE"
PORTA_PADRAO = "465"
# Destino de fábrica: a caixa de suporte do orcauto. Continua podendo ser
# trocada pela variável de ambiente, mas sem ela o recurso já funciona.
SUPORTE_PADRAO = "suportorcauto@gmail.com"

# O corpo é montado a partir de texto que o funcionário digitou. Um relato
# gigante não pode virar um e-mail impossível de ler nem um vetor de abuso.
LIMITE_DESCRICAO = 5000


class RelatoNaoConfigurado(RuntimeError):
    """Falta variável de ambiente: é erro de servidor, não do funcionário."""


class FalhaNoEnvio(RuntimeError):
    """O SMTP recusou ou não respondeu."""


def configurado() -> bool:
    """Se dá para enviar. A tela usa isto para não oferecer o que não funciona."""
    return all(os.environ.get(nome) for nome in (HOST_ENV, USUARIO_ENV, SENHA_ENV))


def montar_mensagem(descricao: str, contexto: dict | None = None) -> EmailMessage:
    """Monta o e-mail sem tocar na rede — é o que o teste consegue inspecionar."""
    remetente = os.environ.get(USUARIO_ENV)
    destino = os.environ.get(SUPORTE_ENV) or SUPORTE_PADRAO
    if not remetente or not destino:
        raise RelatoNaoConfigurado(
            f"defina {USUARIO_ENV} para habilitar o relato de problemas")

    msg = EmailMessage()
    msg["Subject"] = ASSUNTO
    resposta = (contexto or {}).get("email")
    if resposta:
        # assim o suporte responde à pessoa com um clique, sem procurar o
        # endereço no meio do texto
        msg["Reply-To"] = resposta
    msg["From"] = remetente
    msg["To"] = destino
    corpo = descricao[:LIMITE_DESCRICAO]
    if contexto:
        corpo += "\n\n---\n" + "\n".join(f"{chave}: {valor}"
                                         for chave, valor in contexto.items())
    msg.set_content(corpo)
    return msg


def enviar_relato(descricao: str, contexto: dict | None = None,
                  smtp_factory=None) -> None:
    """Manda o relato para o e-mail de suporte.

    `smtp_factory` existe para o teste: por padrão é o `SMTP_SSL` de verdade,
    e no teste vira um duplo que registra a chamada sem abrir conexão.
    """
    if not configurado():
        faltando = [nome for nome in (HOST_ENV, USUARIO_ENV, SENHA_ENV)
                    if not os.environ.get(nome)]
        raise RelatoNaoConfigurado(
            "envio de relato não configurado no servidor; falta: " + ", ".join(faltando))

    msg = montar_mensagem(descricao, contexto)
    host = os.environ[HOST_ENV]
    porta = int(os.environ.get(PORTA_ENV) or PORTA_PADRAO)
    fabrica = smtp_factory or smtplib.SMTP_SSL
    try:
        with fabrica(host, porta) as smtp:
            smtp.login(os.environ[USUARIO_ENV], os.environ[SENHA_ENV])
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as erro:
        # OSError cobre DNS, recusa de conexão e timeout — tudo que é "agora não
        # deu"; quem chama transforma em 502, que é falha de gateway, não do
        # funcionário que escreveu o relato.
        raise FalhaNoEnvio(str(erro)) from erro
