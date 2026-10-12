"""Interface Streamlit. Fina de propósito: a lógica fica em src/.

Regra de ouro do produto: nada entra no currículo sem um fato confirmado na base. Aqui a pessoa só
confirma, edita e exporta; as regras são impostas em src/render.py.
"""
from __future__ import annotations

import streamlit as st

from src import config, exemplo, export, interview, registro, saidas, sessao, tailor
from src.kb import ARQUIVOS_FATOS, KB, ErroBase
from src.llm import LLM, Configuracao, ErroConfig, ErroLLM
from src.texto import extrair_contato_local, ler_arquivo, palpite_nome

FALHOU = object()  # sentinela: a ação deu erro e a mensagem já foi mostrada
TIPOS_ARQUIVO = ["pdf", "docx", "md", "txt"]
CAMPOS_CONTATO = [("nome", "Nome completo"), ("titulo_padrao", "Título padrão (português)"),
                  ("titulo_padrao_en", "Título padrão (inglês)"), ("local", "Cidade e país"),
                  ("telefone", "Telefone"), ("email", "E-mail"), ("linkedin", "LinkedIn (endereço)"),
                  ("site", "Site ou portfólio")]
ROTULO_DESTINO = {"perfil": "Perfil", "habilidades": "Habilidades", "formacao": "Formação",
                  "certificacoes": "Certificações", "idiomas": "Idiomas", "nova_experiencia": "Nova experiência"}
ROTULO_STATUS = {"coberto": "coberto", "parcial": "parcial", "lacuna": "lacuna"}


# ------------------------------------------------------------------ infraestrutura

def estado_inicial() -> None:
    for chave, valor in (("chat", []), ("rev_id", 0), ("rev_entrevista", None), ("rev_importacao", None), ("analise_id", 0),
                         ("analise", None), ("vaga_analisada", ""), ("rev_lacuna", None), ("gen_id", 0),
                         ("resultado", None), ("trad", None), ("trad_id", 0), ("base_v", 0),
                         ("msg", None)):
        if chave not in st.session_state:
            st.session_state[chave] = valor
    # Uma vez por sessão do navegador: recupera a conversa e as revisões que estavam salvas em disco.
    if not st.session_state.get("_sessao_carregada"):
        st.session_state["_sessao_carregada"] = True
        salvo = sessao.carregar(config.base_dir())
        if salvo["chat"] or salvo["rev_importacao"] or salvo["rev_entrevista"]:
            st.session_state["chat"] = salvo["chat"]
            st.session_state["rev_importacao"] = salvo["rev_importacao"] or None
            st.session_state["rev_entrevista"] = salvo["rev_entrevista"] or None
            st.session_state["rev_id"] += 1
            partes = []
            if salvo["chat"]:
                partes.append(f"a conversa ({sum(1 for m in salvo['chat'] if m['role'] == 'user')} resposta(s) sua(s))")
            if salvo["rev_importacao"] or salvo["rev_entrevista"]:
                partes.append("revisões de fatos que ainda não foram salvas na base")
            st.session_state["msg"] = ("info", "Recuperei o que estava salvo: " + " e ".join(partes) + ".")


def persistir(kb: KB) -> None:
    """Grava a conversa e as revisões pendentes. Roda a cada execução, inclusive antes de um st.rerun()."""
    s = st.session_state
    if s.get("_sessao_carregada"):
        sessao.salvar(kb.base, s.get("chat") or [], s.get("rev_importacao"), s.get("rev_entrevista"))


def configuracao_do_provedor():
    """(Configuracao, None) ou (None, mensagem de erro)."""
    config.carregar_env()
    try:
        return Configuracao.do_ambiente(), None
    except ErroConfig as e:
        return None, str(e)


def obter_llm(kb: KB) -> LLM:
    cfg, erro = configuracao_do_provedor()
    if erro:
        raise ErroConfig(erro)
    return LLM(cfg, segredos=kb.segredos(), log_dir=config.logs_dir() if registro.ativo() else None)


def executar(rotulo: str, funcao, *args):
    """Roda uma ação que pode falhar e mostra o erro em português, sem derrubar a tela."""
    try:
        with st.spinner(rotulo):
            return funcao(*args)
    except (ErroLLM, ErroBase) as e:
        st.error(str(e))
        return FALHOU


