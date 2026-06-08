import streamlit as st
import uuid
import requests
import base64
import xml.etree.ElementTree as ET
import pdfplumber
import re
from io import BytesIO
from datetime import date

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

def gerar_token():
    auth_string = f"{CLIENT_ID}:{CLIENT_SECRET}"
    auth_base64 = base64.b64encode(auth_string.encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_base64}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {"grant_type": "password", "username": USERNAME, "password": PASSWORD}
    resp = requests.post(TOKEN_URL, data=payload, headers=headers)
    if resp.status_code != 200:
        return None
    return resp.json().get("access_token")

def xml_para_infor_customer(xml_bytes):
    ns = {"n": "http://www.portalfiscal.inf.br/nfe"}
    root = ET.fromstring(xml_bytes)
    dest = root.find(".//n:dest", ns)
    cnpj_el = dest.find("n:CNPJ", ns) if dest is not None else None
    cpf_el  = dest.find("n:CPF",  ns) if dest is not None else None
    storerkey = (cnpj_el.text if cnpj_el is not None else None) or (cpf_el.text if cpf_el is not None else None)
    xNome_el  = dest.find("n:xNome", ns) if dest is not None else None
    company   = xNome_el.text if xNome_el is not None else None
    ender     = dest.find("n:enderDest", ns) if dest is not None else None
    xLgr_el   = ender.find("n:xLgr", ns) if ender is not None else None
    nro_el    = ender.find("n:nro",  ns) if ender is not None else None
    logradouro = xLgr_el.text if xLgr_el is not None else ""
    numero     = nro_el.text  if nro_el  is not None else ""
    address1   = f"{logradouro}, {numero}".strip(", ") if logradouro or numero else None
    cep_el     = ender.find("n:CEP",    ns) if ender is not None else None
    zip_code   = cep_el.text if cep_el is not None else None
    xBairro_el = ender.find("n:xBairro", ns) if ender is not None else None
    address2   = xBairro_el.text if xBairro_el is not None else None
    xMun_el    = ender.find("n:xMun", ns) if ender is not None else None
    city       = xMun_el.text if xMun_el is not None else None
    return {
        "storerkey": storerkey[:30] if storerkey else storerkey,
        "company":   company[:30]   if company   else company,
        "address1":  address1[:35]  if address1  else address1,
        "zip":       zip_code[:10]  if zip_code  else zip_code,
        "address2":  address2[:35]  if address2  else address2,
        "city":      city[:30]      if city      else city,
        "type": "2"
    }

def xml_para_infor_shipment(xml_bytes):
    ns = {"n": "http://www.portalfiscal.inf.br/nfe"}
    root = ET.fromstring(xml_bytes)
    emit_cnpj_el = root.find(".//n:emit/n:CNPJ", ns)
    emit_cnpj    = emit_cnpj_el.text if emit_cnpj_el is not None else None
    storerkey    = CNPJ_MAP.get(emit_cnpj, emit_cnpj)
    nNF_el   = root.find(".//n:ide/n:nNF", ns)
    orderkey = nNF_el.text if nNF_el is not None else None
    orderdetails = []
    for det in root.findall(".//n:det", ns):
        cProd_el = det.find("n:prod/n:cProd", ns)
        qCom_el  = det.find("n:prod/n:qCom",  ns)
        if cProd_el is None or qCom_el is None:
            continue
        try:
            openqty = float(qCom_el.text)
        except Exception:
            openqty = 0
        orderdetails.append({"sku": cProd_el.text, "openqty": openqty})
    return {"storerkey": storerkey, "orderkey": orderkey, "orderdetails": orderdetails}

