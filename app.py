"""
app.py
======
Versión Flask del stock checker de Zara, diseñada para desplegar
en Render / Railway y ser invocada por cron-job.org cada X minutos.

Endpoints:
    GET /           -> Health check
    GET /verificar  -> Comprueba stock y envía Telegram si hay talla disponible
"""

import os
import re
import json
import requests
from flask import Flask, jsonify
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)

# -----------------------------------------------------------
# Configuración (se lee de variables de entorno)
# -----------------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ZARA_PRODUCT_URL = os.getenv(
    "ZARA_PRODUCT_URL",
    "https://www.zara.com/es/es/zueco-piel-hebilla-p12721620.html?v1=495716335"
)
TALLA_BUSCADA = os.getenv("TALLA_BUSCADA", "42")
STORE_ID = "10701"  # Zara España

# SKU de la talla 42 del Zueco Piel Hebilla (descubierto via API)
SKU_TALLA_42 = "495712891"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "es-ES,es;q=0.9",
    "Referer": "https://www.zara.com/es/es/",
}


# -----------------------------------------------------------
# Funciones auxiliares (mismas que en zara_stock_checker.py)
# -----------------------------------------------------------

def extraer_product_id(url):
    """Extrae el productId del parámetro 'v1' de la URL de Zara."""
    match = re.search(r"[?&]v1=(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"-p(\d+)\.html", url)
    if match:
        return match.group(1)
    return None


def verificar_stock_api(product_id, sku_buscado):
    """
    Consulta la API interna de Zara para comprobar la disponibilidad.
    Devuelve: "in_stock", "out_of_stock", o None si hay error.
    """
    url_api = (
        f"https://www.zara.com/itxrest/1/catalog/store/{STORE_ID}"
        f"/product/id/{product_id}/availability"
    )
    try:
        response = requests.get(url_api, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, json.JSONDecodeError) as e:
        print(f"Error al consultar API: {e}")
        return None

    for item in data.get("skusAvailability", []):
        if str(item.get("sku")) == str(sku_buscado):
            return item.get("availability", "unknown")

    return None


def enviar_telegram(mensaje):
    """Envía un mensaje de texto a tu chat de Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        return resp.status_code == 200
    except requests.RequestException as e:
        print(f"Error Telegram: {e}")
        return False


# -----------------------------------------------------------
# Endpoints de Flask
# -----------------------------------------------------------

@app.route("/")
def index():
    """Health check - para verificar que la app está corriendo."""
    return jsonify({
        "status": "ok",
        "servicio": "Zara Stock Checker",
        "producto": ZARA_PRODUCT_URL,
        "talla": TALLA_BUSCADA,
    })


@app.route("/verificar")
def verificar():
    """
    Endpoint principal: comprueba el stock y envía Telegram si hay stock.
    Pensado para ser llamado por cron-job.org cada X minutos.
    """
    product_id = extraer_product_id(ZARA_PRODUCT_URL)
    if not product_id:
        return jsonify({"error": "No se pudo extraer el ID del producto"}), 500

    # Usar el SKU hardcodeado para la talla 42
    sku = SKU_TALLA_42
    estado = verificar_stock_api(product_id, sku)

    resultado = {
        "producto": "ZUECO PIEL HEBILLA",
        "talla": TALLA_BUSCADA,
        "sku": sku,
        "estado": estado or "error",
        "notificado": False,
    }

    if estado == "in_stock":
        # ¡Talla disponible! Enviar notificación
        enviado = enviar_telegram(
            f"🎉 <b>¡TALLA {TALLA_BUSCADA} DISPONIBLE!</b>\n\n"
            f"Producto: ZUECO PIEL HEBILLA\n"
            f"Precio: 27,96 EUR (-30%)\n\n"
            f"👉 <a href='{ZARA_PRODUCT_URL}'>Comprar ahora</a>"
        )
        resultado["notificado"] = enviado

    return jsonify(resultado), 200


# -----------------------------------------------------------
# Arranque
# -----------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