def mostrar_mensagem() -> None:
    """Mostra a mensagem pendente num espaço fixo acima das abas.

    O espaço (st.empty) existe sempre, com ou sem mensagem. Se o elemento aparecesse e sumisse, o
    Streamlit reiniciaria a seleção das abas e a tela voltaria para a aba 1 a cada ação.
    """
    espaco = st.empty()
    msg = st.session_state.get("msg")
    if msg:
        getattr(espaco, msg[0])(msg[1])
        st.session_state["msg"] = None


def avisar(tipo: str, texto: str) -> None:
    """Guarda uma mensagem para aparecer depois do próximo rerun."""
    st.session_state["msg"] = (tipo, texto)


def tela_configuracao(erro: str) -> None:
    st.warning("O aplicativo ainda não está ligado a um provedor de IA.")
    st.markdown(
        f"**O que falta:** {erro}\n\n"
        "1. Na pasta do aplicativo, copie o arquivo `.env.example` e chame a cópia de `.env`.\n"
        "2. Abra o `.env` no Bloco de Notas e cole a sua chave na linha do provedor que você usa.\n"
        "3. Salve, feche e abra o aplicativo de novo.\n\n"
        "Enquanto isso, a aba **3. Minha base** continua funcionando.")


# ------------------------------------------------------------------------- revisão

def formulario_revisao(chave: str, propostas: list, rev_id: int, kb: KB):
    """Tela de revisão. Fatos 'dito' vêm marcados, 'sugerido' (inferência da IA) vêm desmarcados.

    Devolve o dicionário de contagens quando salvou, ou None. A key leva o contador (rev_id), senão
    checkbox e texto antigos reaparecem.
    """
    marcados: set = set()
    metas: dict = {}
    with st.form(f"form_{chave}_{rev_id}"):
        st.markdown("**Revise antes de salvar.** Só o que estiver marcado entra na sua base como confirmado.")
        for i, p in enumerate(propostas):
            if p.destino == "nova_experiencia":
                nome = f"Nova experiência: {p.meta.get('empresa') or 'preencha os dados'}"
            elif p.destino in ROTULO_DESTINO:
                nome = ROTULO_DESTINO[p.destino]
            else:
                nome = f"Experiência: {p.destino}"
            st.markdown(f"##### {nome}")
            for problema in p.problemas:
                st.warning(problema)
            if p.destino == "nova_experiencia":
                c1, c2, c3 = st.columns(3)
                k = f"{chave}_{rev_id}_{i}"
                metas[i] = {
                    "empresa": c1.text_input("Empresa", p.meta.get("empresa", ""), key=f"{k}_empresa"),
                    "cargo": c2.text_input("Cargo", p.meta.get("cargo", ""), key=f"{k}_cargo"),
                    "local": c3.text_input("Local", p.meta.get("local", ""), key=f"{k}_local"),
                }
                c4, c5 = st.columns(2)
                metas[i]["inicio"] = c4.text_input("Início (AAAA-MM)", p.meta.get("inicio", ""), key=f"{k}_inicio")
                metas[i]["fim"] = c5.text_input("Fim (AAAA-MM ou atual)", p.meta.get("fim", ""), key=f"{k}_fim")
            for j, f in enumerate(p.fatos):
                etiqueta = f.texto if f.origem == "dito" else f"{f.texto}  (sugestão da IA, confirme só se for verdade)"
                if st.checkbox(etiqueta, value=f.marcado_por_padrao, key=f"{chave}_{rev_id}_{i}_{j}"):
                    marcados.add((i, j))
        c1, c2 = st.columns(2)
        so_marcados = c1.form_submit_button("Salvar marcados como confirmados")
        com_pendentes = c2.form_submit_button("Salvar marcados e guardar o resto como pendente")
    if not (so_marcados or com_pendentes):
        return None
    for i, meta in metas.items():
        propostas[i].meta = {**propostas[i].meta, **{k: v.strip() for k, v in meta.items()}}
    r = executar("Salvando na base...", interview.aplicar, kb, propostas, marcados, bool(com_pendentes))
    return None if r is FALHOU else r


def resumo_salvamento(r: dict) -> str:
    partes = [f"{r['confirmados']} fato(s) confirmado(s)"]
    if r["pendentes"]:
        partes.append(f"{r['pendentes']} guardado(s) como pendente(s)")
    if r["experiencias_criadas"]:
        partes.append(f"{r['experiencias_criadas']} experiência(s) criada(s)")
    if r["ignorados"]:
        partes.append(f"{r['ignorados']} já existia(m)")
    return "Salvo: " + ", ".join(partes) + "."


