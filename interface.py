import streamlit as st
import uuid
import requests
import base64
import xml.etree.ElementTree as ET
import pdfplumber
import re
from io import BytesIO
from datetime import date

# ============================
# CONFIGURAÇÕES DO SISTEMA
# ============================

WAREHOUSE_MAP = {
    "RIO I": "BLUELOGISTICA_PRD_BLUELOGISTICA_PRD_SCE_PRD_0_wmwhse1",
    "RIO II": "BLUELOGISTICA_PRD_BLUELOGISTICA_PRD_SCE_PRD_0_wmwhse2",
    "RIO IV": "BLUELOGISTICA_PRD_BLUELOGISTICA_PRD_SCE_PRD_0_wmwhse5"
}

WAREHOUSE_CUSTOMERS = "BLUELOGISTICA_PRD_ENTERPRISE"

BASE_URL = "https://mingle-ionapi.inforcloudsuite.com/BLUELOGISTICA_PRD/WM/wmwebservice_rest"

CNPJ_MAP = {
    "04214716000142": "c-trade comerci"
}

CLIENT_ID = st.secrets["CLIENT_ID"]
CLIENT_SECRET = st.secrets["CLIENT_SECRET"]
USERNAME = st.secrets["USERNAME"]
PASSWORD = st.secrets["PASSWORD"]

TOKEN_URL = "https://mingle-sso.inforcloudsuite.com:443/BLUELOGISTICA_PRD/as/token.oauth2"


# ============================
# FUNÇÕES DO BACKEND
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


def xml_para_infor_customer(xml_bytes: bytes):
    """Extrai dados do destinatário (dest) para o endpoint /customers."""
    ns = {"n": "http://www.portalfiscal.inf.br/nfe"}
    root = ET.fromstring(xml_bytes)

    dest = root.find(".//n:dest", ns)

    cnpj_el = dest.find("n:CNPJ", ns) if dest is not None else None
    cpf_el = dest.find("n:CPF", ns) if dest is not None else None
    storerkey = (cnpj_el.text if cnpj_el is not None else None) or (cpf_el.text if cpf_el is not None else None)

    xNome_el = dest.find("n:xNome", ns) if dest is not None else None
    company = xNome_el.text if xNome_el is not None else None

    ender = dest.find("n:enderDest", ns) if dest is not None else None

    xLgr_el = ender.find("n:xLgr", ns) if ender is not None else None
    nro_el = ender.find("n:nro", ns) if ender is not None else None
    logradouro = xLgr_el.text if xLgr_el is not None else ""
    numero = nro_el.text if nro_el is not None else ""
    address1 = f"{logradouro}, {numero}".strip(", ") if logradouro or numero else None

    cep_el = ender.find("n:CEP", ns) if ender is not None else None
    zip_code = cep_el.text if cep_el is not None else None

    xBairro_el = ender.find("n:xBairro", ns) if ender is not None else None
    address2 = xBairro_el.text if xBairro_el is not None else None

    xMun_el = ender.find("n:xMun", ns) if ender is not None else None
    city = xMun_el.text if xMun_el is not None else None

    return {
        "storerkey": storerkey,
        "company": company,
        "address1": address1,
        "zip": zip_code,
        "address2": address2,
        "city": city,
        "type": "2"
    }


def xml_para_infor_shipment(xml_bytes: bytes):
    """Extrai dados do emitente e itens para o endpoint /shipments."""
    ns = {"n": "http://www.portalfiscal.inf.br/nfe"}
    root = ET.fromstring(xml_bytes)

    emit_cnpj_el = root.find(".//n:emit/n:CNPJ", ns)
    emit_cnpj = emit_cnpj_el.text if emit_cnpj_el is not None else None
    storerkey = CNPJ_MAP.get(emit_cnpj, emit_cnpj)

    nNF_el = root.find(".//n:ide/n:nNF", ns)
    orderkey = nNF_el.text if nNF_el is not None else None

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
        "orderdetails": orderdetails
    }