# FIX: removido "type": "3" — campo invalido para /carriers, causava
# rejeicao silenciosa pelo Infor e shipment era criado sem transportadora
def xml_extrair_carrier(xml_bytes):
    ns = {"n": "http://www.portalfiscal.inf.br/nfe"}
    root = ET.fromstring(xml_bytes)
    transp = root.find(".//n:transporta", ns)
    if transp is None:
        return None
    cnpj_el = transp.find("n:CNPJ",  ns)
    nome_el = transp.find("n:xNome", ns)
    end_el  = transp.find("n:xEnder", ns)
    mun_el  = transp.find("n:xMun",  ns)
    cnpj = cnpj_el.text if cnpj_el is not None else None
    if not cnpj:
        return None
    return {
        "storerkey": cnpj,
        "company":   nome_el.text if nome_el is not None else None,
        "address1":  end_el.text  if end_el  is not None else None,
        "city":      mun_el.text  if mun_el  is not None else None,
        # "type": "3" REMOVIDO - invalido para /carriers
    }

def xml_extrair_emit_cnpj(xml_bytes):
    ns = {"n": "http://www.portalfiscal.inf.br/nfe"}
    root = ET.fromstring(xml_bytes)
    el = root.find(".//n:emit/n:CNPJ", ns)
    return el.text if el is not None else ""

def xml_extrair_carrier_cnpj(xml_bytes):
    ns = {"n": "http://www.portalfiscal.inf.br/nfe"}
    root = ET.fromstring(xml_bytes)
    el = root.find(".//n:transporta/n:CNPJ", ns)
    return el.text if el is not None else "SEM_TRANSPORTADORA"

def xml_extrair_emit_nome(xml_bytes):
    ns = {"n": "http://www.portalfiscal.inf.br/nfe"}
    root = ET.fromstring(xml_bytes)
    el = root.find(".//n:emit/n:xNome", ns)
    return el.text if el is not None else ""

def postar_load(warehouse, carrier_cnpj, proprietario, pedidos, headers):
    hoje = date.today().strftime("%Y%m%d")
    carrier_limpo = re.sub(r"[^0-9A-Za-z]", "", carrier_cnpj or "LOAD")
    externalid = f"{carrier_limpo[:12]}{hoje}"[:20]
    route = (proprietario or "LOAD")[:10]
    load_order_details = [{"shipmentorderid": p["orderkey"], "storer": p["storerkey"]} for p in pedidos]
    payload = {"externalid": externalid, "stops": [{"stop": 1, "loadorderdetails": load_order_details}], "route": route}
    endpoint = f"{BASE_URL}/{warehouse}/loads"
    resp = requests.post(endpoint, headers=headers, json=payload)
    return {"endpoint": endpoint, "payload_enviado": payload, "status": resp.status_code, "resposta": resp.text}

