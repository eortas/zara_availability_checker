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

*Nota:* El bot resolverá el SKU y el nombre del producto automáticamente haciendo una consulta rápida al HTML. Si en algún caso especial no se encuentra de forma automática, puedes forzar el SKU manualmente usando: `/añadir URL TALLA SKU`.

---

## Estructura

- `api/index.py`: El cerebro principal (Flask). Funciona como Serverless Function en Vercel.
- `vercel.json`: Reglas de enrutamiento para Vercel.
- `requirements.txt`: Dependencias del entorno de Python.
