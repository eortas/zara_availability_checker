import os
import re
import json
import csv
import io
import base64
import time
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ==========================================
# CONFIGURACIÓN
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")           # Ej: "tu-usuario/zara-bot"
GITHUB_FILE_PATH = os.getenv("GITHUB_FILE_PATH", "productos.csv")
STORE_ID = "10701" # Zara España

HEADERS_ZARA = {
    "User-Agent": "ZaraApp/22.4.2 (iPhone; iOS 16.5; Scale/3.00)",
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "es-ES,es;q=0.9",
    "Referer": "https://www.zara.com/es/es/",
}

# ==========================================
# FUNCIONES DE GITHUB (CSV COMO BASE DE DATOS)
# ==========================================

def leer_csv_github():
    """Lee el CSV desde GitHub. Devuelve (lista_de_diccionarios, sha_del_archivo)"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    resp = requests.get(url, headers=headers)
    if resp.status_code == 404:
        # El archivo no existe aún
        return [], None
    elif resp.status_code != 200:
        print(f"Error leyendo de GitHub: {resp.text}")
        return [], None

    data = resp.json()
    sha = data["sha"]
    contenido_b64 = data["content"]
    
    # Decodificar Base64 a texto
    contenido_texto = base64.b64decode(contenido_b64).decode('utf-8')
    
    # Parsear CSV
    f = io.StringIO(contenido_texto)
    lector = csv.DictReader(f)
    productos = list(lector)
    
    return productos, sha

def guardar_csv_github(productos, sha_actual):
    """Guarda la lista de productos en el CSV de GitHub"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # Si la lista está vacía, creamos un CSV solo con cabeceras
    campos = ["id", "nombre", "url", "talla", "product_id", "sku", "notificado"]
    f = io.StringIO()
    escritor = csv.DictWriter(f, fieldnames=campos)
    escritor.writeheader()
    for p in productos:
        escritor.writerow(p)
    
    contenido_csv = f.getvalue()
    contenido_b64 = base64.b64encode(contenido_csv.encode('utf-8')).decode('utf-8')
    
    payload = {
        "message": "Actualizando productos desde el bot",
        "content": contenido_b64
    }
    if sha_actual:
        payload["sha"] = sha_actual
        
    resp = requests.put(url, headers=headers, json=payload)
    if resp.status_code in [200, 201]:
        return True
    else:
        print(f"Error guardando en GitHub: {resp.text}")
        return False

# ==========================================
# FUNCIONES DE TELEGRAM Y ZARA
# ==========================================

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML", "disable_web_page_preview": True}
    requests.post(url, json=params)

def extraer_product_id(url):
    match = re.search(r"[?&]v1=(\d+)", url)
    if match: return match.group(1)
    match = re.search(r"-p(\d+)\.html", url)
    if match: return match.group(1)
    return None

def extraer_nombre_url(url):
    # Extrae un nombre amigable del producto usando el slug de la URL
    match = re.search(r"/([a-z0-9-]+)-p\d+\.html", url)
    if match:
        return match.group(1).replace("-", " ").upper()
    return "PRODUCTO ZARA"

def obtener_mapa_tallas(url):
    # Cabeceras específicas para descargar el HTML sin ser bloqueado
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9",
        "Referer": "https://www.zara.com/es/es/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        if resp.status_code != 200:
            return {}
    except Exception:
        return {}

    html = resp.text
    mapa = {}

    # Método 1: window.zara.viewPayload
    match = re.search(r'window\.zara\.viewPayload\s*=\s*(\{.*?\});', html, re.DOTALL)
    if match:
        try:
            payload = json.loads(match.group(1))
            colores = payload.get("product", {}).get("detail", {}).get("colors", [])
            for color in colores:
                for t in color.get("sizes", []):
                    name = str(t.get("name", "")).strip()
                    sku = t.get("sku")
                    if name and sku:
                        mapa[name] = str(sku)
            if mapa: return mapa
        except Exception:
            pass

    # Método 2: Buscar patrón "sizes":[...]
    sizes_pattern = re.search(r'"sizes"\s*:\s*\[(\{.*?\}(?:,\s*\{.*?\})*)\]', html, re.DOTALL)
    if sizes_pattern:
        try:
            sizes_json = json.loads(f"[{sizes_pattern.group(1)}]")
            for size_obj in sizes_json:
                name = str(size_obj.get("name", "")).strip()
                sku = size_obj.get("sku") or size_obj.get("id")
                if name and sku:
                    mapa[name] = str(sku)
            if mapa: return mapa
        except Exception:
            pass

    # Método 3: JSON-LD
    json_ld_blocks = re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
    for bloque in json_ld_blocks:
        try:
            data = json.loads(bloque)
            items = data if isinstance(data, list) else [data]
            for item in items:
                offers = item.get("offers", {})
                if isinstance(offers, dict):
                    offers = offers.get("offers", [])
                if isinstance(offers, list):
                    for offer in offers:
                        name = str(offer.get("size", "")).strip()
                        sku_str = str(offer.get("sku", ""))
                        if name and sku_str:
                            mapa[name] = sku_str
        except Exception:
            continue

    return mapa