def processar_grupo_ctrade(planta, xmls, token):
    warehouse_shipment = WAREHOUSE_MAP[planta]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    carrier_json = xml_extrair_carrier(xmls[0][1])
    carrier_cnpj = carrier_json["storerkey"] if carrier_json else "desconhecida"

    # 1. POST /customers
    resultado_customers = []
    for nome, xml_bytes in xmls:
        customer_json = xml_para_infor_customer(xml_bytes)
        endpoint_customers = f"{BASE_URL}/{WAREHOUSE_CUSTOMERS}/customers"
        resp_cust = requests.post(endpoint_customers, headers=headers, json=customer_json)
        resultado_customers.append({
            "nf": nome, "endpoint": endpoint_customers,
            "payload_enviado": customer_json,
            "status": resp_cust.status_code, "resposta": resp_cust.text
        })

    # 2. POST /carriers
    # FIX: verifica sucesso antes de usar carriercode no shipment
    # 409 = ja existe no Infor, tambem valido para uso
    resultado_carrier = {"status": None, "resposta": None, "endpoint": None}
    carrier_cadastrado = False
    if carrier_json:
        endpoint_carriers = f"{BASE_URL}/{warehouse_shipment}/carriers"
        resp_carrier = requests.post(endpoint_carriers, headers=headers, json=carrier_json)
        resultado_carrier = {
            "endpoint": endpoint_carriers, "payload_enviado": carrier_json,
            "status": resp_carrier.status_code, "resposta": resp_carrier.text
        }
        carrier_cadastrado = resp_carrier.status_code in (200, 201, 409)

    # Monta orderdetails
    storerkey = CNPJ_MAP.get("04214716000142", "04214716000142")
    sku_totais = {}
    nfs_incluidas = []
    for nome, xml_bytes in xmls:
        shipment = xml_para_infor_shipment(xml_bytes)
        for det in shipment.get("orderdetails", []):
            sku = det["sku"]
            sku_totais[sku] = sku_totais.get(sku, 0) + det["openqty"]
        nfs_incluidas.append(shipment.get("orderkey", nome))

    todos_details = [{"sku": sku, "openqty": qty} for sku, qty in sku_totais.items()]

    # FIX: carriercode so incluido se carrier foi cadastrado com sucesso
    shipment_json = {
        "storerkey":    storerkey,
        "notes":        ", ".join(str(nf) for nf in nfs_incluidas),
        "orderdetails": todos_details
    }
    if carrier_cadastrado and carrier_cnpj != "desconhecida":
        shipment_json["carriercode"] = carrier_cnpj

    # 3. POST /shipments
    endpoint_shipments = f"{BASE_URL}/{warehouse_shipment}/shipments"
    resp_shipments = requests.post(endpoint_shipments, headers=headers, json=shipment_json)
    resultado_shipment = {
        "endpoint": endpoint_shipments, "payload_enviado": shipment_json,
        "status": resp_shipments.status_code, "resposta": resp_shipments.text
    }

    orderkey_gerado = None
    if resp_shipments.status_code in (200, 201):
        try:
            orderkey_gerado = resp_shipments.json().get("orderkey")
        except Exception:
            pass

    # 4. POST /release
    resultado_release = {"status": None, "resposta": None, "endpoint": None}
    status_pedido = {"erro": "Pedido nao foi criado, release nao executado."}
    if orderkey_gerado:
        endpoint_release = f"{BASE_URL}/{warehouse_shipment}/shipments/{orderkey_gerado}/release"
        resp_release = requests.post(endpoint_release, headers=headers)
        resultado_release = {"endpoint": endpoint_release, "status": resp_release.status_code, "resposta": resp_release.text}
        status_pedido = consultar_status_pedido(warehouse_shipment, orderkey_gerado, headers)

    resultado = {
        "arquivo":            f"C-Trade - Transportadora {carrier_cnpj} ({len(xmls)} NF{'s' if len(xmls) > 1 else ''})",
        "planta":             planta,
        "tipo":               "ctrade",
        "nfs_incluidas":      nfs_incluidas,
        "orderkey_gerado":    orderkey_gerado,
        "storerkey":          storerkey,
        "carrier_cnpj":       carrier_cnpj,
        "carrier_cadastrado": carrier_cadastrado,
        "warehouse":          warehouse_shipment,
        "customers":          resultado_customers,
        "carrier":            resultado_carrier,
        "shipments":          resultado_shipment,
        "release":            resultado_release,
        "status_pedido":      status_pedido
    }

    # DEBUG (remover apos confirmacao do fix)
    st.warning("DEBUG - resultado c-trade (remover apos confirmacao)")
    st.write({
        "carrier_cnpj":        carrier_cnpj,
        "carrier_cadastrado":  carrier_cadastrado,
        "carrier_status_http": resultado_carrier["status"],
        "carrier_resposta":    resultado_carrier["resposta"],
        "storerkey":           storerkey,
        "carrier_json":        carrier_json,
        "shipment_payload":    shipment_json,
        "shipments_status":    resultado_shipment["status"],
        "shipments_resposta":  resultado_shipment["resposta"],
    })

    return resultado

def pdf_para_infor_shipment(pdf_bytes):
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        texto = "\n".join(page.extract_text() or "" for page in pdf.pages)
    roteiro_match = re.search(r"Roteiro:\s*(\d+)", texto)
    orderkey = roteiro_match.group(1) if roteiro_match else None
    UOM_MAP = {"CX": "CA", "PC": "PCT", "UN": "UN", "KG": "KG", "FD": "FD", "BD": "BD"}
    orderdetails = []
    for linha in texto.splitlines():
        m = re.match(r"^(\d+)\s+(\d+)\s+.+?\s+(\d+)\s*(CX|PC|UN|KG|FD|BD)(?:\s+\d{8,})?$", linha)
        if m:
            udm_pdf = m.group(4)
            try:
                uomopenqty = float(m.group(3))
            except Exception:
                uomopenqty = 0
            orderdetails.append({"sku": m.group(2), "uomopenqty": uomopenqty, "uom": UOM_MAP.get(udm_pdf, udm_pdf)})
    return {"storerkey": "BLUE FOOD SERVI", "orderkey": orderkey, "orderdetails": orderdetails}

