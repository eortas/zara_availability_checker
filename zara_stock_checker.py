"""
zara_stock_checker.py
=====================
Bot de Telegram que monitoriza múltiples productos de Zara.
Puedes añadir, eliminar y listar productos directamente desde el chat.

Comandos de Telegram:
    /ayuda            — Mostrar comandos disponibles
    /añadir URL TALLA — Añadir un producto a monitorizar
    /eliminar NÚMERO  — Eliminar un producto de la lista
    /listar           — Ver todos los productos monitorizados
    /estado           — Comprobar el stock de todos ahora

Uso:
    1. Copia .env.example a .env y rellena tus datos
    2. pip install -r requirements.txt
    3. python zara_stock_checker.py
"""

import os
import re
import sys
import time
import json
import threading
import requests
from dotenv import load_dotenv

# -----------------------------------------------------------
# 1. Configuración
# -----------------------------------------------------------
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
INTERVALO = int(os.getenv("INTERVALO", "300"))  # segundos entre comprobaciones
STORE_ID = os.getenv("ZARA_STORE_ID", "10701")  # 10701 = España

# Ruta al archivo donde se guardan los productos
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PRODUCTOS_FILE = os.path.join(SCRIPT_DIR, "productos.json")

# Cabeceras HTTP que imitan un navegador para evitar bloqueos
HEADERS = {
    "User-Agent": "ZaraApp/22.4.2 (iPhone; iOS 16.5; Scale/3.00)",
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "es-ES,es;q=0.9",
    "Referer": "https://www.zara.com/es/es/",
}


# -----------------------------------------------------------
# 2. Gestión de productos (lectura/escritura de productos.json)
# -----------------------------------------------------------