# --------------------------------------------------------------------- 1. entrevista

def importar_curriculo(kb: KB, arquivo) -> None:
    texto = ler_arquivo(arquivo.name, arquivo.getvalue())
    if len(texto) < 80:
        st.error("Não consegui ler texto desse arquivo. Se for um PDF escaneado (imagem), envie uma versão em texto.")
        return
    # Contato é preenchido aqui, por regex, e nunca passa pelo modelo.
    achado = extrair_contato_local(texto)
    nome = palpite_nome(texto)
    if nome:
        achado["nome"] = nome
    atual = kb.contato()
    novos = {k: v for k, v in achado.items() if not atual.get(k)}
    if novos:
        kb.salvar_contato({**atual, **novos})
    try:
        llm = obter_llm(kb)
    except ErroConfig as e:
        st.error(str(e))
        return
    props = executar("Lendo o currículo (pode levar um minuto)...", interview.extrair, llm, kb, texto,
                     "curriculo importado")
    if props is FALHOU:
        return
    st.session_state["rev_id"] += 1
    st.session_state["rev_importacao"] = props
    avisar("info" if props else "warning",
           ("Currículo lido. Contato preenchido na aba Minha base. Revise e salve os fatos abaixo antes de conversar."
            if props else "Não encontrei fatos novos nesse currículo."))
    st.rerun()


LIMITE_RESPOSTAS_SUGERIDO = 8  # depois disso o app sugere encerrar a rodada


def textos_aguardando_revisao() -> list[str]:
    """Fatos que a pessoa ainda não revisou. O entrevistador os trata como já informados."""
    textos: list[str] = []
    for chave in ("rev_importacao", "rev_entrevista"):
        for p in st.session_state.get(chave) or []:
            textos += [f.texto for f in p.fatos]
    return textos


def aba_entrevista(kb: KB, config_erro: str | None) -> None:
    st.info("Privacidade: não digite telefone, e-mail nem endereço no chat. Eles ficam só no seu computador "
            "e não são enviados à IA. O que você escreve aqui é enviado ao provedor de IA configurado.")
    if config_erro:
        tela_configuracao(config_erro)
        return
    with st.expander("Importar um currículo existente (opcional, acelera a entrevista)"):
        arq = st.file_uploader("Currículo em PDF, DOCX, MD ou TXT", type=TIPOS_ARQUIVO, key="up_curriculo")
        if st.button("Ler este currículo", key="btn_importar", disabled=arq is None):
            importar_curriculo(kb, arq)

    # Revisão do currículo importado: espaço próprio, que a conversa nunca substitui.
    importados = st.session_state["rev_importacao"]
    if importados:
        st.markdown("#### Revisão do currículo importado")
        st.warning("Salve esta revisão antes de seguir. Enquanto ela não for salva, nada do currículo está na sua base "
                   "e a análise de vagas não enxerga esses fatos.")
        r = formulario_revisao("imp", importados, st.session_state["rev_id"], kb)
        if r:
            st.session_state["rev_importacao"] = None
            avisar("success", resumo_salvamento(r) + " A conversa agora só aprofunda o que falta.")
            st.rerun()
        if st.button("Descartar esta revisão", key="btn_descartar_imp"):
            st.session_state["rev_importacao"] = None
            st.rerun()

    st.markdown("#### Conversa")
    if st.session_state["rev_entrevista"] and not importados:
        st.warning("Há fatos da última rodada aguardando a sua revisão, logo abaixo da conversa.")
    with st.chat_message("assistant"):
        st.write(interview.abertura(kb))
    for m in st.session_state["chat"]:
        with st.chat_message(m["role"]):
            st.write(m["content"])
    texto = st.chat_input("Responda aqui")
    if texto:
        try:
            llm = obter_llm(kb)
        except ErroConfig as e:
            st.error(str(e))
            return
        resposta = executar("Pensando...", interview.responder, llm, kb, st.session_state["chat"], texto,
                            textos_aguardando_revisao())
        if resposta is not FALHOU:
            st.session_state["chat"] += [{"role": "user", "content": texto},
                                         {"role": "assistant", "content": resposta}]
            st.rerun()

    respostas = sum(1 for m in st.session_state["chat"] if m["role"] == "user")
    if respostas >= LIMITE_RESPOSTAS_SUGERIDO:
        st.info(f"Você já respondeu {respostas} perguntas. É um bom momento para clicar em **Encerrar rodada e "
                "revisar**: o que você confirmar fica salvo e uma nova rodada não repete as perguntas.")
    revisao_pendente = bool(st.session_state["rev_entrevista"])
    if st.button("Encerrar rodada e revisar", key="btn_encerrar", disabled=respostas == 0 or revisao_pendente):
        props = executar("Extraindo os fatos da conversa...", interview.extrair_da_conversa, obter_llm(kb), kb,
                         st.session_state["chat"])
        if props is not FALHOU:
            st.session_state["rev_id"] += 1
            st.session_state["rev_entrevista"] = props
            if not props:
                avisar("warning", "Não encontrei fatos novos nessa conversa.")
            st.rerun()
    if revisao_pendente:
        st.caption("Salve ou descarte a revisão abaixo antes de encerrar outra rodada.")
    if respostas and st.button("Começar uma conversa nova", key="btn_nova_conversa"):
        # a conversa fica salva em disco até aqui; revisões pendentes não são afetadas
        st.session_state["chat"] = []
        st.rerun()

    props = st.session_state["rev_entrevista"]
    if props:
        st.markdown("#### Revisão da conversa")
        r = formulario_revisao("ent", props, st.session_state["rev_id"], kb)
        if r:
            st.session_state["rev_entrevista"] = None
            st.session_state["chat"] = []
            avisar("success", resumo_salvamento(r) + " A conversa foi reiniciada; o que já está na base não será perguntado de novo.")
            st.rerun()
        if st.button("Descartar esta revisão", key="btn_descartar_ent"):
            st.session_state["rev_entrevista"] = None
            st.rerun()