STATUS_MAP = {
    "00": "Ordem em branco", "02": "Criado extern.", "04": "Criado intern.",
    "06": "Nao alocou", "08": "Convertido", "09": "Nao inic.", "-1": "Desc.",
    "10": "Agrupado", "11": "Volume pre-alocado", "12": "Pre-alocado",
    "13": "Liberado p/ planej. de armaz.", "14": "Volume alocado",
    "15": "Volume aloc./volume sep.", "16": "Volume alocado/volume exp.",
    "17": "Alocado", "18": "Substituido", "-2": "SemSincronismo",
    "22": "Volume liberado", "25": "Volume liberado/volume sep.",
    "27": "Volume liberado/volume exp.", "29": "Liberado", "51": "Em separacao",
    "52": "Vol. sep.", "53": "Vol. separado/volume exp.", "55": "Separacao concluida",
    "57": "Separado/volume exp.", "61": "Em emb.", "68": "Emb. concluida",
    "75": "Preparado", "78": "Manifestado", "82": "Em carreg.", "88": "Carregado",
    "92": "Volume expedido", "94": "Fechar producao", "95": "Expedicao concluida",
    "96": "Entrega aceita", "97": "Entrega recusada", "98": "Cancelado extern.",
    "99": "Cancelado intern.",
}

def consultar_status_pedido(warehouse, orderkey, headers):
    endpoint = f"{BASE_URL}/{warehouse}/shipments/{orderkey}"
    resp = requests.get(endpoint, headers=headers)
    if resp.status_code not in (200, 201):
        return {"liberado": False, "erro": f"Nao foi possivel consultar o pedido (HTTP {resp.status_code})", "linhas_pendentes": []}
    try:
        data = resp.json()
    except Exception:
        return {"liberado": False, "erro": "Resposta invalida do Infor", "linhas_pendentes": []}
    status_header = str(data.get("status", ""))
    if status_header == "29":
        return {"liberado": True, "status_header": status_header, "status_desc": STATUS_MAP.get(status_header, status_header), "linhas_pendentes": []}
    linhas_pendentes = []
    for det in data.get("orderdetails", []):
        st_code = str(det.get("status", ""))
        if st_code != "29":
            linhas_pendentes.append({
                "sku": det.get("sku"), "status": st_code,
                "status_desc": STATUS_MAP.get(st_code, st_code),
                "uomopenqty": det.get("uomopenqty"), "openqty": det.get("openqty"),
                "uom": det.get("uom"), "linha": det.get("orderlinenumber"),
            })
    return {"liberado": False, "status_header": status_header, "status_desc": STATUS_MAP.get(status_header, status_header), "linhas_pendentes": linhas_pendentes}

def processar_pdf(planta, pdf_bytes, nome_arquivo):
    if planta not in WAREHOUSE_MAP:
        return {"arquivo": nome_arquivo, "erro": f"Planta invalida: {planta}"}
    warehouse_shipment = WAREHOUSE_MAP[planta]
    shipment_json = pdf_para_infor_shipment(pdf_bytes)
    token = gerar_token()
    if not token:
        return {"arquivo": nome_arquivo, "erro": "Falha ao gerar token no Infor"}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    endpoint_shipments = f"{BASE_URL}/{warehouse_shipment}/shipments"
    resp_shipments = requests.post(endpoint_shipments, headers=headers, json=shipment_json)
    resultado_shipment_pdf = {"endpoint": endpoint_shipments, "payload_enviado": shipment_json, "status": resp_shipments.status_code, "resposta": resp_shipments.text}
    orderkey_pdf = shipment_json.get("orderkey")
    endpoint_release_pdf = f"{BASE_URL}/{warehouse_shipment}/shipments/{orderkey_pdf}/release"
    resp_release_pdf = requests.post(endpoint_release_pdf, headers=headers)
    resultado_release_pdf = {"endpoint": endpoint_release_pdf, "status": resp_release_pdf.status_code, "resposta": resp_release_pdf.text}
    status_pedido_pdf = consultar_status_pedido(warehouse_shipment, orderkey_pdf, headers)
    return {"arquivo": nome_arquivo, "planta": planta, "tipo": "pdf", "storerkey": "BLUE FOOD SERVI", "orderkey": orderkey_pdf, "warehouse": warehouse_shipment, "shipments": resultado_shipment_pdf, "release": resultado_release_pdf, "status_pedido": status_pedido_pdf}

