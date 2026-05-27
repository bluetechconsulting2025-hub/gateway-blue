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


def pdf_para_infor_shipment(pdf_bytes: bytes):
    """Extrai dados do romaneio PDF para o endpoint /shipments."""
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        texto = "\n".join(page.extract_text() or "" for page in pdf.pages)

    # Extrai número do Roteiro
    roteiro_match = re.search(r"Roteiro:\s*(\d+)", texto)
    orderkey = roteiro_match.group(1) if roteiro_match else None

    # Data de hoje como orderdate
    orderdate = date.today().strftime("%Y-%m-%d")

    # Mapeamento de UDM
    UOM_MAP = {"CX": "CA", "PC": "PCT", "UN": "UN", "KG": "KG", "FD": "FD", "BD": "BD"}

    # Extrai linhas de produtos
    # Aceita qty colado na unidade (17CX) ou separado por espaço (17 CX), com ou sem EAN no final
    orderdetails = []
    for linha in texto.splitlines():
        m = re.match(r"^(\d+)\s+(\d+)\s+.+?\s+(\d+)\s*(CX|PC|UN|KG|FD|BD)(?:\s+\d{8,})?$", linha)
        if m:
            sku = m.group(2)
            udm_pdf = m.group(4)
            try:
                uomopenqty = float(m.group(3))
            except Exception:
                uomopenqty = 0
            orderdetails.append({
                "sku": sku,
                "uomopenqty": uomopenqty,
                "uom": UOM_MAP.get(udm_pdf, udm_pdf)
            })

    return {
        "storerkey": "BLUE FOOD SERVI",
        "orderkey": orderkey,
        "orderdate": orderdate,
        "orderdetails": orderdetails
    }


STATUS_MAP = {
    "00": "Ordem em branco",
    "02": "Criado extern.",
    "04": "Criado intern.",
    "06": "Não alocou",
    "08": "Convertido",
    "09": "Não inic.",
    "-1": "Desc.",
    "10": "Agrupado",
    "11": "Volume pré-alocado",
    "12": "Pré-alocado",
    "13": "Liberado p/ planej. de armaz.",
    "14": "Volume alocado",
    "15": "Volume aloc./volume sep.",
    "16": "Volume alocado/volume exp.",
    "17": "Alocado",
    "18": "Substituído",
    "-2": "SemSincronismo",
    "22": "Volume liberado",
    "25": "Volume liberado/volume sep.",
    "27": "Volume liberado/volume exp.",
    "29": "Liberado",
    "51": "Em separação",
    "52": "Vol. sep.",
    "53": "Vol. separado/volume exp.",
    "55": "Separação concluída",
    "57": "Separado/volume exp.",
    "61": "Em emb.",
    "68": "Emb. concluída",
    "75": "Preparado",
    "78": "Manifestado",
    "82": "Em carreg.",
    "88": "Carregado",
    "92": "Volume expedido",
    "94": "Fechar produção",
    "95": "Expedição concluída",
    "96": "Entrega aceita",
    "97": "Entrega recusada",
    "98": "Cancelado extern.",
    "99": "Cancelado intern.",
}


