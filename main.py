from fastapi import FastAPI, UploadFile, File, Form
import requests
import base64
import xml.etree.ElementTree as ET

app = FastAPI()

# ---------- CONFIGURAÇÕES BÁSICAS ----------

# Plantas -> warehouses reais
WAREHOUSE_MAP = {
    "RIO I": "BLUELOGISTICA_TST_BLUELOGISTICA_TST_SCE_PRD_0_wmwhse2",
    "RIO II": "BLUELOGISTICA_TST_BLUELOGISTICA_TST_SCE_PRD_0_wmwhse5"
}

# Base do endpoint do WMS
BASE_URL = "https://mingle-ionapi.inforcloudsuite.com/BLUELOGISTICA_TST/WM/wmwebservice_rest"

# De-para de CNPJ do emitente -> storerkey
CNPJ_MAP = {
    "04214716000142": "c-trade comerci"
}

# ---------- CONFIGURAÇÕES DO TOKEN (EXEMPLOS / MOCK) ----------

CLIENT_ID = "BLUELOGISTICA_TST~q4d1G48GB59HGXnnRq7ofZAzXd0bCp_shy6PmqL-etQ"
CLIENT_SECRET = "xHbeIkCgGM50sJyRNAFDlhYmiPpXC7r44Im5aeJi8nl6jvk5uoK72cs9Mw_0mMhj0szAXnUe9iUDES0pNM6mIQ"
USERNAME = "BLUELOGISTICA_TST#YIRLobVp6gOGHtmIyp4ATHVfKWFhkywl8rWuuLGXMpwusD7dCZrObsxB1xlK5C69K6fZA4aZ9qBvnjfsy1YyaA"
PASSWORD = "xja7dTAKaSAQsDKYvvQ23NpMLuAewFzk7z1fO3B4cfO7WoK9WnucjG71QGsMlwO5W9438bCxS66xX5UdJjXAoA"

TOKEN_URL = "https://mingle-sso.inforcloudsuite.com:443/BLUELOGISTICA_TST/as/token.oauth2"


# ---------- FUNÇÃO: GERAR TOKEN ----------

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
        print("Erro ao gerar token:", resp.status_code, resp.text)
        return None

    return resp.json().get("access_token")


# ---------- FUNÇÃO: XML -> JSON SHIPMENTS (INFOR) ----------

def xml_para_infor_shipment(xml_bytes: bytes):
    ns = {"n": "http://www.portalfiscal.inf.br/nfe"}
    root = ET.fromstring(xml_bytes)

    # CNPJ emitente
    emit_cnpj_el = root.find(".//n:emit/n:CNPJ", ns)
    emit_cnpj = emit_cnpj_el.text if emit_cnpj_el is not None else None
    storerkey = CNPJ_MAP.get(emit_cnpj, emit_cnpj)

    # Número da NF
    nNF_el = root.find(".//n:ide/n:nNF", ns)
    orderkey = nNF_el.text if nNF_el is not None else None

    # Data de emissão
    dhEmi_el = root.find(".//n:ide/n:dhEmi", ns)
    orderdate = None
    if dhEmi_el is not None and "T" in dhEmi_el.text:
        orderdate = dhEmi_el.text.split("T")[0]

    # Itens
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


# ---------- ENDPOINT PRINCIPAL ----------

@app.post("/processar")
async def processar_arquivo(
    planta: str = Form(...),
    arquivo: UploadFile = File(...)
):
    # valida planta
    if planta not in WAREHOUSE_MAP:
        return {"erro": f"Planta inválida: {planta}"}

    warehouse_real = WAREHOUSE_MAP[planta]

    # lê XML
    xml_bytes = await arquivo.read()

    # transforma XML -> JSON padrão Infor (shipments)
    shipment_json = xml_para_infor_shipment(xml_bytes)

    # gera token
    token = gerar_token()
    if not token:
        return {"erro": "Falha ao gerar token no Infor"}

    # monta endpoint final de shipments
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