def processar_arquivo(planta, xml_bytes, nome_arquivo):
    if planta not in WAREHOUSE_MAP:
        return {"arquivo": nome_arquivo, "erro": f"Planta invalida: {planta}"}
    warehouse_shipment = WAREHOUSE_MAP[planta]
    customer_json = xml_para_infor_customer(xml_bytes)
    shipment_json = xml_para_infor_shipment(xml_bytes)
    token = gerar_token()
    if not token:
        return {"arquivo": nome_arquivo, "erro": "Falha ao gerar token no Infor"}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    endpoint_customers = f"{BASE_URL}/{WAREHOUSE_CUSTOMERS}/customers"
    resp_customers = requests.post(endpoint_customers, headers=headers, json=customer_json)
    resultado_customer = {"endpoint": endpoint_customers, "payload_enviado": customer_json, "status": resp_customers.status_code, "resposta": resp_customers.text}
    shipment_json["consigneekey"] = customer_json["storerkey"]
    carrier_cnpj = xml_extrair_carrier_cnpj(xml_bytes)
    if carrier_cnpj != "SEM_TRANSPORTADORA":
        shipment_json["carriercode"] = carrier_cnpj
    endpoint_shipments = f"{BASE_URL}/{warehouse_shipment}/shipments"
    resp_shipments = requests.post(endpoint_shipments, headers=headers, json=shipment_json)
    resultado_shipment = {"endpoint": endpoint_shipments, "payload_enviado": shipment_json, "status": resp_shipments.status_code, "resposta": resp_shipments.text}
    orderkey = shipment_json.get("orderkey")
    endpoint_release = f"{BASE_URL}/{warehouse_shipment}/shipments/{orderkey}/release"
    resp_release = requests.post(endpoint_release, headers=headers)
    resultado_release = {"endpoint": endpoint_release, "status": resp_release.status_code, "resposta": resp_release.text}
    status_pedido = consultar_status_pedido(warehouse_shipment, orderkey, headers)
    emit_nome = xml_extrair_emit_nome(xml_bytes)
    return {"arquivo": nome_arquivo, "planta": planta, "tipo": "xml", "storerkey": shipment_json.get("storerkey"), "orderkey": orderkey, "warehouse": warehouse_shipment, "carrier_cnpj": carrier_cnpj, "emit_nome": emit_nome, "customers": resultado_customer, "shipments": resultado_shipment, "release": resultado_release, "status_pedido": status_pedido}

# UI
st.markdown("""
    <script>
        var links = document.querySelectorAll("link[rel='icon']");
        links.forEach(l => l.parentNode.removeChild(l));
        var link = document.createElement('link');
        link.rel = 'icon'; link.href = '/logo.png'; link.type = 'image/png';
        document.getElementsByTagName('head')[0].appendChild(link);
        document.title = "Gateway Blue";
    </script>
""", unsafe_allow_html=True)

