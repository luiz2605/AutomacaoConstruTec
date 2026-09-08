"""Camada web: upload, fila, download e limpeza.

Os testes usam uma planilha-base sintética e um orçamento injetado, para não
depender do arquivo real nem do PDF — mesma disciplina dos demais.
"""
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient           # noqa: E402

USUARIO, SENHA = "orcamentos", "senha-de-teste"


@pytest.fixture
def cliente(template_workbook_path, topics, monkeypatch, tmp_path):
    """Sobe a aplicação com a base sintética e o orçamento já interpretado.

    O cliente já vai autenticado: as rotas de orçamento exigem login, e o que
    estes testes conferem é o comportamento *depois* dele. A autenticação em si
    tem os seus próprios testes no fim do arquivo.
    """
    from webapp import app as modulo
    from webapp import service

    monkeypatch.setenv(service.BASE_ENV, str(template_workbook_path))
    monkeypatch.setenv("ORCAUTO_USUARIO", USUARIO)
    monkeypatch.setenv("ORCAUTO_SENHA", SENHA)

    from orcauto.config import CompositionConfig, Config, TargetConfig
    config = Config(compositions=CompositionConfig(sheets=["COMPOSICOES"],
                                                   service_code_re=r"^S"),
                    targets=TargetConfig(template_sheet="MODELO BASE"))
    monkeypatch.setattr(service, "carregar_config", lambda: config)

    original = service.processar_orcamento.__wrapped__ \
        if hasattr(service.processar_orcamento, "__wrapped__") else None
    from orcauto.pipeline import run as pipeline_run
    monkeypatch.setattr(service, "run",
                        lambda base, pdf, destino, cfg: pipeline_run(
                            base, None, destino, cfg, topics=topics))
    modulo.fila.__init__()
    client = TestClient(modulo.app)
    client.auth = (USUARIO, SENHA)
    return client, modulo.fila


@pytest.fixture
def cliente_anonimo(cliente):
    """O mesmo aplicativo, sem credenciais nenhuma."""
    client, fila = cliente
    anonimo = TestClient(client.app)
    return anonimo, fila


def _esperar(cliente, job_id, limite=30):
    for _ in range(limite * 10):
        corpo = cliente.get(f"/estado/{job_id}").json()
        if corpo["estado"] in ("pronto", "erro"):
            return corpo
        time.sleep(0.1)
    raise AssertionError("processamento não terminou")


def test_pagina_inicial_traz_o_formulario(cliente):
    client, _ = cliente
    resposta = client.get("/")
    assert resposta.status_code == 200
    assert 'id="form"' in resposta.text


def test_saude_confirma_a_planilha_base(cliente):
    client, _ = cliente
    corpo = client.get("/saude").json()
    assert corpo["ok"] is True and corpo["planilha_base"].endswith(".xlsx")


def test_recusa_arquivo_que_nao_e_pdf(cliente):
    client, _ = cliente
    resposta = client.post("/processar",
                           files={"arquivo": ("nota.txt", b"texto", "text/plain")})
    assert resposta.status_code == 400
    assert "PDF" in resposta.json()["detail"]


def test_recusa_arquivo_vazio(cliente):
    client, _ = cliente
    resposta = client.post("/processar",
                           files={"arquivo": ("vazio.pdf", b"", "application/pdf")})
    assert resposta.status_code == 400


def test_recusa_arquivo_grande_demais(cliente, monkeypatch):
    from webapp import app as modulo
    client, _ = cliente
    monkeypatch.setattr(modulo, "TAMANHO_MAXIMO", 10)
    resposta = client.post("/processar",
                           files={"arquivo": ("g.pdf", b"x" * 500, "application/pdf")})
    assert resposta.status_code == 413


def test_estado_de_trabalho_inexistente(cliente):
    client, _ = cliente
    assert client.get("/estado/naoexiste").status_code == 404
    assert client.get("/baixar/naoexiste").status_code == 404


def test_ciclo_completo_gera_e_entrega(cliente):
    client, fila = cliente
    envio = client.post("/processar",
                        files={"arquivo": ("ORC.pdf", b"%PDF-1.4 fake", "application/pdf")})
    assert envio.status_code == 202
    job_id = envio.json()["id"]

    corpo = _esperar(client, job_id)
    assert corpo["estado"] == "pronto", corpo.get("erro")
    assert corpo["abas_criadas"] == 1
    assert corpo["nome"] == "LEVANTAMENTO - ORC.xlsx"

    baixado = client.get(f"/baixar/{job_id}")
    assert baixado.status_code == 200
    assert baixado.content[:2] == b"PK"                       # é mesmo um .xlsx
    assert "LEVANTAMENTO" in baixado.headers["content-disposition"]