def verificar_stock_api(product_id, sku):
    """
    Consulta la API interna de Zara para un SKU concreto.
    Devuelve: "in_stock", "low_on_stock", "out_of_stock", o None si hay error.

    Nota: la CDN de Zara a veces devuelve SKUs internos diferentes.
    Se hacen hasta 3 intentos para mitigar esta inconsistencia.
    """
    url_api = (
        f"https://www.zara.com/itxrest/1/catalog/store/{STORE_ID}"
        f"/product/id/{product_id}/availability"
    )

    for intento in range(3):
        try:
            resp = requests.get(url_api, headers=HEADERS_ZARA, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("skusAvailability", []):
                    if str(item.get("sku")) == str(sku):
                        return item.get("availability", "unknown")
        except Exception as e:
            print(f"Error consultando Zara API (intento {intento+1}): {e}")

        # Si no encontramos el SKU, esperar un poco y reintentar
        if intento < 2:
            time.sleep(1)

    return None

# ==========================================
# RUTAS DE LA API (VERCEL)
# ==========================================

@app.route("/")
def home():
    return jsonify({"status": "Zara Bot OK", "github_repo": GITHUB_REPO})

@app.route("/api/cron", methods=["GET"])
def cron_job():
    """Esta ruta será llamada por cron-job.org cada X minutos"""
    if no_configurado():
        return jsonify({"error": "Faltan variables de entorno"}), 500

    productos, sha = leer_csv_github()
    if not productos:
        return jsonify({"mensaje": "No hay productos para comprobar"})

    hubo_cambios = False
    
    for p in productos:
        if not p.get("sku") or p.get("notificado") == "True":
            continue
            
        estado = verificar_stock_api(p["product_id"], p["sku"])
        
        if estado in ("in_stock", "low_on_stock"):
            detalle = "¡EN STOCK!" if estado == "in_stock" else "POCAS UNIDADES"
            enviar_telegram(
                f"🎉 <b>¡TALLA {p['talla']} DISPONIBLE!</b>\n\n"
                f"📦 {p['nombre']}\n"
                f"📊 Estado: {detalle}\n\n"
                f"👉 <a href='{p['url']}'>Comprar ahora</a>"
            )
            p["notificado"] = "True"
            hubo_cambios = True

    if hubo_cambios:
        guardar_csv_github(productos, sha)
        
    return jsonify({"mensaje": "Comprobación completada", "cambios": hubo_cambios})

@app.route("/api/webhook", methods=["POST"])
def telegram_webhook():
    """Esta ruta recibe los mensajes de Telegram al instante"""
    if no_configurado():
        return "OK", 200 # No fallar si falta config para que Telegram no reintente
        
    update = request.json
    mensaje = update.get("message", {})
    texto = mensaje.get("text", "").strip()
    chat_id = str(mensaje.get("chat", {}).get("id", ""))

    if chat_id != TELEGRAM_CHAT_ID:
        return "OK", 200

    if texto.startswith("/ayuda") or texto.startswith("/start"):
        enviar_telegram(
            "🤖 <b>Bot de Zara</b>\n\n"
            "<b>Comandos disponibles:</b>\n"
            "• /añadir <code>URL TALLA [SKU]</code>\n"
            "• /listar — Ver tus productos\n"
            "• /estado — Comprobar stock ahora\n"
            "• /eliminar <code>NÚMERO</code>\n\n"
            "💡 <b>Consejo:</b> Abre el producto de Zara en tu navegador, pulsa en tu marcador <i>'Obtener SKU Zara'</i> y copia el comando de tu talla listo para pegarlo aquí."
        )
        
    elif texto.startswith("/listar"):
        productos, _ = leer_csv_github()
        if not productos:
            enviar_telegram("📋 No hay productos.")
        else:
            lineas = []
            for i, p in enumerate(productos, 1):
                estado = "🔔 Notificado" if p.get("notificado") == "True" else "👀 Vigilando"
                lineas.append(f"{i}️⃣ <b>{p['nombre']}</b> (Talla {p['talla']}) - {estado}")
            enviar_telegram("\n".join(lineas))
            
    elif texto.startswith("/eliminar"):
        partes = texto.split()
        if len(partes) == 2 and partes[1].isdigit():
            idx = int(partes[1]) - 1
            productos, sha = leer_csv_github()
            if 0 <= idx < len(productos):
                eliminado = productos.pop(idx)
                guardar_csv_github(productos, sha)
                enviar_telegram(f"🗑️ Eliminado: {eliminado['nombre']}")
            else:
                enviar_telegram("❌ Número incorrecto.")
                
    elif texto.startswith("/añadir"):
        partes = texto.split()
        if len(partes) >= 3:
            url = partes[1]
            talla = partes[2]
            sku = partes[3] if len(partes) >= 4 else None
            
            product_id = extraer_product_id(url)
            if not product_id:
                enviar_telegram("❌ URL de Zara no válida. Asegúrate de incluir el enlace correcto del producto.")
                return "OK", 200
                
            nombre = extraer_nombre_url(url)
            
            # Si no nos pasaron el SKU, intentamos obtenerlo de forma automática
            if not sku:
                enviar_telegram("🔍 Buscando la talla en Zara de forma automática, un momento...")
                mapa_tallas = obtener_mapa_tallas(url)
                sku = mapa_tallas.get(talla)
                
                # Intentar coincidencia parcial por si acaso (ej. "40 (ES)" -> "40")
                if not sku and mapa_tallas:
                    for key, val in mapa_tallas.items():
                        if talla in key or key in talla:
                            sku = val
                            talla = key # usar el nombre exacto de talla detectado
                            break
                            
            if not sku:
                enviar_telegram(
                    f"❌ No pudimos encontrar la talla <b>{talla}</b> automáticamente.\n\n"
                    f"Inténtalo de nuevo especificando el SKU al final:\n"
                    f"<code>/añadir {url} {talla} SKU_NUMERICO</code>"
                )
                return "OK", 200
                
            productos, sha = leer_csv_github()
            
            # Comprobar si ya existe ese producto + talla
            duplicado = False
            for p in productos:
                if p.get("product_id") == product_id and p.get("talla") == talla:
                    duplicado = True
                    break
            
            if duplicado:
                enviar_telegram(f"⚠️ Ya estás monitorizando <b>{nombre}</b> en talla {talla}.")
                return "OK", 200

            nuevo_id = str(len(productos) + 1)
            nuevo_prod = {
                "id": nuevo_id,
                "nombre": nombre,
                "url": url,
                "talla": talla,
                "product_id": product_id,
                "sku": sku,
                "notificado": "False"
            }
            productos.append(nuevo_prod)
            guardar_csv_github(productos, sha)
            enviar_telegram(f"✅ <b>¡Producto añadido!</b>\n📦 {nombre}\n📏 Talla: {talla}\n🔑 SKU: {sku}")
        else:
            enviar_telegram("⚠️ Uso: /añadir URL TALLA\nEjemplo: /añadir https://www.zara.com/... 40")
            
    elif texto.startswith("/estado"):
        productos, _ = leer_csv_github()
        lineas = ["📊 <b>Estado:</b>"]
        for p in productos:
            est = verificar_stock_api(p["product_id"], p["sku"])
            if est == "in_stock":
                icono = "🟢 En stock"
            elif est == "low_on_stock":
                icono = "🟡 Pocas unidades"
            elif est == "out_of_stock":
                icono = "🔴 Agotada"
            elif est is None:
                icono = "⚠️ Error al consultar"
            else:
                icono = f"❓ Estado: {est}"
            lineas.append(f"📦 Talla {p['talla']}: {icono}")
        enviar_telegram("\n".join(lineas))

    return "OK", 200

def no_configurado():
    return not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GITHUB_TOKEN, GITHUB_REPO])

# Necesario para el servidor local de pruebas
if __name__ == "__main__":
    app.run(debug=True, port=5000)
