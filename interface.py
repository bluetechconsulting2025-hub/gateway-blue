import streamlit as st
import uuid
import requests
import base64
import xml.etree.ElementTree as ET

# ============================
# CONFIGURAÇÕES DO SISTEMA
# ============================

WAREHOUSE_MAP = {
    "RIO I": "BLUELOGISTICA_TST_BLUELOGISTICA_TST_SCE_PRD_0_wmwhse2",
    "RIO II": "BLUELOGISTICA_TST_BLUELOGISTICA_TST_SCE_PRD_0_wmwhse5"
}

BASE_URL = "https://mingle-ionapi.inforcloudsuite.com/BLUELOGISTICA_TST/WM/wmwebservice_rest"

CNPJ_MAP = {
    "04214716000142": "c-trade comerci"
}

CLIENT_ID = "BLUELOGISTICA_TST~q4d1G48GB59HGXnnRq7ofZAzXd0bCp_shy6PmqL-etQ"
CLIENT_SECRET = "xHbeIkCgGM50sJyRNAFDlhYmiPpXC7r44Im5aeJi8nl6jvk5uoK72cs9Mw_0mMhj0szAXnUe9iUDES0pNM6mIQ"
USERNAME = "BLUELOGISTICA_TST#YIRLobVp6gOGHtmIyp4ATHVfKWFhkywl8rWuuLGXMpwusD7dCZrObsxB1xlK5C69K6fZA4aZ9qBvnjfsy1YyaA"
PASSWORD = "xja7dTAKaSAQsDKYvvQ23NpMLuAewFzk7z1fO3B4cfO7WoK9WnucjG71QGsMlwO5W9438bCxS66xX5UdJjXAoA"

TOKEN_URL = "https://mingle-sso.inforcloudsuite.com:443/BLUELOGISTICA_TST/as/token.oauth2"


# ============================
# FUNÇÕES DO BACKEND (AGORA INTERNAS)
# ============================

def gerar_token():
    auth_string = f"{CLIENT_ID}:{CLIENT_SECRET}"
    auth_base64 = base64.b64encode(auth_string.encode()).decode()

    headers = {
        "Authorization": f"Basic {auth_base64}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    payload = {
        "grant_type": "password",
        "username": USERNAME,
        "password": PASSWORD
    }

    resp = requests.post(TOKEN_URL, data=payload, headers=headers)

    if resp.status_code != 200:
        return None

    return resp.json().get("access_token")


def xml_para_infor_shipment(xml_bytes: bytes):
    ns = {"n": "http://www.portalfiscal.inf.br/nfe"}
    root = ET.fromstring(xml_bytes)

    emit_cnpj_el = root.find(".//n:emit/n:CNPJ", ns)
    emit_cnpj = emit_cnpj_el.text if emit_cnpj_el is not None else None
    storerkey = CNPJ_MAP.get(emit_cnpj, emit_cnpj)

    nNF_el = root.find(".//n:ide/n:nNF", ns)
    orderkey = nNF_el.text if nNF_el is not None else None

    dhEmi_el = root.find(".//n:ide/n:dhEmi", ns)
    orderdate = None
    if dhEmi_el is not None and "T" in dhEmi_el.text:
        orderdate = dhEmi_el.text.split("T")[0]

    orderdetails = []
    for det in root.findall(".//n:det", ns):
        cProd_el = det.find("n:prod/n:cProd", ns)
        qCom_el = det.find("n:prod/n:qCom", ns)

        if cProd_el is None or qCom_el is None:
            continue

        sku = cProd_el.text
        try:
            openqty = float(qCom_el.text)
        except Exception:
            openqty = 0

        orderdetails.append({
            "sku": sku,
            "openqty": openqty
        })

    return {
        "storerkey": storerkey,
        "orderkey": orderkey,
        "orderdate": orderdate,
        "orderdetails": orderdetails
    }


def processar_arquivo(planta: str, xml_bytes: bytes):
    if planta not in WAREHOUSE_MAP:
        return {"erro": f"Planta inválida: {planta}"}

    warehouse_real = WAREHOUSE_MAP[planta]

    shipment_json = xml_para_infor_shipment(xml_bytes)

    token = gerar_token()
    if not token:
        return {"erro": "Falha ao gerar token no Infor"}

    endpoint_final = f"{BASE_URL}/{warehouse_real}/shipments"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    resp = requests.post(endpoint_final, headers=headers, json=shipment_json)

    return {
        "planta_selecionada": planta,
        "warehouse_enviado": warehouse_real,
        "endpoint_usado": endpoint_final,
        "payload_enviado": shipment_json,
        "status_infor": resp.status_code,
        "resposta_infor": resp.text
    }


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

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = str(uuid.uuid4())

arquivo = st.file_uploader(
    "Envie o XML da NF-e",
    type=["xml"],
    key=st.session_state.uploader_key
)

if arquivo and st.button("Enviar para o Infor"):
    with st.spinner("Processando e enviando para o Infor..."):
        xml_bytes = arquivo.getvalue()
        resposta = processar_arquivo(planta, xml_bytes)

    if "erro" in resposta:
        st.error("❌ " + resposta["erro"])
    else:
        st.success("✅ Pedido criado com sucesso!")
        st.json(resposta)

        st.session_state.uploader_key = str(uuid.uuid4())
        st.rerun()


# ============================
# RODAPÉ
# ============================

st.markdown("""
<div class="footer">
    © 2026 • Gateway Infor WMS • Todos os direitos reservados
</div>
""", unsafe_allow_html=True)