# ----------------------------------------------------------------------- 2. vaga

def texto_da_vaga() -> str:
    escrito = st.text_area("Cole aqui o texto da vaga", height=220, key="vaga_texto")
    arq = st.file_uploader("Ou envie a vaga em arquivo", type=TIPOS_ARQUIVO, key="vaga_arquivo")
    if escrito.strip():
        return escrito.strip()
    return ler_arquivo(arq.name, arq.getvalue()) if arq is not None else ""


def analisar_vaga(kb: KB, vaga: str) -> None:
    analise = executar("Analisando a vaga contra a sua base...", tailor.analisar, obter_llm(kb), kb, vaga)
    if analise is FALHOU:
        return
    st.session_state["analise_id"] += 1
    st.session_state.update(analise=analise, vaga_analisada=vaga, resultado=None, trad=None, rev_lacuna=None)
    st.rerun()


def mostrar_analise(analise: dict) -> None:
    st.markdown(f"**{analise['titulo_vaga'] or 'Vaga'}**" + (f" · {analise['empresa']}" if analise["empresa"] else ""))
    linhas = [f"- **{ROTULO_STATUS[r['status']]}** ({'obrigatório' if r['tipo'] == 'obrigatorio' else 'desejável'}): "
              f"{r['requisito']}" for r in analise["requisitos"]]
    st.markdown("\n".join(linhas) or "Nenhum requisito identificado.")
    if analise["palavras_chave"]:
        st.caption("Palavras-chave da vaga: " + ", ".join(analise["palavras_chave"]))
    if analise["observacoes"]:
        st.caption("Observação da IA (opinião, não fato): " + analise["observacoes"])


def secao_lacunas(kb: KB, analise: dict) -> None:
    perguntas = tailor.perguntas_lacuna(analise)
    if not perguntas:
        st.success("A base cobre os requisitos desta vaga. Nenhuma pergunta pendente.")
        return
    st.markdown("#### Lacunas: o que a vaga pede e a sua base não comprova")
    st.caption("Responda só o que for verdade. Se você não tem a experiência, marque a caixa: ela não vai para o currículo.")
    aid = st.session_state["analise_id"]
    for i, r in enumerate(perguntas):
        st.markdown(f"**{r['requisito']}**  ({'obrigatório' if r['tipo'] == 'obrigatorio' else 'desejável'})")
        st.text_area(r["pergunta"], key=f"lac_{aid}_{i}", height=80)
        st.checkbox("Não tenho essa experiência", key=f"lacnao_{aid}_{i}")
    if st.button("Salvar respostas na base", key="btn_lacunas"):
        pares = [(r["pergunta"], st.session_state.get(f"lac_{aid}_{i}", ""), bool(st.session_state.get(f"lacnao_{aid}_{i}")))
                 for i, r in enumerate(perguntas)]
        props = executar("Lendo as suas respostas...", tailor.extrair_respostas, obter_llm(kb), kb, pares)
        if props is not FALHOU:
            if not props:
                st.info("Nenhuma resposta para registrar.")
            else:
                st.session_state["rev_id"] += 1
                st.session_state["rev_lacuna"] = props
                st.rerun()
    props = st.session_state["rev_lacuna"]
    if props:
        r = formulario_revisao("lac", props, st.session_state["rev_id"], kb)
        if r:
            st.session_state["rev_lacuna"] = None
            avisar("success", resumo_salvamento(r) + " Use \"Reanalisar com a base atualizada\" para ver o efeito.")
            st.rerun()
    if st.button("Reanalisar com a base atualizada", key="btn_reanalisar"):
        analisar_vaga(kb, st.session_state["vaga_analisada"])