def pdf_para_infor_shipment(pdf_bytes: bytes):
    """Extrai dados do romaneio PDF para o endpoint /shipments."""
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        texto = "\n".join(page.extract_text() or "" for page in pdf.pages)

    # Extrai número do Roteiro
    roteiro_match = re.search(r"Roteiro:\s*(\d+)", texto)
    orderkey = roteiro_match.group(1) if roteiro_match else None

    # Data de hoje como orderdate
    orderdate = date.today().strftime("%Y-%m-%d")

    # Extrai linhas de produtos
    # Formato real: CódFab(6)  CódProd  Descrição...  QtdeUN(ex: 24CX)  EAN
    orderdetails = []
    for linha in texto.splitlines():
        # Linha começa com 6 dígitos (CódFab) seguido de CódProd
        m = re.match(r"^(\d{6})\s+(\d+)\s+.+?\s+(\d+)(CX|PC|UN|KG|FD|BD)\s+\d{8,}", linha)
        if m:
            sku = m.group(2)
            try:
                openqty = float(m.group(3))
            except Exception:
                openqty = 0
            orderdetails.append({"sku": sku, "openqty": openqty})

    return {
        "storerkey": "BLUE FOOD SERVI",
        "orderkey": orderkey,
        "orderdate": orderdate,
        "orderdetails": orderdetails
    }