def test_download_apaga_o_trabalho_e_os_arquivos(cliente):
    client, fila = cliente
    job_id = client.post("/processar",
                         files={"arquivo": ("ORC.pdf", b"%PDF", "application/pdf")}
                         ).json()["id"]
    _esperar(client, job_id)
    pasta = fila.obter(job_id).pasta
    client.get(f"/baixar/{job_id}")
    assert fila.obter(job_id) is None
    assert not pasta.exists()                                 # nada fica no servidor


def test_pdf_e_apagado_logo_apos_o_processamento(cliente):
    client, fila = cliente
    job_id = client.post("/processar",
                         files={"arquivo": ("ORC.pdf", b"%PDF", "application/pdf")}
                         ).json()["id"]
    _esperar(client, job_id)
    job = fila.obter(job_id)
    assert not (job.pasta / job.nome_pdf).exists()
    assert job.resultado.caminho.exists()


def test_baixar_antes_de_terminar_devolve_conflito(cliente, monkeypatch):
    from webapp import jobs
    client, fila = cliente
    monkeypatch.setattr(jobs.Fila, "executar", lambda self, job_id: None)
    job_id = client.post("/processar",
                         files={"arquivo": ("ORC.pdf", b"%PDF", "application/pdf")}
                         ).json()["id"]
    assert client.get(f"/baixar/{job_id}").status_code == 409


def test_trabalho_expirado_e_removido(cliente):
    client, fila = cliente
    job_id = client.post("/processar",
                         files={"arquivo": ("ORC.pdf", b"%PDF", "application/pdf")}
                         ).json()["id"]
    _esperar(client, job_id)
    fila.vida_util = -1
    assert fila.limpar_expirados() >= 1
    assert client.get(f"/estado/{job_id}").status_code == 404


# ---------------------------------------------------------------------------
# Autenticação — o endereço passa a ser público, então toda rota que mostra ou
# entrega dado de orçamento precisa de login.
# ---------------------------------------------------------------------------

ROTAS_PROTEGIDAS = [
    ("get", "/"),
    ("post", "/processar"),
    ("get", "/estado/qualquer"),
    ("get", "/baixar/qualquer"),
]


@pytest.mark.parametrize("metodo, rota", ROTAS_PROTEGIDAS)
def test_sem_credenciais_recusa_com_401(cliente_anonimo, metodo, rota):
    client, _ = cliente_anonimo
    resposta = getattr(client, metodo)(rota)
    assert resposta.status_code == 401, rota
    # sem o desafio o navegador não abre a caixa de login
    assert resposta.headers.get("www-authenticate") == "Basic"


@pytest.mark.parametrize("metodo, rota", ROTAS_PROTEGIDAS)
def test_credenciais_erradas_recusam_com_401(cliente_anonimo, metodo, rota):
    client, _ = cliente_anonimo
    client.auth = (USUARIO, "senha-errada")
    assert getattr(client, metodo)(rota).status_code == 401, rota
    client.auth = ("outro-usuario", SENHA)
    assert getattr(client, metodo)(rota).status_code == 401, rota


def test_credenciais_certas_liberam_o_fluxo_completo(cliente):
    """Com login, tudo se comporta exatamente como antes da autenticação."""
    client, _ = cliente
    assert client.get("/").status_code == 200

    envio = client.post("/processar",
                        files={"arquivo": ("ORC.pdf", b"%PDF-1.4 fake", "application/pdf")})
    assert envio.status_code == 202
    job_id = envio.json()["id"]

    corpo = _esperar(client, job_id)
    assert corpo["estado"] == "pronto", corpo.get("erro")
    baixado = client.get(f"/baixar/{job_id}")
    assert baixado.status_code == 200 and baixado.content[:2] == b"PK"


@pytest.mark.parametrize("metodo, rota", ROTAS_PROTEGIDAS)
def test_sem_senha_no_ambiente_responde_503_e_nao_401(cliente_anonimo, monkeypatch,
                                                      metodo, rota):
    """Servidor mal configurado tem de dizer isso, não fingir senha errada."""
    client, _ = cliente_anonimo
    monkeypatch.delenv("ORCAUTO_SENHA", raising=False)
    client.auth = (USUARIO, SENHA)
    resposta = getattr(client, metodo)(rota)
    assert resposta.status_code == 503, rota
    assert "não configurada" in resposta.json()["detail"]


def test_sem_senha_no_ambiente_nao_abre_a_rota(cliente_anonimo, monkeypatch):
    """Sem senha configurada e sem credenciais: recusa, nunca libera."""
    client, _ = cliente_anonimo
    monkeypatch.delenv("ORCAUTO_SENHA", raising=False)
    assert client.get("/").status_code == 503


