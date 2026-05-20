import streamlit as st
import requests
import uuid

# ============================
# FAVICON + TÍTULO DA ABA
# ============================
st.markdown("""
    <script>
        var links = document.querySelectorAll("link[rel='icon']");
        links.forEach(l => l.parentNode.removeChild(l));

        var link = document.createElement('link');
        link.rel = 'icon';
        link.href = '/logo.png';
        link.type = 'image/png';
        document.getElementsByTagName('head')[0].appendChild(link);

        document.title = "Gateway Blue";
    </script>
""", unsafe_allow_html=True)

# ============================
# ESTILO PREMIUM + HEADER
# ============================
st.markdown("""
    <style>
        header[data-testid="stHeader"] { display: none; }
        div[data-testid="stStatusWidget"] { display: none !important; }

        .custom-header {
            display: flex;
            align-items: center;
            background-color: #0A1A2F;
            padding: 12px 20px;
            border-radius: 8px;
            margin-bottom: 25px;
        }

        .custom-header-title {
            color: white;
            font-size: 28px;
            font-weight: 700;
            letter-spacing: 0.5px;
        }

        [data-testid="stSidebar"] {
            background-color: #0A1A2F;
            padding-top: 30px;
        }

        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: #FFFFFF;
        }

        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] div {
            color: #D9E2EC;
        }

        .footer {
            text-align: center;
            margin-top: 40px;
            font-size: 13px;
            color: #6c757d;
        }
    </style>

    <div class="custom-header">
        <div class="custom-header-title">Gateway Blue</div>
    </div>
""", unsafe_allow_html=True)

# ============================
# SIDEBAR
# ============================
with st.sidebar:
    st.image("logo.png", width=160)
    st.markdown("### **Gateway Infor WMS**")
    st.markdown("---")
    st.markdown("Envio de Shipments")
    st.markdown("---")
    st.caption("Versão corporativa • Desenvolvido por André")

# ============================
# FORMULÁRIO PRINCIPAL
# ============================
st.title("Envio de XML para Shipments")

plantas = ["RIO I", "RIO II"]
planta = st.selectbox("Selecione a planta", plantas)

# Criamos uma key dinâmica para o uploader
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = str(uuid.uuid4())

arquivo = st.file_uploader(
    "Envie o XML da NF-e",
    type=["xml"],
    key=st.session_state.uploader_key
)

if arquivo and st.button("Enviar para o Infor"):
    with st.spinner("Processando e enviando para o Infor..."):
        resposta = requests.post(
            "http://localhost:8000/processar",
            data={"planta": planta},
            files={"arquivo": (arquivo.name, arquivo.getvalue())}
        )

    if resposta.status_code == 200:
        st.success("✅ Pedido criado com sucesso!")

        # 🔥 Reset do uploader: gera nova key
        st.session_state.uploader_key = str(uuid.uuid4())

        # Força rerender
        st.rerun()

    else:
        st.error(f"❌ Erro ao criar pedido: {resposta.text}")

# ============================
# RODAPÉ
# ============================
st.markdown("""
<div class="footer">
    © 2026 • Gateway Infor WMS • Todos os direitos reservados
</div>
""", unsafe_allow_html=True)
