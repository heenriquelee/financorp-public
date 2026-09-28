"""FinanCorp - Financial Management System (Streamlit)."""
from datetime import date
import os

import pandas as pd
import plotly.express as px
import streamlit as st

import core

# Streamlit Community Cloud supplies secrets through st.secrets, not environment variables.
deployment_mode = "local"
try:
    deployment_mode = st.secrets.get("DEPLOYMENT_MODE", "local")
    database_url = st.secrets.get("DATABASE_URL", "")
    if database_url:
        os.environ["DATABASE_URL"] = database_url
        core.DATABASE_URL = database_url
except Exception:
    pass

st.set_page_config(page_title="FinanCorp", page_icon="💼", layout="wide")
if deployment_mode == "cloud" and not core.DATABASE_URL:
    st.error("Configure DATABASE_URL nos Secrets da hospedagem antes de iniciar o app.")
    st.stop()
core.init()

VERDE, VERMELHO, AZUL = "#2ecc71", "#e74c3c", "#3498db"


def brl(v):
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt(df):
    d = df.copy()
    for col in ("due_date", "paid_date"):
        d[col] = d[col].dt.strftime("%d/%m/%Y").fillna("—")
    d["amount"] = d["amount"].map(brl)
    return d.rename(columns={"id": "ID", "description": "Descrição", "type": "Tipo",
                             "amount": "Valor", "due_date": "Vencimento",
                             "paid_date": "Pagamento", "party": "Contraparte",
                             "categoria": "Categoria", "status": "Status"})[
        ["ID", "Descrição", "Tipo", "Categoria", "Valor", "Vencimento", "Pagamento",
         "Contraparte", "Status"]]


# ---------- login ----------
if "user" not in st.session_state:
    st.title("💼 FinanCorp")
    st.caption("Gestão financeira com dados privados por conta")
    entrar, criar = st.tabs(["Entrar", "Criar meu espaço"])
    with entrar, st.form("login"):
        u = st.text_input("Login")
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            user = core.login(u, p)
            if user:
                st.session_state.user = user
                st.rerun()
            st.error("Login ou senha inválidos.")
    with criar, st.form("register", clear_on_submit=True):
        st.write("Sua conta começa com um espaço financeiro privado.")
        workspace = st.text_input("Nome do espaço")
        name = st.text_input("Seu nome")
        username = st.text_input("Crie um login")
        password = st.text_input("Crie uma senha (mínimo 10 caracteres)", type="password")
        if st.form_submit_button("Criar conta"):
            try:
                user = core.register_workspace(username, name, workspace, password)
                st.session_state.user = user
                st.rerun()
            except Exception as exc:
                message = str(exc)
                if "unique" in message.lower() or "duplicate" in message.lower():
                    message = "Esse login já está em uso. Escolha outro."
                st.error(message or "Não foi possível criar a conta.")
    st.stop()

user = st.session_state.user
role = user["role"]
workspace_id = user["workspace_id"]
df = core.transactions(workspace_id)

paginas = ["Dashboard", "Transações", "Contas a pagar/receber", "Fluxo de caixa", "Categorias"]
if core.can(role, "relatorios"):
    paginas.append("Relatórios")

with st.sidebar:
    st.title("💼 FinanCorp")
    st.write(f"**{user['name']}**  \nPerfil: `{role}`")
    page = st.radio("Menu", paginas, label_visibility="collapsed")
    if st.button("Sair"):
        del st.session_state.user
        st.rerun()

hoje = pd.Timestamp(date.today())
pagos = df[df.status == "Pago"].copy()
pagos["mes"] = pagos.paid_date.dt.to_period("M").dt.to_timestamp()