def cargar_productos():
    """Lee la lista de productos desde productos.json."""
    if not os.path.exists(PRODUCTOS_FILE):
        return []
    try:
        with open(PRODUCTOS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def guardar_productos(productos):
    """Guarda la lista de productos en productos.json."""
    with open(PRODUCTOS_FILE, "w", encoding="utf-8") as f:
        json.dump(productos, f, indent=2, ensure_ascii=False)


# -----------------------------------------------------------
# 3. Funciones de extracción de datos de Zara
# -----------------------------------------------------------

def extraer_product_id(url):
    """
    Extrae el ID del color/variante del parámetro 'v1' de la URL.
    Si no existe v1, extrae el ID base del path (pXXXXXXXX).
    """
    match = re.search(r"[?&]v1=(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"-p(\d+)\.html", url)
    if match:
        return match.group(1)
    return None


def extraer_nombre_url(url):
    """
    Extrae el nombre del producto desde el slug de la URL.
    Ejemplo: '.../zueco-piel-hebilla-p12721620.html' -> 'ZUECO PIEL HEBILLA'
    """
    # Buscar el slug entre la última '/' y '-pXXXXX.html'
    match = re.search(r"/([a-z0-9-]+)-p\d+\.html", url)
    if match:
        slug = match.group(1)
        # Convertir guiones a espacios y poner en mayúsculas
        return slug.replace("-", " ").upper()
    return "PRODUCTO DESCONOCIDO"


def obtener_mapa_tallas(url):
    """
    Obtiene la página del producto e intenta extraer el mapeo
    talla -> SKU numérico desde los datos embebidos en el HTML.

    Devuelve un diccionario: {"39": "495712345", "40": "495712346", ...}
    Si falla, devuelve un diccionario vacío {}.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException:
        return {}

    html = resp.text
    mapa = {}

    # --- Estrategia 1: window.zara.viewPayload ---
    # Este objeto JS contiene todos los datos del producto, incluidas las tallas
    match = re.search(
        r'window\.zara\.viewPayload\s*=\s*(\{.*?\});', html, re.DOTALL
    )
    if match:
        try:
            payload = json.loads(match.group(1))
            colores = (
                payload.get("product", {})
                .get("detail", {})
                .get("colors", [])
            )
            for color in colores:
                for talla in color.get("sizes", []):
                    nombre = str(talla.get("name", ""))
                    sku = talla.get("sku")
                    if nombre and sku:
                        mapa[nombre] = str(sku)
            if mapa:
                return mapa
        except (json.JSONDecodeError, KeyError):
            pass

    # --- Estrategia 2: Buscar patrón "sizes":[...] en scripts ---
    # A veces los datos están en un bloque <script> como JSON inline
    sizes_pattern = re.search(
        r'"sizes"\s*:\s*\[(\{.*?\}(?:,\s*\{.*?\})*)\]',
        html,
        re.DOTALL
    )
    if sizes_pattern:
        try:
            sizes_json = json.loads(f"[{sizes_pattern.group(1)}]")
            for size_obj in sizes_json:
                nombre = str(size_obj.get("name", ""))
                sku = size_obj.get("sku") or size_obj.get("id")
                if nombre and sku:
                    mapa[nombre] = str(sku)
            if mapa:
                return mapa
        except json.JSONDecodeError:
            pass

    # --- Estrategia 3: JSON-LD (<script type="application/ld+json">) ---
    json_ld_blocks = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    for bloque in json_ld_blocks:
        try:
            data = json.loads(bloque)
            items = data if isinstance(data, list) else [data]
            for item in items:
                # Buscar offers con tallas
                offers = item.get("offers", {})
                if isinstance(offers, dict):
                    offers = offers.get("offers", [])
                if isinstance(offers, list):
                    for offer in offers:
                        talla_nombre = str(offer.get("size", ""))
                        sku_str = str(offer.get("sku", ""))
                        if talla_nombre and sku_str:
                            mapa[talla_nombre] = sku_str
        except json.JSONDecodeError:
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

    # Intentar hasta 3 veces por si la CDN devuelve SKUs internos distintos
    for intento in range(3):
        try:
            resp = requests.get(url_api, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, json.JSONDecodeError):
            return None

        for item in data.get("skusAvailability", []):
            if str(item.get("sku")) == str(sku):
                return item.get("availability", "unknown")

        # Si no encontramos el SKU, esperar un poco y reintentar
        # (la CDN puede haber devuelto SKUs internos diferentes)
        if intento < 2:
            time.sleep(1)

    return None


# -----------------------------------------------------------
# 4. Funciones de Telegram
# -----------------------------------------------------------

def enviar_telegram(mensaje, chat_id=None):
    """Envía un mensaje por Telegram al chat indicado."""
    destino = chat_id or TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {
        "chat_id": destino,
        "text": mensaje,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=params, timeout=10)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def obtener_actualizaciones(offset):
    """
    Usa long-polling para obtener mensajes nuevos del bot de Telegram.
    Devuelve una lista de 'updates' (puede estar vacía).
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"offset": offset, "timeout": 10}
    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        return data.get("result", [])
    except (requests.RequestException, json.JSONDecodeError):
        return []


# -----------------------------------------------------------
# 5. Manejo de comandos del bot
# -----------------------------------------------------------

def cmd_ayuda(chat_id):
    """Muestra los comandos disponibles."""
    texto = (
        "🤖 <b>Zara Stock Checker Bot</b>\n\n"
        "<b>Comandos disponibles:</b>\n"
        "• /añadir <code>URL TALLA [SKU]</code>\n"
        "• /listar — Ver tus productos\n"
        "• /estado — Comprobar stock ahora\n"
        "• /eliminar <code>NÚMERO</code>\n\n"
        "💡 <b>Consejo:</b> Abre el producto de Zara en tu navegador, pulsa en tu marcador <i>'Obtener SKU Zara'</i> y copia el comando de tu talla listo para pegarlo aquí.\n\n"
        f"⏱ Intervalo de comprobación: cada {INTERVALO // 60} min"
    )
    enviar_telegram(texto, chat_id)


def cmd_añadir(chat_id, argumentos):
    """
    Añade un producto nuevo a la lista.
    Uso: /añadir URL TALLA [SKU]
    El SKU es opcional; si no se da, se intenta descubrir automáticamente.
    """
    # Separar la URL, talla y SKU opcional de los argumentos
    partes = argumentos.strip().split()
    if len(partes) < 2:
        enviar_telegram(
            "⚠️ <b>Formato incorrecto</b>\n\n"
            "Uso: /añadir <code>URL TALLA [SKU]</code>\n\n"
            "Ejemplo:\n"
            "<code>/añadir https://www.zara.com/es/es/"
            "zueco-piel-hebilla-p12721620.html?v1=495716335 42</code>\n\n"
            "💡 Si tienes el SKU del bookmarklet, pégalo al final:\n"
            "<code>/añadir URL S 528564799</code>",
            chat_id,
        )
        return

    url = partes[0]
    talla = partes[1]
    sku_manual = partes[2] if len(partes) >= 3 else None

    # Validar que la URL es de Zara
    if "zara.com" not in url:
        enviar_telegram("❌ La URL no parece ser de Zara.", chat_id)
        return

    # Extraer el product ID
    product_id = extraer_product_id(url)
    if not product_id:
        enviar_telegram(
            "❌ No se pudo extraer el ID del producto de la URL.\n"
            "Asegúrate de que la URL tiene el formato correcto.",
            chat_id,
        )
        return

    enviar_telegram("🔍 Analizando producto...", chat_id)

    # Extraer el nombre del producto desde la URL
    nombre = extraer_nombre_url(url)

    # Determinar el SKU: prioridad al SKU manual del bookmarklet
    if sku_manual:
        sku = sku_manual
    else:
        # Intentar descubrir el SKU de la talla desde el HTML
        mapa_tallas = obtener_mapa_tallas(url)
        sku = mapa_tallas.get(talla)

        if not sku and mapa_tallas:
            # La talla no existe pero tenemos el mapa
            tallas_str = ", ".join(sorted(mapa_tallas.keys()))
            enviar_telegram(
                f"❌ La talla <b>{talla}</b> no existe para este producto.\n\n"
                f"Tallas disponibles: {tallas_str}",
                chat_id,
            )
            return

    # Crear el registro del producto
    productos = cargar_productos()

    # Comprobar si ya existe ese producto + talla
    for p in productos:
        if p["product_id"] == product_id and p["talla"] == talla:
            enviar_telegram(
                f"⚠️ Ya estás monitorizando <b>{nombre}</b> "
                f"en talla {talla}.",
                chat_id,
            )
            return

    nuevo = {
        "nombre": nombre,
        "url": url,
        "talla": talla,
        "product_id": product_id,
        "sku": sku,       # Puede ser None si no se pudo descubrir
        "notificado": False,
    }
    productos.append(nuevo)
    guardar_productos(productos)

    # Confirmar al usuario
    if sku:
        origen = "bookmarklet" if sku_manual else "auto"
        enviar_telegram(
            f"✅ <b>Producto añadido</b>\n\n"
            f"📦 {nombre}\n"
            f"👟 Talla: {talla}\n"
            f"🔑 SKU: {sku} ({origen})\n\n"
            f"Se comprobará cada {INTERVALO // 60} minutos.",
            chat_id,
        )
    else:
        enviar_telegram(
            f"✅ <b>Producto añadido</b> (sin SKU automático)\n\n"
            f"📦 {nombre}\n"
            f"👟 Talla: {talla}\n\n"
            f"⚠️ No se pudo descubrir el SKU automáticamente.\n"
            f"Usa /sku <code>{len(productos)} SKU_NUMÉRICO</code> "
            f"para asignarlo manualmente.\n\n"
            f"💡 Para encontrar el SKU: abre DevTools en Chrome (F12), "
            f"ve a la pestaña Network, selecciona la talla en la web "
            f"y busca la petición que contiene 'availability'.",
            chat_id,
        )


def cmd_sku(chat_id, argumentos):
    """
    Asigna un SKU manualmente a un producto.
    Uso: /sku 1 495712891
    """
    partes = argumentos.strip().split()
    if len(partes) < 2:
        enviar_telegram(
            "⚠️ Uso: /sku <code>NÚMERO SKU</code>\n"
            "Ejemplo: <code>/sku 1 495712891</code>",
            chat_id,
        )
        return

    try:
        indice = int(partes[0]) - 1
        nuevo_sku = partes[1]
    except ValueError:
        enviar_telegram("❌ El número debe ser un entero.", chat_id)
        return

    productos = cargar_productos()
    if indice < 0 or indice >= len(productos):
        enviar_telegram("❌ Número de producto no válido.", chat_id)
        return

    productos[indice]["sku"] = nuevo_sku
    productos[indice]["notificado"] = False
    guardar_productos(productos)

    p = productos[indice]
    enviar_telegram(
        f"✅ SKU actualizado para <b>{p['nombre']}</b> "
        f"(talla {p['talla']}): {nuevo_sku}",
        chat_id,
    )


def cmd_eliminar(chat_id, argumentos):
    """
    Elimina un producto de la lista.
    Uso: /eliminar 1
    """
    try:
        indice = int(argumentos.strip()) - 1
    except ValueError:
        enviar_telegram(
            "⚠️ Uso: /eliminar <code>NÚMERO</code>\n"
            "Usa /listar para ver los números.",
            chat_id,
        )
        return

    productos = cargar_productos()
    if indice < 0 or indice >= len(productos):
        enviar_telegram("❌ Número de producto no válido.", chat_id)
        return

    eliminado = productos.pop(indice)
    guardar_productos(productos)

    enviar_telegram(
        f"🗑️ Eliminado: <b>{eliminado['nombre']}</b> "
        f"(talla {eliminado['talla']})",
        chat_id,
    )


def cmd_listar(chat_id):
    """Muestra todos los productos monitorizados."""
    productos = cargar_productos()
    if not productos:
        enviar_telegram(
            "📋 No hay productos monitorizados.\n\n"
            "Usa /añadir para agregar uno.",
            chat_id,
        )
        return

    lineas = [f"📋 <b>Productos monitorizados ({len(productos)}):</b>\n"]
    for i, p in enumerate(productos, 1):
        sku_info = f"SKU: {p['sku']}" if p.get("sku") else "⚠️ Sin SKU"
        estado = "🔔 Notificado" if p.get("notificado") else "👀 Vigilando"
        lineas.append(
            f"{i}️⃣ <b>{p['nombre']}</b>\n"
            f"   Talla: {p['talla']} | {sku_info}\n"
            f"   {estado}\n"
        )

    enviar_telegram("\n".join(lineas), chat_id)


def cmd_estado(chat_id):
    """Comprueba el stock de todos los productos y muestra el resultado."""
    productos = cargar_productos()
    if not productos:
        enviar_telegram("📋 No hay productos para comprobar.", chat_id)
        return

    enviar_telegram("🔍 Comprobando stock...", chat_id)

    lineas = ["📊 <b>Estado actual:</b>\n"]
    for i, p in enumerate(productos, 1):
        if not p.get("sku"):
            lineas.append(
                f"{i}️⃣ {p['nombre']} ({p['talla']}): "
                f"⚠️ Sin SKU asignado"
            )
            continue

        estado = verificar_stock_api(p["product_id"], p["sku"])
        if estado == "in_stock":
            icono = "🟢 En stock"
        elif estado == "low_on_stock":
            icono = "🟡 Pocas unidades"
        elif estado == "out_of_stock":
            icono = "🔴 Agotada"
        elif estado is None:
            icono = "⚠️ Error al consultar"
        else:
            icono = f"❓ Estado: {estado}"

        lineas.append(f"{i}️⃣ {p['nombre']} ({p['talla']}): {icono}")

    enviar_telegram("\n".join(lineas), chat_id)


def procesar_mensaje(update):
    """
    Procesa un mensaje recibido del bot de Telegram.
    Extrae el comando y llama a la función correspondiente.
    """
    mensaje = update.get("message", {})
    texto = mensaje.get("text", "").strip()
    chat_id = str(mensaje.get("chat", {}).get("id", ""))

    # Solo responder a nuestro chat autorizado
    if TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
        return

    if not texto.startswith("/"):
        return

    # Separar el comando de los argumentos
    # Eliminar @nombre_del_bot si viene (ej: /ayuda@mi_bot)
    partes = texto.split(maxsplit=1)
    comando = partes[0].split("@")[0].lower()
    argumentos = partes[1] if len(partes) > 1 else ""

    # Despachar al handler correcto
    if comando in ("/start", "/ayuda", "/help"):
        cmd_ayuda(chat_id)
    elif comando in ("/añadir", "/anadir", "/add"):
        cmd_añadir(chat_id, argumentos)
    elif comando in ("/eliminar", "/delete", "/del"):
        cmd_eliminar(chat_id, argumentos)
    elif comando in ("/listar", "/list"):
        cmd_listar(chat_id)
    elif comando in ("/estado", "/status", "/check"):
        cmd_estado(chat_id)
    elif comando == "/sku":
        cmd_sku(chat_id, argumentos)
    else:
        enviar_telegram(
            f"❓ Comando desconocido: {comando}\n"
            f"Usa /ayuda para ver los comandos.",
            chat_id,
        )


# -----------------------------------------------------------
# 6. Bucle de verificación de stock (hilo en segundo plano)
# -----------------------------------------------------------

def bucle_verificacion():
    """
    Se ejecuta en un hilo en segundo plano.
    Cada INTERVALO segundos comprueba el stock de todos los productos.
    Envía una notificación por Telegram si alguno pasa a 'in_stock'.
    """
    print(f"🔄 Verificación de stock activa (cada {INTERVALO}s)\n")

    while True:
        time.sleep(INTERVALO)

        productos = cargar_productos()
        if not productos:
            continue

        ahora = time.strftime("%H:%M:%S")
        print(f"  [{ahora}] Comprobando {len(productos)} producto(s)...")

        hubo_cambios = False
        for p in productos:
            # Si no tiene SKU o ya fue notificado, saltar
            if not p.get("sku") or p.get("notificado"):
                continue

            estado = verificar_stock_api(p["product_id"], p["sku"])

            if estado in ("in_stock", "low_on_stock"):
                emoji = "🟢" if estado == "in_stock" else "🟡"
                detalle = "¡EN STOCK!" if estado == "in_stock" else "POCAS UNIDADES"
                print(f"    {emoji} {p['nombre']} ({p['talla']}): {detalle}")
                enviar_telegram(
                    f"🎉 <b>¡TALLA {p['talla']} DISPONIBLE!</b>\n\n"
                    f"📦 {p['nombre']}\n"
                    f"📊 Estado: {detalle}\n\n"
                    f"👉 <a href='{p['url']}'>Comprar ahora</a>",
                )
                p["notificado"] = True
                hubo_cambios = True
            elif estado == "out_of_stock":
                print(f"    🔴 {p['nombre']} ({p['talla']}): agotada")
            else:
                print(f"    ⚠️ {p['nombre']} ({p['talla']}): error")

            # Pequeña pausa entre productos para no saturar la API
            time.sleep(1)

        if hubo_cambios:
            guardar_productos(productos)


# -----------------------------------------------------------
# 7. Main: arranca el bot y la verificación de stock
# -----------------------------------------------------------

def main():
    # Validar configuración
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "TU_TOKEN_AQUI":
        print("❌ ERROR: Configura TELEGRAM_TOKEN en el archivo .env")
        sys.exit(1)
    if not TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID == "TU_CHAT_ID_AQUI":
        print("❌ ERROR: Configura TELEGRAM_CHAT_ID en el archivo .env")
        sys.exit(1)

    productos = cargar_productos()

    print("=" * 55)
    print("  ZARA STOCK CHECKER BOT")
    print("=" * 55)
    print(f"  Productos monitorizados: {len(productos)}")
    print(f"  Intervalo:               {INTERVALO}s ({INTERVALO // 60} min)")
    print(f"  Archivo:                 {PRODUCTOS_FILE}")
    print("=" * 55)

    # Arrancar el hilo de verificación de stock
    hilo = threading.Thread(target=bucle_verificacion, daemon=True)
    hilo.start()

    # Enviar mensaje de arranque
    enviar_telegram(
        f"🤖 <b>Zara Stock Checker iniciado</b>\n\n"
        f"📦 Productos: {len(productos)}\n"
        f"⏱ Intervalo: cada {INTERVALO // 60} min\n\n"
        f"Escribe /ayuda para ver los comandos."
    )

    # Bucle principal: escuchar comandos de Telegram
    print("\n📡 Escuchando comandos de Telegram... (Ctrl+C para salir)\n")
    offset = 0
    while True:
        try:
            updates = obtener_actualizaciones(offset)
            for update in updates:
                procesar_mensaje(update)
                offset = update["update_id"] + 1
        except KeyboardInterrupt:
            print("\n\n🛑 Bot detenido por el usuario.")
            enviar_telegram("🛑 Bot detenido.")
            break
        except Exception as e:
            print(f"  ⚠️ Error en polling: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