def test_saude_responde_sem_login(cliente_anonimo):
    """É o health check do Render e não devolve nada de orçamento."""
    client, _ = cliente_anonimo
    resposta = client.get("/saude")
    assert resposta.status_code == 200
    assert resposta.json()["ok"] is True


def test_saude_responde_mesmo_sem_senha_configurada(cliente_anonimo, monkeypatch):
    client, _ = cliente_anonimo
    monkeypatch.delenv("ORCAUTO_SENHA", raising=False)
    assert client.get("/saude").status_code == 200


def test_usuario_padrao_quando_a_variavel_nao_e_declarada(cliente_anonimo, monkeypatch):
    """`ORCAUTO_USUARIO` é opcional; sem ela vale 'orcamentos'."""
    client, _ = cliente_anonimo
    monkeypatch.delenv("ORCAUTO_USUARIO", raising=False)
    client.auth = ("orcamentos", SENHA)
    assert client.get("/").status_code == 200


def test_senha_com_acento_no_ambiente_recusa_sem_derrubar_a_rota(cliente_anonimo,
                                                                 monkeypatch):
    """Senha com acento não funciona em HTTP Basic — mas tem de dar 401, não 500.

    O cabeçalho Basic é decodificado como ASCII pelo FastAPI, então uma senha
    acentuada nunca chega inteira. O risco real era outro: `compare_digest` em
    `str` levanta TypeError com caractere fora do ASCII, e o operador que
    configurasse `ORCAUTO_SENHA=produção` derrubaria toda requisição com 500.
    Comparando em bytes, a resposta é uma recusa limpa.
    """
    client, _ = cliente_anonimo
    monkeypatch.setenv("ORCAUTO_SENHA", "produção-2026")
    client.auth = (USUARIO, "producao-2026")
    assert client.get("/").status_code == 401


# ---------------------------------------------------------------------------
# Relato de problema — o funcionário descreve o erro na própria tela e o texto
# vai por e-mail para o suporte. Nenhum teste abre conexão SMTP de verdade.
# ---------------------------------------------------------------------------

SMTP_ENV = {
    "ORCAUTO_SMTP_HOST": "smtp.exemplo.com",
    "ORCAUTO_SMTP_PORTA": "465",
    "ORCAUTO_SMTP_USUARIO": "orcauto@exemplo.com",
    "ORCAUTO_SMTP_SENHA": "senha-smtp",
    "ORCAUTO_EMAIL_SUPORTE": "suporte@exemplo.com",
}


class SMTPFalso:
    """Duplo de `smtplib.SMTP_SSL` que registra em vez de conectar."""
    enviados: list = []

    def __init__(self, host, porta):
        self.host, self.porta = host, porta

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def login(self, usuario, senha):
        self.usuario, self.senha = usuario, senha

    def send_message(self, msg):
        SMTPFalso.enviados.append({"host": self.host, "porta": self.porta,
                                   "de": msg["From"], "para": msg["To"],
                                   "assunto": msg["Subject"],
                                   "corpo": msg.get_content()})


@pytest.fixture
def smtp(monkeypatch):
    """SMTP configurado e falsificado; devolve a lista de e-mails 'enviados'."""
    import smtplib
    for chave, valor in SMTP_ENV.items():
        monkeypatch.setenv(chave, valor)
    SMTPFalso.enviados = []
    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTPFalso)
    return SMTPFalso.enviados


def test_relatar_sem_credenciais_recusa_com_401(cliente_anonimo, smtp):
    client, _ = cliente_anonimo
    resposta = client.post("/relatar", data={"descricao": "está errado"})
    assert resposta.status_code == 401
    assert smtp == []                       # nada sai sem login


def test_relatar_com_descricao_vazia_recusa_com_400(cliente, smtp):
    client, _ = cliente
    for vazio in ("", "   ", "\n\t "):
        resposta = client.post("/relatar", data={"descricao": vazio})
        assert resposta.status_code == 400, repr(vazio)
        assert "Descreva o problema" in resposta.json()["detail"]
    assert smtp == []


def test_relatar_envia_o_email_para_o_suporte(cliente, smtp):
    client, _ = cliente
    resposta = client.post("/relatar",
                           data={"descricao": "  A aba PISOS veio sem a coluna de cimento.  "})
    assert resposta.status_code == 200 and resposta.json() == {"ok": True}

    assert len(smtp) == 1
    email = smtp[0]
    assert email["para"] == "suporte@exemplo.com"
    assert email["de"] == "orcauto@exemplo.com"
    assert (email["host"], email["porta"]) == ("smtp.exemplo.com", 465)
    assert "A aba PISOS veio sem a coluna de cimento." in email["corpo"]
    assert f"usuario: {USUARIO}" in email["corpo"]        # quem relatou