# ---------- Dashboard ----------
if page == "Dashboard":
    st.header("Visão geral")
    mes_atual = hoje.to_period("M").to_timestamp()
    m = pagos[pagos.mes == mes_atual]
    rec, desp = m[m.type == "receita"].amount.sum(), m[m.type == "despesa"].amount.sum()
    pend = df[df.status != "Pago"]
    c = st.columns(5)
    c[0].metric("Receitas (mês)", brl(rec))
    c[1].metric("Despesas (mês)", brl(desp))
    c[2].metric("Resultado (mês)", brl(rec - desp))
    c[3].metric("A receber", brl(pend[pend.type == "receita"].amount.sum()))
    c[4].metric("A pagar", brl(pend[pend.type == "despesa"].amount.sum()),
                f"{(pend.status == 'Atrasado').sum()} atrasadas", delta_color="inverse")

    mensal = pagos.pivot_table(index="mes", columns="type", values="amount",
                               aggfunc="sum", fill_value=0).reset_index()
    for tipo in ("receita", "despesa"):
        if tipo not in mensal:
            mensal[tipo] = 0.0
    if mensal.empty:
        st.info("Seu espaço está pronto. Cadastre uma transação para começar a acompanhar os resultados.")
        st.stop()
    a, b = st.columns([3, 2])
    fig = px.bar(mensal, x="mes", y=["receita", "despesa"], barmode="group",
                 color_discrete_map={"receita": VERDE, "despesa": VERMELHO},
                 title="Receitas x Despesas por mês", labels={"value": "R$", "mes": ""})
    a.plotly_chart(fig, use_container_width=True)
    dcat = pagos[pagos.type == "despesa"].groupby("categoria").amount.sum().reset_index()
    b.plotly_chart(px.pie(dcat, names="categoria", values="amount", hole=0.5,
                          title="Despesas por categoria"), use_container_width=True)
    mensal["saldo_acum"] = (mensal.get("receita", 0) - mensal.get("despesa", 0)).cumsum()
    st.plotly_chart(px.area(mensal, x="mes", y="saldo_acum", title="Saldo acumulado",
                            color_discrete_sequence=[AZUL], labels={"saldo_acum": "R$", "mes": ""}),
                    use_container_width=True)