st.markdown("""
    <style>
        header[data-testid="stHeader"] { display: none; }
        [data-testid="collapsedControl"] { display: flex !important; top: 12px; left: 12px; }
        div[data-testid="stStatusWidget"] { display: none !important; }
        .custom-header { display: flex; align-items: center; background-color: #0A1A2F; padding: 12px 20px; border-radius: 8px; margin-bottom: 25px; }
        .custom-header-title { color: white; font-size: 28px; font-weight: 700; letter-spacing: 0.5px; }
        [data-testid="stSidebar"] { background-color: #0A1A2F; padding-top: 30px; }
        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { color: #FFFFFF; }
        [data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] div { color: #D9E2EC; }
        .footer { text-align: center; margin-top: 40px; font-size: 13px; color: #6c757d; }
    </style>
    <div class="custom-header"><div class="custom-header-title">Gateway Blue</div></div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.image("logo.png", width=160)
    st.markdown("### **Gateway Infor WMS**")
    st.markdown("---")
    st.markdown("Integracoes de Pedidos")
    st.markdown("---")
    st.caption("Versao corporativa - Desenvolvido por Blue Tech Consulting")

st.title("Integracao de pedidos - XML e Romaneios")
plantas = list(WAREHOUSE_MAP.keys())
planta  = st.selectbox("Selecione a planta", plantas)

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = str(uuid.uuid4())

arquivos = st.file_uploader(
    "Envie os XMLs da NF-e ou PDFs de romaneio (pode selecionar varios)",
    type=["xml", "pdf"], accept_multiple_files=True, key=st.session_state.uploader_key
)

if arquivos and st.button(f"Enviar {len(arquivos)} arquivo(s) para o Infor"):
    resultados  = []
    progress    = st.progress(0, text="Iniciando integracoes...")
    ctrade_grupos = {}

    for i, arquivo in enumerate(arquivos):
        progress.progress(i / len(arquivos), text=f"Processando {arquivo.name} ({i + 1}/{len(arquivos)})...")
        file_bytes = arquivo.getvalue()
        if arquivo.name.lower().endswith(".pdf"):
            resultados.append(processar_pdf(planta, file_bytes, arquivo.name))
        else:
            emit_cnpj = xml_extrair_emit_cnpj(file_bytes)
            if emit_cnpj == "04214716000142":
                carrier_cnpj = xml_extrair_carrier_cnpj(file_bytes)
                if carrier_cnpj == "SEM_TRANSPORTADORA":
                    resultados.append(processar_arquivo(planta, file_bytes, arquivo.name))
                else:
                    ctrade_grupos.setdefault(carrier_cnpj, []).append((arquivo.name, file_bytes))
            else:
                resultados.append(processar_arquivo(planta, file_bytes, arquivo.name))

    if ctrade_grupos:
        token_ctrade = gerar_token()
        for carrier_cnpj, xmls_grupo in ctrade_grupos.items():
            resultados.append(processar_grupo_ctrade(planta, xmls_grupo, token_ctrade))

    progress.progress(1.0, text="Todos os arquivos processados!")

    load_groups = {}
    for res in resultados:
        if "erro" in res:
            continue
        warehouse = res.get("warehouse")
        tipo      = res.get("tipo")
        ship_status = res.get("shipments", {}).get("status") or 0
        if ship_status not in (200, 201):
            continue
        if tipo == "ctrade":
            carrier_cnpj = res.get("carrier_cnpj", "desconhecida")
            orderkey     = res.get("orderkey_gerado")
            storerkey    = res.get("storerkey")
            if orderkey:
                key = (warehouse, carrier_cnpj, "c-trade")
                load_groups.setdefault(key, {"pedidos": [], "proprietario": "c-trade"})
                load_groups[key]["pedidos"].append({"orderkey": orderkey, "storerkey": storerkey})
        elif tipo == "pdf":
            orderkey  = res.get("orderkey")
            storerkey = res.get("storerkey", "BLUE FOOD SERVI")
            if orderkey:
                key = (warehouse, "SEM_CARRIER", "BLUE FOOD SERVI")
                load_groups.setdefault(key, {"pedidos": [], "proprietario": "BLUE FOOD SERVI"})
                load_groups[key]["pedidos"].append({"orderkey": orderkey, "storerkey": storerkey})
        else:
            carrier_cnpj = res.get("carrier_cnpj", "SEM_CARRIER")
            proprietario = res.get("emit_nome", "") or res.get("storerkey", "")
            orderkey     = res.get("orderkey")
            storerkey    = res.get("storerkey")
            if orderkey:
                key = (warehouse, carrier_cnpj, proprietario)
                load_groups.setdefault(key, {"pedidos": [], "proprietario": proprietario})
                load_groups[key]["pedidos"].append({"orderkey": orderkey, "storerkey": storerkey})

    resultados_loads = []
    if load_groups:
        token_load   = gerar_token()
        headers_load = {"Authorization": f"Bearer {token_load}", "Content-Type": "application/json"}
        for (warehouse, carrier_cnpj, proprietario), grupo in load_groups.items():
            res_load = postar_load(warehouse=warehouse, carrier_cnpj=carrier_cnpj, proprietario=proprietario, pedidos=grupo["pedidos"], headers=headers_load)
            res_load["descricao"] = f"Load - {proprietario[:10]} x {carrier_cnpj} ({len(grupo['pedidos'])} pedido{'s' if len(grupo['pedidos']) > 1 else ''})"
            resultados_loads.append(res_load)

    st.session_state["resultados"]       = resultados
    st.session_state["resultados_loads"] = resultados_loads
    st.session_state.uploader_key = str(uuid.uuid4())
    st.rerun()

if "resultados" in st.session_state:
    resultados = st.session_state["resultados"]
    st.markdown(f"### Resultados - {len(resultados)} arquivo(s) processado(s)")

    for res in resultados:
        if "erro" in res:
            st.error(f"X **{res['arquivo']}** - {res['erro']}")
            continue

        is_pdf    = res.get("tipo") == "pdf"
        is_ctrade = res.get("tipo") == "ctrade"
        status_ship    = res["shipments"]["status"] or 0
        status_release = res.get("release", {}).get("status") or 0

        if is_pdf or is_ctrade:
            sucesso = status_ship in (200, 201) and status_release in (200, 201)
        else:
            status_cust = res["customers"]["status"]
            sucesso = status_cust in (200, 201) and status_ship in (200, 201) and status_release in (200, 201)

        icone = "OK" if sucesso else "ATENCAO"
        label = "Sucesso" if sucesso else "Atencao - verifique os detalhes"

        with st.expander(f"{'OK' if sucesso else 'ATENCAO'} {res['arquivo']}  -  {label}", expanded=not sucesso):
            if is_ctrade:
                orderkey_exib = res.get("orderkey_gerado") or "(aguardando criacao)"
                st.markdown(f"**Pedido gerado:** `{orderkey_exib}`")
                nfs = res.get("nfs_incluidas", [])
                if nfs:
                    st.markdown("**NFs incluidas:** " + " - ".join(str(n) for n in nfs))
                if not res.get("carrier_cadastrado") and res.get("carrier_cnpj") != "desconhecida":
                    st.warning(f"Transportadora **{res.get('carrier_cnpj')}** nao cadastrada (HTTP {res.get('carrier', {}).get('status')}). Pedido criado sem transportadora.")
            else:
                orderkey_exib = res.get("shipments", {}).get("payload_enviado", {}).get("orderkey", "-")
                st.markdown(f"**Pedido:** `{orderkey_exib}`")

            st.markdown("<hr style='margin:8px 0 16px 0; border-color:#e0e0e0'>", unsafe_allow_html=True)

            passos = []
            if is_ctrade:
                custs = res.get("customers", [])
                cust_status = 200 if custs and all(c["status"] in (200, 201) for c in custs) else (custs[0]["status"] if custs else 0)
                passos.append(("U", "Clientes Finais", cust_status))
                passos.append(("T", "Transportadora", res["carrier"]["status"] or 0))
            elif not is_pdf:
                passos.append(("U", "Cliente Final", res["customers"]["status"]))
            passos.append(("P", "Pedido", res["shipments"]["status"] or 0))
            if res.get("release", {}).get("status"):
                passos.append(("L", "Pedido Liberado", res["release"]["status"]))

            step_parts = []
            for i, (icon, nome, http_status) in enumerate(passos):
                ok = http_status in (200, 201)
                cor_bg = "#1a7a3c" if ok else "#c0392b"
                status_txt = ("OK " + str(http_status)) if ok else ("ERRO " + str(http_status))
                cor_status = "#1a7a3c" if ok else "#c0392b"
                step_parts.append(
                    f'<div style="display:flex;flex-direction:column;align-items:center;min-width:110px;">'
                    f'<div style="background:{cor_bg};color:#fff;border-radius:50%;width:48px;height:48px;display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;">{icon}</div>'
                    f'<div style="font-size:13px;font-weight:600;margin-top:6px;text-align:center;color:#1a1a1a;">{nome}</div>'
                    f'<div style="font-size:12px;color:{cor_status};font-weight:500;">{status_txt}</div>'
                    f'</div>'
                )
                if i < len(passos) - 1:
                    step_parts.append('<div style="flex:1;height:2px;background:#cccccc;margin-bottom:24px;min-width:20px;"></div>')

            st.markdown('<div style="display:flex;align-items:center;gap:0;margin-bottom:20px;">' + "".join(step_parts) + '</div>', unsafe_allow_html=True)

            if is_ctrade:
                for c in res.get("customers", []):
                    if c["status"] not in (200, 201):
                        st.error(f"**Cliente Final ({c['nf']})** - Erro {c['status']}: {c['resposta']}")
                if res["carrier"].get("status") not in (200, 201, 409, None):
                    st.error(f"**Transportadora** - Erro {res['carrier']['status']}: {res['carrier']['resposta']}")
            elif not is_pdf and not is_ctrade and res["customers"]["status"] not in (200, 201):
                st.error(f"**Cliente Final** - Erro {res['customers']['status']}: {res['customers']['resposta']}")
            if (res["shipments"]["status"] or 0) not in (200, 201):
                st.error(f"**Pedido** - Erro {res['shipments']['status']}: {res['shipments']['resposta']}")
            if res.get("release", {}).get("status") not in (200, 201, None):
                st.error(f"**Pedido Liberado** - Erro {res['release']['status']}: {res['release']['resposta']}")

            if "status_pedido" in res:
                sp = res["status_pedido"]
                st.markdown("<hr style='margin:8px 0 12px 0; border-color:#e0e0e0'>", unsafe_allow_html=True)
                if "erro" in sp:
                    st.warning(f"Nao foi possivel consultar o status: {sp['erro']}")
                elif sp["liberado"]:
                    st.success("Pedido totalmente liberado no Infor!")
                else:
                    status_label = f"{sp.get('status_header', '?')} - {sp.get('status_desc', '')}"
                    st.warning(f"Pedido nao esta totalmente liberado (status atual: **{status_label}**)")
                    linhas = sp.get("linhas_pendentes", [])
                    if linhas:
                        st.markdown("**Linhas pendentes:**")
                        st.dataframe([{"Linha": l["linha"], "SKU": l["sku"], "Status": f"{l['status']} - {l['status_desc']}", "Qtd Aberta (UOM)": l["uomopenqty"], "Qtd Aberta": l["openqty"], "UOM": l["uom"]} for l in linhas], use_container_width=True)
                    else:
                        st.info("Nenhuma linha pendente encontrada nos detalhes.")

    resultados_loads = st.session_state.get("resultados_loads", [])
    if resultados_loads:
        st.markdown("---")
        st.markdown(f"### Romaneios (Loads) - {len(resultados_loads)} gerado(s)")
        for rl in resultados_loads:
            ok = rl["status"] in (200, 201)
            label = "Criado com sucesso" if ok else "Erro ao criar"
            with st.expander(f"{'OK' if ok else 'ERRO'} {rl['descricao']}  -  {label}", expanded=not ok):
                st.markdown(f"**Endpoint:** `{rl['endpoint']}`")
                st.markdown(f"**Status HTTP:** `{rl['status']}`")
                payload = rl.get("payload_enviado", {})
                st.markdown(f"**ExternalID:** `{payload.get('externalid', '-')}`")
                st.markdown(f"**Route:** `{payload.get('route', '-')}`")
                pedidos_no_load = payload.get("stops", [{}])[0].get("loadorderdetails", [])
                if pedidos_no_load:
                    st.markdown("**Pedidos incluidos:**")
                    st.dataframe(pedidos_no_load, use_container_width=True)
                if not ok:
                    st.error(f"Resposta do Infor: {rl['resposta']}")

st.markdown('<div class="footer">2026 - Gateway Infor WMS - Todos os direitos reservados</div>', unsafe_allow_html=True)
