# Zara Stock Checker — Vercel + GitHub API

Bot interactivo de Telegram alojado en **Vercel** que utiliza un archivo `.csv` en un repositorio de **GitHub** como base de datos. 

Ideal para cuentas gratuitas:
- **Vercel** aloja el código sin pausas (*Serverless*).
- **GitHub** guarda la base de datos de productos (superando el límite de solo-lectura de Vercel).
- **cron-job.org** despierta al bot para comprobar el stock.

---

## Despliegue Paso a Paso

### 1. Preparar Telegram y GitHub

1. **Telegram:** Crea un bot con [@BotFather](https://t.me/BotFather) y guarda el `TOKEN`. 
2. Obtén tu `CHAT_ID` enviando un mensaje a [@userinfobot](https://t.me/userinfobot).
3. **GitHub:** Ve a *Settings > Developer Settings > Personal Access Tokens > Tokens (classic)* y crea un token nuevo con permisos para `repo` (leer y escribir código). Guarda el `GITHUB_TOKEN`.

### 2. Desplegar en Vercel

1. Sube este código a tu repositorio de GitHub (el mismo u otro).
2. Entra a [Vercel](https://vercel.com) y dale a **Add New > Project**.
3. Selecciona tu repositorio.
4. En **Environment Variables**, añade exactamente estas:
   - `TELEGRAM_TOKEN` = `Tu token de bot`
   - `TELEGRAM_CHAT_ID` = `Tu Chat ID`
   - `GITHUB_TOKEN` = `El token de GitHub (ghp_...)`
   - `GITHUB_REPO` = `TuUsuario/TuRepositorio` (ej. `juan/zara-bot`)
   - `GITHUB_FILE_PATH` = `productos.csv`
5. Haz clic en **Deploy**. 
6. Cuando termine, copia la URL que te da Vercel (ej. `https://zara-bot.vercel.app`).

### 3. Conectar Telegram con Vercel (Webhook)

Para que Vercel reciba los mensajes de Telegram al instante, abre tu navegador y pega esta URL (cambiando tus datos):

```
https://api.telegram.org/bot[TU_TELEGRAM_TOKEN]/setWebhook?url=https://[TU_URL_DE_VERCEL]/api/webhook
```
Si sale `"ok": true`, ¡el bot ya te escuchará!

### 4. Configurar comprobaciones automáticas

1. Entra a [cron-job.org](https://cron-job.org).
2. Crea un cronjob nuevo.
3. **URL:** `https://[TU_URL_DE_VERCEL]/api/cron`
4. **Schedule:** Cada 1 o 5 minutos.
5. **Method:** GET.

---

## 🤖 Uso del Bot en Telegram

Abre el chat con tu bot y usa los siguientes comandos:

- `/añadir [URL] [TALLA]` — Añade un producto (el bot buscará el SKU automáticamente, ej: `/añadir https://... 40`)
- `/listar` — Muestra los productos vigilados.
- `/estado` — Comprueba si hay stock manualmente.
- `/eliminar [NÚMERO]` — Borra un producto.
- `/ayuda` — Muestra información básica.

*Nota:* Debido a los sistemas de protección de Zara (Akamai), la extracción automática de tallas desde Vercel/servidores puede fallar y devolver un error indicando que no se pudo encontrar la talla. Si esto ocurre, puedes forzar el SKU manualmente usando: `/añadir URL TALLA SKU`.

### 🔍 Cómo conseguir el SKU fácilmente (Bookmarklet)

Para no tener que buscar el SKU manualmente en el código o en la red, puedes añadir un botón inteligente (bookmarklet) en tu navegador:

1. Muestra la barra de marcadores en tu navegador (`Ctrl + Mayús + B`).
2. Haz clic derecho en la barra de marcadores y selecciona **Añadir página** o **Agregar marcador**.
3. Ponle de nombre `🔍 Obtener SKU Zara` y en el campo de la URL pega exactamente el siguiente código:

```javascript
javascript:(function(){try{const payload=window.zara&&window.zara.viewPayload;if(!payload||!payload.product||!payload.product.detail||!payload.product.detail.colors){alert("Asegúrate de estar en una página de producto de Zara.");return;}const colors=payload.product.detail.colors;const url=window.location.href.split('#')[0];let output="<h3 style='margin:0 0 10px 0;font-family:sans-serif;'>📏 Comandos de Telegram</h3><p style='font-size:12px;color:#555;font-family:sans-serif;margin-bottom:15px;'>Haz clic en el botón de tu talla para copiar el comando de Telegram:</p>";let count=0;colors.forEach(color=>{output+=`<div style='margin-top:10px;font-family:sans-serif;'><strong>Color: ${color.name}</strong></div>`;output+="<ul style='padding-left:0;margin:5px 0;'>";color.sizes.forEach(size=>{const cmd=`/añadir ${url} ${size.name} ${size.sku}`;output+=`<li style='margin-bottom:8px;list-style:none;display:flex;align-items:center;font-family:sans-serif;font-size:12px;'><button onclick="navigator.clipboard.writeText('${cmd}');this.innerText='✅ Copiado';setTimeout(()=>this.innerText='Copiar',2000)" style='padding:4px 8px;margin-right:10px;font-size:11px;cursor:pointer;border-radius:4px;border:1px solid #000;background:#fff;font-weight:bold;'>Copiar</button><div>Talla <strong>${size.name}</strong> (SKU: ${size.sku})</div></li>`;count++;});output+="</ul>";});if(count===0){alert("No se encontraron tallas.");return;}const div=document.createElement('div');div.id='zara-sku-helper-overlay';div.style='position:fixed;top:20px;right:20px;width:380px;max-height:85%;overflow-y:auto;background:white;color:black;border:2px solid #000;box-shadow:0 10px 25px rgba(0,0,0,0.25);z-index:9999999;padding:20px;border-radius:8px;text-align:left;line-height:1.4;';div.innerHTML=output+"<button onclick='document.getElementById(\"zara-sku-helper-overlay\").remove()' style='margin-top:15px;width:100%;padding:8px;background:black;color:white;border:none;cursor:pointer;font-weight:bold;border-radius:4px;font-size:12px;'>Cerrar</button>";const existing=document.getElementById('zara-sku-helper-overlay');if(existing)existing.remove();document.body.appendChild(div);}catch(e){alert("Error: "+e.message);}})();
```

4. Guarda el marcador. Cuando estés en cualquier página de producto de Zara, haz clic en él y podrás copiar el comando directamente.

---

## Estructura

- `api/index.py`: El cerebro principal (Flask). Funciona como Serverless Function en Vercel.
- `vercel.json`: Reglas de enrutamiento para Vercel.
- `requirements.txt`: Dependencias del entorno de Python.