def secao_traducao(kb: KB, idioma: str) -> bool:
    """Cargos sem tradução: a IA sugere, ela confirma. Devolve True se ainda há pendência."""
    if idioma == kb.idioma_base():
        return False
    pendentes = [e for e in kb.experiencias() if not e.meta.get(f"cargo_{idioma}")]
    if not pendentes:
        return False
    nome = {"pt": "português", "en": "inglês"}[idioma]
    st.markdown("#### Tradução dos cargos")
    st.caption(f"A sua base está em {({'pt': 'inglês', 'en': 'português'})[idioma]}. Para gerar em {nome}, confirme como os cargos "
               "e locais devem aparecer. A IA sugere, você decide.")
    trad = st.session_state["trad"]
    if trad is None or trad["idioma"] != idioma:
        if st.button("Sugerir tradução dos cargos", key="btn_sugerir_trad"):
            sug = executar("Sugerindo traduções...", tailor.sugerir_traducoes, obter_llm(kb), kb, idioma)
            if sug is not FALHOU:
                st.session_state["trad_id"] += 1
                st.session_state["trad"] = {"idioma": idioma, "itens": sug}
                st.rerun()
        return True
    tid = st.session_state["trad_id"]
    for s in trad["itens"]:
        c1, c2 = st.columns(2)
        c1.text_input(f"{s['empresa']}: {s['cargo_original']}", s["cargo"], key=f"trad_{tid}_{s['slug']}_c")
        c2.text_input(f"Local ({s['local_original'] or 'sem local'})", s["local"], key=f"trad_{tid}_{s['slug']}_l")
    if st.button("Confirmar traduções", key="btn_confirmar_trad"):
        confirmadas = [{"slug": s["slug"], "cargo": st.session_state.get(f"trad_{tid}_{s['slug']}_c", ""),
                        "local": st.session_state.get(f"trad_{tid}_{s['slug']}_l", "")} for s in trad["itens"]]
        n = executar("Salvando...", tailor.aplicar_traducoes, kb, idioma, confirmadas)
        if n is not FALHOU:
            st.session_state["trad"] = None
            avisar("success", f"{n} tradução(ões) confirmada(s).")
            st.rerun()
    return True


def mostrar_cobertura(cob: dict) -> None:
    st.markdown(f"**Palavras-chave da vaga usadas com respaldo na base: {cob['percentual']}%**")
    if cob["usadas"]:
        st.caption("Usadas: " + ", ".join(cob["usadas"]))
    if cob["usadas_sem_base"]:
        st.warning("Aparecem no currículo, mas a base não sustenta (confira): " + ", ".join(cob["usadas_sem_base"]))
    if cob["fora_com_base"]:
        st.caption("A base tem, mas o currículo não usou (dá para incluir editando): " + ", ".join(cob["fora_com_base"]))
    if cob["fora_sem_base"]:
        st.caption("Ficaram de fora por falta de base. É assim que deve ser, a menos que você tenha essa experiência "
                   "(responda nas lacunas): " + ", ".join(cob["fora_sem_base"]))
    if cob["fora_indeterminadas"] or cob["usadas_indeterminadas"]:
        st.caption("Sem como confirmar (a verificação por IA não rodou): "
                   + ", ".join(cob["fora_indeterminadas"] + cob["usadas_indeterminadas"]))