# ---------- Transações ----------
elif page == "Transações":
    st.header("Transações")
    if core.can(role, "editar"):
        with st.expander("➕ Nova transação"):
            with st.form("nova_tx", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                tipo = c1.selectbox("Tipo", ["receita", "despesa"])
                cats = core.categories(tipo, workspace_id)
                if cats.empty:
                    st.warning("Crie uma categoria antes de registrar transações.")
                    st.stop()
                cat = c2.selectbox("Categoria", cats.name)
                valor = c3.number_input("Valor (R$)", min_value=0.01, step=100.0)
                desc = st.text_input("Descrição")
                c4, c5, c6 = st.columns(3)
                venc = c4.date_input("Vencimento", date.today())
                pago = c5.checkbox("Já foi pago/recebido?")
                party = c6.text_input("Cliente / Fornecedor")
                if st.form_submit_button("Salvar") and desc:
                    cid = int(cats[cats.name == cat].id.iloc[0])
                    core.add_transaction(desc, tipo, cid, valor, venc,
                                         venc if pago else None, party, workspace_id)
                    st.success("Transação registrada.")
                    st.rerun()
    f1, f2, f3, f4 = st.columns(4)
    tipos = f1.multiselect("Tipo", ["receita", "despesa"], ["receita", "despesa"])
    sts = f2.multiselect("Status", ["Pago", "Pendente", "Atrasado"], ["Pago", "Pendente", "Atrasado"])
    cts = f3.multiselect("Categoria", sorted(df.categoria.unique()))
    busca = f4.text_input("Buscar descrição")
    v = df[df.type.isin(tipos) & df.status.isin(sts)]
    if cts:
        v = v[v.categoria.isin(cts)]
    if busca:
        v = v[v.description.str.contains(busca, case=False)]
    st.caption(f"{len(v)} transações · total {brl(v.amount.sum())}")
    st.dataframe(fmt(v.sort_values("due_date", ascending=False)), hide_index=True,
                 use_container_width=True)
    if core.can(role, "editar"):
        with st.expander("🗑️ Excluir transação"):
            tid = st.number_input("ID", min_value=1, step=1)
            if st.button("Excluir"):
                core.delete_transaction(int(tid), workspace_id)
                st.rerun()

# ---------- Contas a pagar/receber ----------
elif page == "Contas a pagar/receber":
    st.header("Contas a pagar e a receber")
    pend = df[df.status != "Pago"].sort_values("due_date")
    tabs = st.tabs(["📤 A pagar", "📥 A receber"])
    for tab, tipo in zip(tabs, ["despesa", "receita"]):
        with tab:
            t = pend[pend.type == tipo]
            c1, c2 = st.columns(2)
            c1.metric("Total em aberto", brl(t.amount.sum()))
            c2.metric("Em atraso", brl(t[t.status == "Atrasado"].amount.sum()))
            st.dataframe(fmt(t), hide_index=True, use_container_width=True)
            if core.can(role, "editar") and not t.empty:
                sel = st.selectbox("Baixar conta", t.id, key=tipo,
                                   format_func=lambda i: f"#{i} - {t[t.id == i].description.iloc[0]}"
                                   f" ({brl(t[t.id == i].amount.iloc[0])})")
                if st.button("Marcar como pago/recebido", key="b" + tipo):
                    core.mark_paid(int(sel), workspace_id)
                    st.rerun()

# ---------- Fluxo de caixa ----------
elif page == "Fluxo de caixa":
    st.header("Fluxo de caixa")
    d = df.copy()
    if d.empty:
        st.info("Cadastre transações para visualizar o fluxo de caixa.")
        st.stop()
    d["data"] = d.paid_date.fillna(d.due_date)
    d["mes"] = d.data.dt.to_period("M").dt.to_timestamp()
    d["valor"] = d.amount.where(d.type == "receita", -d.amount)
    d["realizado"] = d.status == "Pago"
    fluxo = d.groupby("mes").apply(lambda g: pd.Series({
        "Entradas": g[g.valor > 0].valor.sum(), "Saídas": -g[g.valor < 0].valor.sum(),
        "Saldo": g.valor.sum(), "Previsto (em aberto)": g[~g.realizado].valor.sum()})).reset_index()
    fluxo["Saldo acumulado"] = fluxo.Saldo.cumsum()
    st.plotly_chart(px.line(fluxo, x="mes", y=["Saldo", "Saldo acumulado"], markers=True,
                            labels={"value": "R$", "mes": ""},
                            title="Saldo mensal e acumulado (realizado + previsto)"),
                    use_container_width=True)
    show = fluxo.copy()
    show["mes"] = show.mes.dt.strftime("%m/%Y")
    for col in show.columns[1:]:
        show[col] = show[col].map(brl)
    st.dataframe(show.rename(columns={"mes": "Mês"}), hide_index=True, use_container_width=True)

# ---------- Categorias ----------
elif page == "Categorias":
    st.header("Categorias")
    cats = core.categories(workspace_id=workspace_id)
    resumo = df.groupby("categoria").amount.sum().rename("Total movimentado")
    st.dataframe(cats.merge(resumo, left_on="name", right_index=True, how="left")
                 .rename(columns={"name": "Categoria", "type": "Tipo"})
                 .assign(**{"Total movimentado": lambda x: x["Total movimentado"].fillna(0).map(brl)})
                 .drop(columns="id"), hide_index=True, use_container_width=True)
    if core.can(role, "editar"):
        with st.form("cat", clear_on_submit=True):
            n = st.text_input("Nova categoria")
            t = st.selectbox("Tipo", ["receita", "despesa"])
            if st.form_submit_button("Criar") and n:
                try:
                    core.add_category(n, t, workspace_id)
                    st.rerun()
                except Exception:
                    st.error("Essa categoria já existe.")

# ---------- Relatórios ----------
elif page == "Relatórios":
    st.header("Relatórios")
    if pagos.empty:
        st.info("Os relatórios aparecerão quando houver transações pagas ou recebidas.")
        st.stop()
    ano = st.selectbox("Ano", sorted(pagos.paid_date.dt.year.unique(), reverse=True))
    p = pagos[pagos.paid_date.dt.year == ano]
    dre = p.pivot_table(index=["type", "categoria"], columns=p.paid_date.dt.month,
                        values="amount", aggfunc="sum", fill_value=0)
    dre["Total"] = dre.sum(axis=1)
    st.subheader("Demonstrativo por categoria (regime de caixa)")
    st.dataframe(dre.style.format(brl), use_container_width=True)
    receita, despesa = p[p.type == "receita"].amount.sum(), p[p.type == "despesa"].amount.sum()
    c = st.columns(3)
    c[0].metric("Receita no ano", brl(receita))
    c[1].metric("Despesa no ano", brl(despesa))
    c[2].metric("Margem", f"{(receita - despesa) / receita * 100:.1f}%" if receita else "—")
    st.download_button("⬇️ Baixar DRE (CSV)", dre.to_csv().encode("utf-8-sig"), f"dre_{ano}.csv")
    st.download_button("⬇️ Baixar todas as transações (CSV)",
                       fmt(df).to_csv(index=False).encode("utf-8-sig"), "transacoes.csv")