def test_relato_leva_o_contexto_do_processamento(cliente, smtp):
    """O suporte recebe arquivo, estado e erro — o que o funcionário não digita."""
    client, _ = cliente
    job_id = client.post("/processar",
                         files={"arquivo": ("ORC.pdf", b"%PDF", "application/pdf")}
                         ).json()["id"]
    _esperar(client, job_id)

    client.post("/relatar", data={"descricao": "conferir", "job_id": job_id})
    corpo = smtp[0]["corpo"]
    assert f"job_id: {job_id}" in corpo
    assert "arquivo: ORC.pdf" in corpo
    assert "estado: pronto" in corpo


def test_falha_no_envio_responde_502(cliente, monkeypatch, smtp):
    """SMTP fora do ar é problema de gateway, não de quem escreveu o relato."""
    import smtplib

    def recusa(host, porta):
        raise smtplib.SMTPConnectError(421, "servidor indisponivel")

    monkeypatch.setattr(smtplib, "SMTP_SSL", recusa)
    client, _ = cliente
    resposta = client.post("/relatar", data={"descricao": "não gerou a aba MURO"})
    assert resposta.status_code == 502
    assert "Tente de novo" in resposta.json()["detail"]


def test_conexao_recusada_tambem_responde_502(cliente, monkeypatch, smtp):
    """OSError (DNS, recusa, timeout) não pode escapar como 500."""
    import smtplib

    def recusa(host, porta):
        raise OSError("Connection refused")

    monkeypatch.setattr(smtplib, "SMTP_SSL", recusa)
    client, _ = cliente
    assert client.post("/relatar", data={"descricao": "x"}).status_code == 502


def test_sem_smtp_configurado_responde_503(cliente, monkeypatch):
    """Servidor sem SMTP diz que não está configurado, não que o envio falhou."""
    client, _ = cliente
    for chave in SMTP_ENV:
        monkeypatch.delenv(chave, raising=False)
    resposta = client.post("/relatar", data={"descricao": "algo errado"})
    assert resposta.status_code == 503
    assert "não foi configurado" in resposta.json()["detail"]


def test_link_de_relato_so_aparece_com_smtp_configurado(cliente, monkeypatch, smtp):
    client, _ = cliente
    assert "relato-abrir" in client.get("/").text
    for chave in SMTP_ENV:
        monkeypatch.delenv(chave, raising=False)
    assert 'class="link relato-abrir"' not in client.get("/").text


def test_descricao_muito_longa_e_truncada(cliente, smtp):
    """Um relato gigante não pode virar um e-mail impossível de ler."""
    from webapp.relatos import LIMITE_DESCRICAO
    client, _ = cliente
    client.post("/relatar", data={"descricao": "x" * (LIMITE_DESCRICAO + 500)})
    assert smtp[0]["corpo"].count("x") == LIMITE_DESCRICAO


def test_pdf_nao_reconhecido_nao_culpa_a_planilha_base(cliente, monkeypatch):
    """Zero itens lidos é problema de leitura do PDF, não de cliente/tabela."""
    from webapp import service
    from orcauto.pipeline import run as pipeline_run
    monkeypatch.setattr(service, "run",
                        lambda base, pdf, destino, cfg: pipeline_run(
                            base, None, destino, cfg, topics=[]))
    client, _ = cliente
    job_id = client.post("/processar",
                         files={"arquivo": ("ORC.pdf", b"%PDF", "application/pdf")}
                         ).json()["id"]
    corpo = _esperar(client, job_id)
    assert corpo["estado"] == "erro"
    assert "formato deste PDF não foi reconhecido" in corpo["erro"]
    assert "planilha-base" not in corpo["erro"]
    assert "cliente/tabela" not in corpo["erro"]


def test_itens_lidos_sem_composicao_mantem_a_mensagem_antiga(cliente, monkeypatch):
    """O outro caso continua dizendo o que já dizia — este não mudou."""
    from webapp import service
    from orcauto.pdf_budget import BudgetItem, Topic
    from orcauto.pipeline import run as pipeline_run
    sem_par = Topic(9, "SEM PAR", [
        BudgetItem("9.1", "ZZZ999", "SERVICO INEXISTENTE", "M2", 1.0, 1.0, 1.0, 1, 9, "SEM PAR")])
    monkeypatch.setattr(service, "run",
                        lambda base, pdf, destino, cfg: pipeline_run(
                            base, None, destino, cfg, topics=[sem_par]))
    client, _ = cliente
    job_id = client.post("/processar",
                         files={"arquivo": ("ORC.pdf", b"%PDF", "application/pdf")}
                         ).json()["id"]
    corpo = _esperar(client, job_id)
    assert corpo["estado"] == "erro"
    assert "nenhum item dele encontrou composição na planilha-base" in corpo["erro"]