def secao_geracao(kb: KB, cfg: dict) -> None:
    analise, vaga = st.session_state["analise"], st.session_state["vaga_analisada"]
    aid = st.session_state["analise_id"]
    recomendado = tailor.recomendar_idioma(vaga, analise, cfg)
    st.markdown("#### Gerar o currículo")
    st.caption(f"Idioma recomendado pela vaga: {'português' if recomendado == 'pt' else 'inglês'}. A escolha é sua.")
    idioma = st.radio("Idioma do currículo", ["pt", "en"], index=0 if recomendado == "pt" else 1,
                      format_func=lambda x: "Português (PT-BR)" if x == "pt" else "English", horizontal=True,
                      key=f"idioma_{aid}")
    titulo = st.text_input("Título abaixo do nome (opcional, deixe vazio para usar um cargo da sua base)",
                           key=f"titulo_{aid}")
    if secao_traducao(kb, idioma):
        st.info("Confirme as traduções acima antes de gerar, ou gere assim mesmo: os cargos sem tradução ficam no idioma original.")
    if st.button("Gerar currículo", key="btn_gerar", type="primary"):
        res = executar("Gerando e verificando o currículo (pode levar um minuto)...", tailor.gerar, obter_llm(kb), kb,
                       vaga, analise, idioma, cfg, titulo or None)
        if res is not FALHOU:
            st.session_state["gen_id"] += 1
            st.session_state["resultado"] = res
            # a saída é gerada ANTES do text_area, para preencher o estado do widget nesta mesma execução
            st.session_state[f"md_{st.session_state['gen_id']}"] = res.curriculo.markdown
            st.rerun()