def processar_pdf(planta: str, pdf_bytes: bytes, nome_arquivo: str):
    """Processa um único PDF de romaneio: POST /shipments (sem /customers)."""
    if planta not in WAREHOUSE_MAP:
        return {"arquivo": nome_arquivo, "erro": f"Planta inválida: {planta}"}

    warehouse_shipment = WAREHOUSE_MAP[planta]
    shipment_json = pdf_para_infor_shipment(pdf_bytes)

    token = gerar_token()
    if not token:
        return {"arquivo": nome_arquivo, "erro": "Falha ao gerar token no Infor"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    endpoint_shipments = f"{BASE_URL}/{warehouse_shipment}/shipments"
    resp_shipments = requests.post(endpoint_shipments, headers=headers, json=shipment_json)

    return {
        "arquivo": nome_arquivo,
        "planta": planta,
        "tipo": "pdf",
        "shipments": {
            "endpoint": endpoint_shipments,
            "payload_enviado": shipment_json,
            "status": resp_shipments.status_code,
            "resposta": resp_shipments.text
        }
    }


def processar_arquivo(planta: str, xml_bytes: bytes, nome_arquivo: str):
    """Processa um único XML: POST /customers → POST /shipments."""
    if planta not in WAREHOUSE_MAP:
        return {"arquivo": nome_arquivo, "erro": f"Planta inválida: {planta}"}

    warehouse_shipment = WAREHOUSE_MAP[planta]

    # Extrai payloads
    customer_json = xml_para_infor_customer(xml_bytes)
    shipment_json = xml_para_infor_shipment(xml_bytes)

    # Gera token uma vez por arquivo
    token = gerar_token()
    if not token:
        return {"arquivo": nome_arquivo, "erro": "Falha ao gerar token no Infor"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # ── 1. POST /customers ──────────────────────────────────────────────
    endpoint_customers = f"{BASE_URL}/{WAREHOUSE_CUSTOMERS}/customers"
    resp_customers = requests.post(endpoint_customers, headers=headers, json=customer_json)

    resultado_customer = {
        "endpoint": endpoint_customers,
        "payload_enviado": customer_json,
        "status": resp_customers.status_code,
        "resposta": resp_customers.text
    }

    # ── 2. POST /shipments ──────────────────────────────────────────────
    shipment_json["consigneekey"] = customer_json["storerkey"]
    endpoint_shipments = f"{BASE_URL}/{warehouse_shipment}/shipments"
    resp_shipments = requests.post(endpoint_shipments, headers=headers, json=shipment_json)

    resultado_shipment = {
        "endpoint": endpoint_shipments,
        "payload_enviado": shipment_json,
        "status": resp_shipments.status_code,
        "resposta": resp_shipments.text
    }

    return {
        "arquivo": nome_arquivo,
        "planta": planta,
        "customers": resultado_customer,
        "shipments": resultado_shipment
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
        /* Mantém o botão de toggle da sidebar visível */
        [data-testid="collapsedControl"] {
            display: flex !important;
            top: 12px;
            left: 12px;
        }
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

        .resultado-arquivo {
            border: 1px solid #1e3a5f;
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 12px;
            background-color: #f0f4f8;
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

plantas = list(WAREHOUSE_MAP.keys())
planta = st.selectbox("Selecione a planta", plantas)

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = str(uuid.uuid4())

arquivos = st.file_uploader(
    "Envie os XMLs da NF-e ou PDFs de romaneio (pode selecionar vários)",
    type=["xml", "pdf"],
    accept_multiple_files=True,
    key=st.session_state.uploader_key
)

# ============================
# BOTÃO DE ENVIO
# ============================

if arquivos and st.button(f"Enviar {len(arquivos)} arquivo(s) para o Infor"):
    resultados = []

    progress = st.progress(0, text="Iniciando envios...")

    for i, arquivo in enumerate(arquivos):
        progress.progress(
            (i) / len(arquivos),
            text=f"Processando {arquivo.name} ({i + 1}/{len(arquivos)})..."
        )

        file_bytes = arquivo.getvalue()
        if arquivo.name.lower().endswith(".pdf"):
            resultado = processar_pdf(planta, file_bytes, arquivo.name)
        else:
            resultado = processar_arquivo(planta, file_bytes, arquivo.name)
        resultados.append(resultado)

    progress.progress(1.0, text="Todos os arquivos processados!")

    st.session_state["resultados"] = resultados

    # Reseta o uploader
    st.session_state.uploader_key = str(uuid.uuid4())

    st.rerun()

# ============================
# EXIBE RESULTADOS APÓS O RERUN
# ============================

if "resultados" in st.session_state:
    resultados = st.session_state["resultados"]

    st.markdown(f"### Resultados — {len(resultados)} arquivo(s) processado(s)")

    for res in resultados:
        if "erro" in res:
            st.error(f"❌ **{res['arquivo']}** — {res['erro']}")
            continue

        is_pdf = res.get("tipo") == "pdf"

        if is_pdf:
            status_ship = res["shipments"]["status"]
            sucesso = status_ship in (200, 201)
        else:
            status_cust = res["customers"]["status"]
            status_ship = res["shipments"]["status"]
            sucesso = status_cust in (200, 201) and status_ship in (200, 201)

        icone = "✅" if sucesso else "⚠️"
        label = "Sucesso" if sucesso else "Atenção — verifique os detalhes"

        with st.expander(f"{icone} {res['arquivo']}  —  {label}", expanded=not sucesso):
            if not is_pdf:
                st.markdown("#### 1. Customers")
                col1, col2 = st.columns([1, 3])
                col1.metric("Status HTTP", res["customers"]["status"])
                col2.markdown(f"**Endpoint:** `{res['customers']['endpoint']}`")
                st.json(res["customers"]["payload_enviado"])
                st.text_area("Resposta Infor (customers)", res["customers"]["resposta"], height=80, key=f"cust_{res['arquivo']}")
                st.markdown("#### 2. Shipments")
            else:
                st.markdown("#### Shipments (Romaneio PDF)")

            col3, col4 = st.columns([1, 3])
            col3.metric("Status HTTP", status_ship)
            col4.markdown(f"**Endpoint:** `{res['shipments']['endpoint']}`")
            st.json(res["shipments"]["payload_enviado"])
            st.text_area("Resposta Infor (shipments)", res["shipments"]["resposta"], height=80, key=f"ship_{res['arquivo']}")


# ============================
# RODAPÉ
# ============================

st.markdown("""
<div class="footer">
    © 2026 • Gateway Infor WMS • Todos os direitos reservados
</div>
""", unsafe_allow_html=True)