def consultar_status_pedido(warehouse: str, orderkey: str, headers: dict):
    """GET /shipments/{orderkey} e retorna resumo de status."""
    endpoint = f"{BASE_URL}/{warehouse}/shipments/{orderkey}"
    resp = requests.get(endpoint, headers=headers)

    if resp.status_code not in (200, 201):
        return {"liberado": False, "erro": f"Não foi possível consultar o pedido (HTTP {resp.status_code})", "linhas_pendentes": []}

    try:
        data = resp.json()
    except Exception:
        return {"liberado": False, "erro": "Resposta inválida do Infor", "linhas_pendentes": []}

    status_header = str(data.get("status", ""))

    if status_header == "29":
        return {"liberado": True, "status_header": status_header, "status_desc": STATUS_MAP.get(status_header, status_header), "linhas_pendentes": []}

    # Coleta linhas que não estão no status 29
    linhas_pendentes = []
    for det in data.get("orderdetails", []):
        st = str(det.get("status", ""))
        if st != "29":
            linhas_pendentes.append({
                "sku": det.get("sku"),
                "status": st,
                "status_desc": STATUS_MAP.get(st, st),
                "uomopenqty": det.get("uomopenqty"),
                "openqty": det.get("openqty"),
                "uom": det.get("uom"),
                "linha": det.get("orderlinenumber"),
            })

    return {
        "liberado": False,
        "status_header": status_header,
        "status_desc": STATUS_MAP.get(status_header, status_header),
        "linhas_pendentes": linhas_pendentes
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

    resultado_shipment_pdf = {
        "endpoint": endpoint_shipments,
        "payload_enviado": shipment_json,
        "status": resp_shipments.status_code,
        "resposta": resp_shipments.text
    }

    # ── POST /release ────────────────────────────────────────────────────
    orderkey_pdf = shipment_json.get("orderkey")
    endpoint_release_pdf = f"{BASE_URL}/{warehouse_shipment}/shipments/{orderkey_pdf}/release"
    resp_release_pdf = requests.post(endpoint_release_pdf, headers=headers)

    resultado_release_pdf = {
        "endpoint": endpoint_release_pdf,
        "status": resp_release_pdf.status_code,
        "resposta": resp_release_pdf.text
    }

    # ── GET /status ──────────────────────────────────────────────────────
    status_pedido_pdf = consultar_status_pedido(warehouse_shipment, orderkey_pdf, headers)

    return {
        "arquivo": nome_arquivo,
        "planta": planta,
        "tipo": "pdf",
        "shipments": resultado_shipment_pdf,
        "release": resultado_release_pdf,
        "status_pedido": status_pedido_pdf
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

    # ── 3. POST /release ────────────────────────────────────────────────
    orderkey = shipment_json.get("orderkey")
    endpoint_release = f"{BASE_URL}/{warehouse_shipment}/shipments/{orderkey}/release"
    resp_release = requests.post(endpoint_release, headers=headers)

    resultado_release = {
        "endpoint": endpoint_release,
        "status": resp_release.status_code,
        "resposta": resp_release.text
    }

    # ── GET /status ──────────────────────────────────────────────────────
    status_pedido = consultar_status_pedido(warehouse_shipment, orderkey, headers)

    return {
        "arquivo": nome_arquivo,
        "planta": planta,
        "customers": resultado_customer,
        "shipments": resultado_shipment,
        "release": resultado_release,
        "status_pedido": status_pedido
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
    st.markdown("Integrações de Pedidos")
    st.markdown("---")
    st.caption("Versão corporativa • Desenvolvido por Blue Tech Consulting")


# ============================
# FORMULÁRIO PRINCIPAL
# ============================

st.title("Integração de XML para pedidos")

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

    progress = st.progress(0, text="Iniciando integrações...")

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
            status_release = res.get("release", {}).get("status", 0)
            sucesso = status_ship in (200, 201) and status_release in (200, 201)
        else:
            status_cust = res["customers"]["status"]
            status_ship = res["shipments"]["status"]
            status_release = res.get("release", {}).get("status", 0)
            sucesso = status_cust in (200, 201) and status_ship in (200, 201) and status_release in (200, 201)

        icone = "✅" if sucesso else "⚠️"
        label = "Sucesso" if sucesso else "Atenção — verifique os detalhes"

        with st.expander(f"{icone} {res['arquivo']}  —  {label}", expanded=not sucesso):

            orderkey_exib = res.get("shipments", {}).get("payload_enviado", {}).get("orderkey", "—")
            st.markdown(f"**Pedido:** `{orderkey_exib}`")
            st.markdown("<hr style='margin:8px 0 16px 0; border-color:#e0e0e0'>", unsafe_allow_html=True)

            passos = []
            if not is_pdf:
                passos.append(("👤", "Cliente Final", res["customers"]["status"]))
            passos.append(("📦", "Pedido", res["shipments"]["status"]))
            if "release" in res:
                passos.append(("🔓", "Pedido Liberado", res["release"]["status"]))

            step_parts = []
            for i, (icon, nome, http_status) in enumerate(passos):
                ok = http_status in (200, 201)
                cor_bg = "#1a7a3c" if ok else "#c0392b"
                status_txt = ("✓ " + str(http_status)) if ok else ("✗ " + str(http_status))
                cor_status = "#1a7a3c" if ok else "#c0392b"
                step_parts.append(
                    f'<div style="display:flex;flex-direction:column;align-items:center;min-width:110px;">'
                    f'<div style="background:{cor_bg};color:#fff;border-radius:50%;width:48px;height:48px;'
                    f'display:flex;align-items:center;justify-content:center;font-size:22px;">{icon}</div>'
                    f'<div style="font-size:13px;font-weight:600;margin-top:6px;text-align:center;color:#1a1a1a;">{nome}</div>'
                    f'<div style="font-size:12px;color:{cor_status};font-weight:500;">{status_txt}</div>'
                    f'</div>'
                )
                if i < len(passos) - 1:
                    step_parts.append('<div style="flex:1;height:2px;background:#cccccc;margin-bottom:24px;min-width:20px;"></div>')

            step_html = '<div style="display:flex;align-items:center;gap:0;margin-bottom:20px;">' + "".join(step_parts) + '</div>'
            st.markdown(step_html, unsafe_allow_html=True)

            if not is_pdf and res["customers"]["status"] not in (200, 201):
                st.error(f"**Cliente Final** — Erro {res['customers']['status']}: {res['customers']['resposta']}")
            if res["shipments"]["status"] not in (200, 201):
                st.error(f"**Pedido** — Erro {res['shipments']['status']}: {res['shipments']['resposta']}")
            if "release" in res and res["release"]["status"] not in (200, 201):
                st.error(f"**Pedido Liberado** — Erro {res['release']['status']}: {res['release']['resposta']}")

            if "status_pedido" in res:
                sp = res["status_pedido"]
                st.markdown("<hr style='margin:8px 0 12px 0; border-color:#e0e0e0'>", unsafe_allow_html=True)
                if "erro" in sp:
                    st.warning(f"⚠️ Não foi possível consultar o status: {sp['erro']}")
                elif sp["liberado"]:
                    st.success("✅ Pedido totalmente liberado no Infor!")
                else:
                    status_label = f"{sp.get('status_header', '?')} — {sp.get('status_desc', '')}"
                    st.warning(f"⚠️ Pedido não está totalmente liberado (status atual: **{status_label}**)")
                    linhas = sp.get("linhas_pendentes", [])
                    if linhas:
                        st.markdown("**Linhas pendentes:**")
                        dados = [{
                            "Linha": l["linha"],
                            "SKU": l["sku"],
                            "Status": f"{l['status']} — {l['status_desc']}",
                            "Qtd Aberta (UOM)": l["uomopenqty"],
                            "Qtd Aberta": l["openqty"],
                            "UOM": l["uom"],
                        } for l in linhas]
                        st.dataframe(dados, use_container_width=True)
                    else:
                        st.info("Nenhuma linha pendente encontrada nos detalhes.")


# ============================
# RODAPÉ
# ============================

st.markdown("""
<div class="footer">
    © 2026 • Gateway Infor WMS • Todos os direitos reservados
</div>
""", unsafe_allow_html=True)