def secao_resultado(cfg: dict) -> None:
    res = st.session_state["resultado"]
    if res is None:
        return
    gid = st.session_state["gen_id"]
    cv = res.curriculo
    st.markdown("---")
    st.markdown("#### Resultado")
    if not res.verificacao_ia:
        st.warning("A verificação por IA não rodou nesta geração. Confira com mais atenção o que foi escrito.")
    if cv.alertas:
        with st.expander(f"Alertas ({len(cv.alertas)}): leia antes de enviar", expanded=True):
            for a in cv.alertas:
                st.warning(a)
    else:
        st.success("Nenhum alerta. Ainda assim, leia o currículo inteiro antes de enviar.")
    if cv.removidos:
        with st.expander(f"Removidos por falta de respaldo na base ({len(cv.removidos)})"):
            for r in cv.removidos:
                st.write(f"- {r['secao']}: {r['texto']}  ({r['motivo']})")
    mostrar_cobertura(res.cobertura)
    with st.expander("Rastro: de qual fato veio cada item"):
        for r in cv.rastro:
            st.write(f"- {r['texto']}  →  {', '.join(r['fontes_validas']) or 'sem fonte válida'}")

    texto = st.text_area("Currículo (pode editar; o PDF e o DOCX saem deste texto)", height=620, key=f"md_{gid}")
    try:
        pdf, paginas = export.gerar_pdf(texto)
        docx = export.gerar_docx(texto)
    except Exception as e:  # texto editado com algo que o exportador não aguenta
        st.error(f"Não consegui montar o PDF ou o DOCX com este texto ({type(e).__name__}). Revise a formatação.")
        return
    limite = int(cfg.get("max_paginas", 2))
    if paginas > limite:
        st.warning(f"O PDF tem {paginas} páginas e o limite configurado é {limite}. Corte conteúdo ou aumente max_paginas no config.yaml.")
    else:
        st.caption(f"O PDF tem {paginas} página(s).")
    c1, c2, c3 = st.columns(3)
    c1.download_button("Baixar PDF", pdf, file_name="curriculo.pdf", mime="application/pdf", key="dl_pdf")
    c2.download_button("Baixar DOCX", docx, file_name="curriculo.docx", key="dl_docx",
                       mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    c3.download_button("Baixar Markdown", texto, file_name="curriculo.md", mime="text/markdown", key="dl_md")
    if st.button("Salvar na pasta de saídas", key="btn_salvar_saida"):
        pasta = saidas.salvar_saida(texto, pdf, docx, st.session_state["vaga_analisada"], st.session_state["analise"])
        st.success(f"Salvo em: {pasta}")


def aba_vaga(kb: KB, config_erro: str | None, cfg: dict) -> None:
    if config_erro:
        tela_configuracao(config_erro)
        return
    if not kb.ids_confirmados():
        st.info("A sua base ainda não tem fatos confirmados. Faça a entrevista, importe um currículo ou use os dados de "
                "exemplo na barra lateral.")
        return
    # A análise só enxerga fatos CONFIRMADOS. Avisar antes evita culpar a vaga por uma base incompleta.
    if st.session_state["rev_importacao"] or st.session_state["rev_entrevista"]:
        st.warning("Há fatos aguardando a sua revisão na aba Entrevista. Enquanto não forem salvos, a análise não os vê.")
    for aviso in kb.diagnostico():
        st.warning(aviso)
    vaga = texto_da_vaga()
    if st.button("Analisar vaga", key="btn_analisar", disabled=not vaga):
        analisar_vaga(kb, vaga)
    analise = st.session_state["analise"]
    if not analise:
        return
    if vaga and vaga != st.session_state["vaga_analisada"]:
        st.caption("O texto da vaga mudou desde a última análise. Clique em Analisar vaga para atualizar.")
    mostrar_analise(analise)
    secao_lacunas(kb, analise)
    secao_geracao(kb, cfg)
    secao_resultado(cfg)


# ------------------------------------------------------------------------ 3. base

def secao_contato(kb: KB) -> None:
    st.markdown("#### Contato")
    st.caption("Estes dados ficam só no seu computador. Eles entram no cabeçalho do currículo e nunca são enviados à IA.")
    atual = kb.contato()
    with st.form(f"form_contato_{st.session_state['base_v']}"):
        valores = {k: st.text_input(rotulo, atual.get(k, ""), key=f"ct_{k}_{st.session_state['base_v']}")
                   for k, rotulo in CAMPOS_CONTATO}
        if st.form_submit_button("Salvar contato"):
            kb.salvar_contato(valores)
            st.session_state["base_v"] += 1
            avisar("success", "Contato salvo.")
            st.rerun()


def secao_pendentes(kb: KB) -> None:
    pend = kb.fatos("sugerido")
    st.markdown(f"#### Fatos pendentes ({len(pend)})")
    if not pend:
        st.caption("Nenhum fato pendente.")
        return
    st.caption("Sugestões que você ainda não confirmou. Pendentes nunca entram no currículo.")
    for f in pend:
        st.write(f"**{f.slug}**: {f.texto}")
        c1, c2, _ = st.columns([1, 1, 4])
        if c1.button("Confirmar", key=f"conf_{f.id}"):
            kb.confirmar(f.id)
            st.rerun()
        if c2.button("Remover", key=f"rem_{f.id}"):
            kb.remover(f.id)
            st.rerun()


def secao_editor(kb: KB) -> None:
    st.markdown("#### Editar arquivos da base")
    arquivos = list(kb.arquivos())
    slugs = list(dict.fromkeys(list(ARQUIVOS_FATOS) + arquivos))
    slug = st.selectbox("Arquivo", slugs, key="ed_arquivo")
    v = st.session_state["base_v"]
    st.caption("Cada fato é uma linha começando com - [confirmado] ou - [sugerido]. Linhas sem essa marca são ignoradas pela IA.")
    texto = st.text_area("Conteúdo", kb.ler_texto(slug), height=300, key=f"ed_{slug}_{v}")
    if st.button("Salvar arquivo", key="btn_salvar_arquivo"):
        try:
            kb.salvar_texto(slug, texto)
        except ErroBase as e:
            st.error(str(e))
        else:
            st.session_state["base_v"] += 1
            avisar("success", f"Arquivo '{slug}' salvo.")
            st.rerun()


def secao_nova_experiencia(kb: KB) -> None:
    st.markdown("#### Nova experiência")
    v = st.session_state["base_v"]
    with st.form(f"form_nova_exp_{v}"):
        c1, c2 = st.columns(2)
        meta = {"empresa": c1.text_input("Empresa", key=f"ne_emp_{v}"), "cargo": c2.text_input("Cargo", key=f"ne_cargo_{v}")}
        c3, c4, c5 = st.columns(3)
        meta["inicio"] = c3.text_input("Início (AAAA-MM)", key=f"ne_ini_{v}")
        meta["fim"] = c4.text_input("Fim (AAAA-MM ou atual)", key=f"ne_fim_{v}")
        meta["local"] = c5.text_input("Local", key=f"ne_loc_{v}")
        if st.form_submit_button("Criar experiência"):
            try:
                slug = kb.criar_experiencia(meta)
            except ErroBase as e:
                st.error(str(e))
            else:
                st.session_state["base_v"] += 1
                avisar("success", f"Experiência criada ('{slug}'). Edite o arquivo para acrescentar fatos.")
                st.rerun()


def aba_base(kb: KB) -> None:
    for erro in kb.erros:
        st.error(f"Arquivo com problema (ignorado até ser corrigido): {erro}")
    sem_marca = kb.linhas_sem_marca()
    if sem_marca:
        st.warning(f"{sem_marca} linha(s) sem marca [confirmado] ou [sugerido]. A IA ignora essas linhas.")
    if kb.mistura_idiomas():
        c = kb.composicao_idiomas()
        st.warning(f"A sua base mistura idiomas ({c['pt']} fatos em português, {c['en']} em inglês). Isso atrapalha as "
                   "verificações. Prefira manter os fatos em um idioma só.")
    secao_contato(kb)
    secao_pendentes(kb)
    secao_editor(kb)
    secao_nova_experiencia(kb)
    secao_registro()


def secao_registro() -> None:
    """Registro das chamadas à IA, para depurar e melhorar os prompts."""
    with st.expander("Registro das interações com a IA (para depuração)"):
        if not registro.ativo():
            st.caption("O registro está desligado (CV_LOG=0 no arquivo .env).")
            return
        st.caption(f"Cada chamada à IA fica salva em {registro.pasta()}, um arquivo por dia. O registro guarda o que "
                   "foi enviado (já sem telefone, e-mail e links) e a resposta recebida. Ele contém o conteúdo da sua "
                   "base e das suas conversas: apague a pasta antes de compartilhar o computador ou o projeto.")
        recentes = registro.ultimos(8)
        if not recentes:
            st.caption("Ainda não há chamadas registradas.")
            return
        for r in recentes:
            st.write("- " + registro.resumo(r))
        arqs = registro.arquivos()
        st.download_button(f"Baixar o registro de {arqs[0].stem}", arqs[0].read_bytes(), file_name=arqs[0].name,
                           mime="application/x-ndjson", key="dl_registro")


# ---------------------------------------------------------------------- barra lateral

def barra_lateral(kb: KB, cfg_provedor, config_erro: str | None) -> None:
    """Barra lateral compacta. Fica recolhida e só abre sozinha se faltar a configuração."""
    with st.sidebar:
        st.subheader("Configuração")
        if cfg_provedor:
            st.caption(f"{cfg_provedor.nome_provedor} · {cfg_provedor.modelo}")
            if st.button("Testar conexão", key="btn_testar"):
                r = executar("Testando...", lambda: obter_llm(kb).conversar(
                    [{"role": "user", "content": "Responda somente com a palavra OK."}], temperatura=0))
                if r is not FALHOU:
                    st.success("Conexão funcionando.")
        else:
            st.warning(config_erro)
        with st.expander("Pastas"):
            st.caption(f"Base: {kb.base}")
            st.caption(f"Currículos gerados: {config.saidas_dir()}")
        with st.expander("Dados de exemplo"):
            st.caption("Copia uma base fictícia, só se a sua estiver vazia.")
            if st.button("Copiar dados de exemplo", key="btn_exemplo"):
                if exemplo.copiar_exemplo(kb):
                    st.session_state["base_v"] += 1
                    avisar("success", "Dados de exemplo copiados. Use as vagas de exemplo na aba 2.")
                else:
                    avisar("warning", "A sua base já tem dados. Não copiei nada para não misturar.")
                st.rerun()


# ------------------------------------------------------------------------------ main

def main() -> None:
    cfg_provedor, config_erro = configuracao_do_provedor()
    # recolhida por padrão; abre sozinha só quando falta configurar o provedor
    st.set_page_config(page_title="Currículo sob medida", layout="wide",
                       initial_sidebar_state="expanded" if config_erro else "collapsed")
    estado_inicial()
    kb = KB(config.base_dir())
    cfg = config.carregar_config()
    try:
        barra_lateral(kb, cfg_provedor, config_erro)
        st.title("Currículo sob medida")
        st.caption("Nada entra no currículo sem um fato que você confirmou. A IA propõe, você decide.")
        mostrar_mensagem()
        aba1, aba2, aba3 = st.tabs(["1. Entrevista", "2. Currículo para uma vaga", "3. Minha base"])
        with aba1:
            aba_entrevista(kb, config_erro)
        with aba2:
            aba_vaga(kb, config_erro, cfg)
        with aba3:
            aba_base(kb)
    finally:
        # o finally também roda quando st.rerun() interrompe o script: nada digitado se perde
        persistir(kb)


if __name__ == "__main__":
    main()
