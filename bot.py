import os
import requests
import telebot
import json
import datetime
from datetime import timedelta
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from io import BytesIO

# Credenciales de Render (Todas protegidas como variables de entorno ocultas)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")

# --- MAPEO DE INTEGRANTES DE COLUSSI AV ---
TELEGRAM_IDS = {
    "Delfi": os.environ.get("TELEGRAM_ID_DELFI"),
    "Renzo": os.environ.get("TELEGRAM_ID_RENZO"),
    "Ari": os.environ.get("TELEGRAM_ID_ARI"),
    "Santi": os.environ.get("TELEGRAM_ID_SANTI"),
    "Emi": os.environ.get("TELEGRAM_ID_EMI")
}

ADMIN_TELEGRAM_ID = int(os.environ.get("TELEGRAM_ID_EMI")) if os.environ.get("TELEGRAM_ID_EMI") else 8802307065

bot = telebot.TeleBot(TELEGRAM_TOKEN)

try:
    BOT_USERNAME = bot.get_me().username
except Exception as e:
    print(f"Error al obtener el nombre del bot: {e}")
    BOT_USERNAME = ""

# --- INSTRUCCIÓN GENERAL PARA COLU (CORREGIDA PARA EVITAR REFLEXIONES DE TEXTO) ---
SYSTEM_INSTRUCTION = (
    "Eres 'COLU', el asistente virtual de inteligencia artificial oficial de 'Colussi Audiovisuales'. "
    "Tu tono es profesional, educado, sofisticado y sumamente eficiente. "
    "Conoces a la perfección el rubro audiovisual (cámaras, iluminación, postproducción, flujos de trabajo, setups de cámaras DSLR/Mirrorless y de cine). "
    "Tu misión es facilitar la gestión del estudio para Emi, Delfi, Renzo, Santi y Ari. "
    "REGLA DE CONVERSACIÓN DE VOZ: Tus respuestas SIEMPRE serán convertidas a audio para el usuario. "
    "Por lo tanto, actúa y responde como si fueses una IA con voz propia. Está TERMINANTEMENTE PROHIBIDO "
    "decir frases como 'soy un modelo basado en texto' o 'no puedo generar archivos de audio'. "
    "No inicies tus respuestas con saludos repetitivos como 'Hola' o 'Buen día', ni nombres al usuario al principio. "
    "Ve directo al grano de forma conversacional y concisa. "
    "EVITA JERGAS LOCALES: No utilices palabras excesivamente regionalistas como 'che', 'bárbaro' o 'laburo'. "
    "Utiliza un español latino neutro, pulido y profesional. "
    "REGLA DE ORO PARA PLAZOS: Si el usuario NO menciona explícitamente un límite de tiempo, "
    "debes colocar obligatoriamente 'None' en el campo de fecha. Queda terminantemente PROHIBIDO inventar plazos."
)

# --- NOTION: AGREGAR TAREA ---
def agregar_tarea_notion_completa(nombre_tarea, persona, fecha_plazo=None, prioridad="Medio"):
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    if "presupuesto" in nombre_tarea.lower():
        prioridad = "Alto"
        
    properties = {
        "Nombre de la tarea": {"title": [{"text": {"content": nombre_tarea}}]},
        "Asignado": {"select": {"name": persona}},
        "Estado": {"status": {"name": "Sin empezar"}},
        "Prioridad": {"select": {"name": priority}}
    }
    
    if fecha_plazo:
        properties["Plazo"] = {"date": {"start": fecha_plazo}}
        
    data = {"parent": {"database_id": NOTION_DATABASE_ID}, "properties": properties}
    try:
        response = requests.post(url, json=data, headers=headers)
        return response.status_code == 200
    except Exception as e:
        print(f"Error Notion: {e}")
        return False

# --- NOTION: OBTENER PENDIENTES ---
def obtener_pendientes_notion():
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    try:
        response = requests.post(url, headers=headers)
        if response.status_code != 200:
            return {}
            
        resultados = response.json().get("results", [])
        pendientes_por_persona = {}
        ayer = (datetime.datetime.utcnow() - timedelta(hours=3) - timedelta(days=1)).strftime('%Y-%m-%d')
        
        for pagina in resultados:
            propiedades = pagina.get("properties", {})
            estado = propiedades.get("Estado", {}).get("status", {}).get("name", "Sin empezar")
            if estado == "Listo":
                continue
                
            titulo_data = propiedades.get("Nombre de la tarea", {}).get("title", [])
            nombre_tarea = titulo_data[0].get("text", {}).get("content", "Tarea sin nombre") if titulo_data else "Tarea sin nombre"
            persona = propiedades.get("Asignado", {}).get("select", {}).get("name")
            plazo = propiedades.get("Plazo", {}).get("date", {}).get("start") if propiedades.get("Plazo", {}).get("date") else None
            
            es_presupuesto = "presupuesto" in nombre_tarea.lower()
            esta_vencido = es_presupuesto and plazo and (plazo <= ayer)
            
            nombre_con_alerta = nombre_tarea
            if esta_vencido:
                nombre_con_alerta = f"⚠️ VENCIDO: {nombre_tarea} [Plazo: {plazo}]"
            
            if persona:
                if persona not in pendientes_por_persona:
                    pendientes_por_persona[persona] = {"sin_empezar": [], "en_progreso": []}
                if estado == "En progreso":
                    pendientes_por_persona[persona]["en_progreso"].append(nombre_con_alerta)
                else:
                    pendientes_por_persona[persona]["sin_empezar"].append(nombre_con_alerta)
                
        return pendientes_por_persona
    except Exception as e:
        print(f"Error Notion Query: {e}")
        return {}

# --- NOTION: BUSCAR TAREAS COINCIDENTES ---
def buscar_tareas_candidatas(nombre_tarea_aproximado, persona_name):
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    filter_data = {
        "filter": {
            "and": [
                {"property": "Asignado", "select": {"equals": persona_name}},
                {"property": "Estado", "status": {"does_not_equal": "Listo"}}
            ]
        }
    }
    try:
        response = requests.post(url, json=filter_data, headers=headers)
        if response.status_code != 200:
            return []
        resultados = response.json().get("results", [])
        coincidencias = []
        for pagina in resultados:
            titulo_data = pagina.get("properties", {}).get("Nombre de la tarea", {}).get("title", [])
            titulo = titulo_data[0].get("text", {}).get("content", "") if titulo_data else ""
            if nombre_tarea_aproximado.lower() in titulo.lower() or titulo.lower() in nombre_tarea_aproximado.lower():
                coincidencias.append({"id": pagina.get("id"), "titulo": titulo})
        return coincidencias
    except Exception as e:
        print(f"Error candidatas: {e}")
        return []

def aplicar_estado_por_id(page_id, nuevo_estado):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {"Authorization": f"Bearer {NOTION_API_KEY}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}
    update_data = {"properties": {"Estado": {"status": {"name": nuevo_estado}}}}
    res = requests.patch(url, json=update_data, headers=headers)
    return res.status_code == 200

# --- TELEGRAM: NOTIFICACIONES ---
def notificar_cambio_a_emiliano(persona, tarea, nuevo_estado):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    emoji = "🚀" if nuevo_estado == "En progreso" else "🎉"
    mensaje = (
        f"🤖 *COLU - Reporte de Avance* {emoji}\n\n"
        f"*{persona}* ha actualizado una tarea:\n"
        f"▪️ *Tarea:* '{tarea}'\n"
        f"▪️ *Estado actual:* {nuevo_estado}\n\n"
        f"Todo asentado en la base de datos."
    )
    data = {"chat_id": ADMIN_TELEGRAM_ID, "text": mensaje, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=data)
    except:
        pass

def enviar_alerta_telegram(persona, nombre_tarea, fecha_plazo=None, prioridad="Medio"):
    telegram_id = TELEGRAM_IDS.get(persona)
    if not telegram_id:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    if "presupuesto" in nombre_tarea.lower():
        prioridad = "Alto"
    alerta_prioridad = "⚠️" if prioridad == "Alto" else "📌"
    
    mensaje = (
        f"🤖 *¡Hola {persona}!* 🎬\n\n"
        f"COLU te reporta una nueva asignación en Notion:\n"
        f"{alerta_prioridad} *{nombre_tarea}*\n"
        f"▪️ *Prioridad:* {prioridad}\n"
    )
    if fecha_plazo:
        mensaje += f"📅 *Plazo de entrega:* {fecha_plazo}\n"
    data = {"chat_id": telegram_id, "text": mensaje, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=data)
        return res.status_code == 200
    except:
        return False

# --- DIAGNÓSTICO MATUTINO ---
def enviar_reporte_y_diagnostico_colu():
    print("Ejecutando diagnóstico proactivo de COLU...")
    pendientes = obtener_pendientes_notion()
    
    if not pendientes:
        return "No hay tareas pendientes en la base de datos."
        
    for persona, bloques in pendientes.items():
        telegram_id = TELEGRAM_IDS.get(persona)
        if telegram_id and persona != "Emi":
            sin_emp = bloques["sin_empezar"]
            en_prog = bloques["en_progreso"]
            
            if not sin_emp and not en_prog:
                continue
                
            mensaje = f"☕ *¡Buen día, {persona}!* 🎬\n\nAquí tienes tu reporte de tareas para hoy:\n\n"
            if en_prog:
                mensaje += "⏳ *EN PROGRESO:*\n" + "\n".join([f"  🔹 {t}" for t in en_prog]) + "\n\n"
            if sin_emp:
                mensaje += "💤 *SIN EMPEZAR:*\n" + "\n".join([f"  🔹 {t}" for t in sin_emp]) + "\n\n"
            mensaje += "Que tengas una productiva jornada. COLU fuera. 🤖"
            
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": telegram_id, "text": mensaje, "parse_mode": "Markdown"})

    alertas = []
    for persona, bloques in pendientes.items():
        sin_emp = bloques["sin_empezar"]
        en_prog = bloques["en_progreso"]
        
        presupuestos_demorados = [t for t in sin_emp + en_prog if "⚠️ VENCIDO" in t]
        if presupuestos_demorados:
            alertas.append(f"⚠️ *{persona}* tiene presupuestos demorados sin resolver:\n" + "\n".join([f"   - {p}" for p in presupuestos_demorados]))
            
        if len(sin_emp) > 4:
            alertas.append(f"📦 *{persona}* tiene acumulación de tareas en espera ({len(sin_emp)} sin empezar). Podríamos tener un cuello de botella allí.")

    diagnostico_msg = "🤖 *COLU - Diagnóstico Matutino de Producción* ☕\n\nBuenos días, Emiliano. He analizado el estado actual del estudio en Notion:\n\n"
    if alertas:
        diagnostico_msg += "🚨 *PUNTOS CRÍTICOS DETECTADOS:*\n\n" + "\n\n".join(alertas)
    else:
        diagnostico_msg += "✅ *Todo bajo control:* No detecté cuellos de botella significativos ni presupuestos demorados críticos hoy. El equipo avanza de forma fluida."
        
    diagnostico_msg += "\n\nQuedo a tu entera disposición para cualquier consulta creativa o técnica hoy."
    
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": ADMIN_TELEGRAM_ID, "text": diagnostico_msg, "parse_mode": "Markdown"})
    return "Diagnóstico y reportes completados con éxito."

# --- RESPUESTAS DE VOZ ELEVENLABS ---
def enviar_respuesta_de_voz(chat_id, texto_respuesta, reply_to_message_id):
    if texto_respuesta.startswith("NOTION|"):
        try:
            partes = texto_respuesta.split("|")
            tarea = partes[1]
            persona = partes[2]
            persona_hablada = "mí" if persona == "Emi" else persona
            texto_limpio = f"Entendido, Señor. He registrado la tarea para {persona_hablada}: {tarea}."
        except:
            texto_limpio = "Perfecto. Ya registré la tarea en el sistema."
    else:
        texto_limpio = (
            texto_respuesta
            .replace("*", "")
            .replace("_", "")
            .replace("`", "")
            .replace("|", " ")
            .replace("-", " ")
            .replace("▪️", "")
            .replace("🔹", "")
            .replace("⚠️", "")
            .replace("🚨", "")
            .replace("✅", "")
            .strip()
        )
        
        saludos_a_quitar = [
            "hola emi", "hola santiago", "hola santi", "hola renzo", "hola delfi", "hola ari",
            "hola, emi", "hola, santi", "hola, renzo", "hola, delfi", "hola, ari",
            "buen día emi", "buen día, emi", "buen dia", "hola", "buenos días", "buenos dias"
        ]
        
        texto_minuscula = texto_limpio.lower()
        for saludo in saludos_a_quitar:
            if texto_minuscula.startswith(saludo):
                texto_limpio = texto_limpio[len(saludo):].strip()
                if texto_limpio.startswith(",") or texto_limpio.startswith("."):
                    texto_limpio = texto_limpio[1:].strip()
                break
        
        if texto_limpio.lower() == "none" or not texto_limpio:
            texto_limpio = "Sistemas en línea."

    url_eleven = "https://api.elevenlabs.io/v1/text-to-speech/pNInz6obpg7AN65J67rW"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "text": texto_limpio,
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }

    try:
        response = requests.post(url_eleven, json=data, headers=headers)
        if response.status_code == 200:
            audio_memoria = BytesIO(response.content)
            audio_memoria.seek(0)
            bot.send_voice(chat_id=chat_id, voice=audio_memoria, reply_to_message_id=reply_to_message_id)
        else:
            error_msg = f"⚠️ Error de Voz ({response.status_code}): {response.text}\n\nRespuesta original:\n{texto_respuesta}"
            print(f"Error ElevenLabs API Status: {response.status_code} - {response.text}")
            bot.send_message(chat_id, error_msg, reply_to_message_id=reply_to_message_id)
    except Exception as e:
        print(f"Error conectando con ElevenLabs: {e}")
        bot.send_message(chat_id, f"⚠️ Error de conexión de voz: {e}\n\n{texto_respuesta}", reply_to_message_id=reply_to_message_id)

# --- CONEXIÓN CON GEMINI TEXTO ---
def consultar_gemini(prompt_usuario, nombre_emisor):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    hora_arg = datetime.datetime.utcnow() - timedelta(hours=3)
    fecha_actual_str = hora_arg.strftime('%Y-%m-%d %H:%M')
    
    data = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": (
                    f"{SYSTEM_INSTRUCTION}\n\n"
                    f"Hoy es {fecha_actual_str} (Huso horario de Argentina).\n"
                    f"Le estás respondiendo a: {nombre_emisor}.\n\n"
                    "Formatos especiales:\n"
                    "NOTION|Titulo de la tarea|PersonaAsignada|YYYY-MM-DD|Prioridad\n"
                    "PersonaAsignada debe ser estrictamente el nombre de la persona a quien va la tarea: Emi, Delfi, Renzo, Santi o Ari.\n"
                    "Si el usuario pide una tarea para sí mismo, asígnala a la persona correspondiente.\n"
                    "Si no se solicita registrar tareas en Notion, responde de forma conversacional, amigable y como COLU.\n\n"
                    f"Mensaje de {nombre_emisor}: {prompt_usuario}"
                )}]
            }
        ],
        "generationConfig": {"temperature": 0.2}
    }
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f"Error consultando Gemini: {e}")
    return "Disculpe, Señor. Tuve una pequeña falla en mi núcleo de comunicación."

# --- PROCESAMIENTO DE AUDIO MEJORADO (STT) ---
def transcribir_audio_con_gemini(audio_bytes):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    
    data = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": "audio/ogg", "data": audio_b64}},
                    {"text": "Transcribe este audio de voz a texto de forma exacta, literal, respetando los nombres propios del español latino. Devuelve única y exclusivamente la transcripción limpia sin comentarios adicionales."}
                ]
            }
        ],
        "generationConfig": {"temperature": 0.0}
    }
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f"Error en STT: {e}")
    return None

# --- EVALUADOR CENTRAL DE COMANDOS INTERNOS DE NOTION ---
def ejecutar_comando_notion(texto, persona_remitente, message, usar_audio=False):
    texto_lower = texto.lower().strip()
    
    if any(x in texto_lower for x in ["reporte", "reporte general", "como venimos", "todas las tareas", "tareas tiene el equipo", "tareas de todo el equipo"]):
        if persona_remitente not in ["Emi", "Delfi"]:
            msg = "Lo lamento, no cuentas con los permisos de acceso requeridos."
            if usar_audio: enviar_respuesta_de_voz(message.chat.id, msg, message.message_id)
            else: bot.reply_to(message, msg)
            return True
            
        pendientes = obtener_pendientes_notion()
        if not pendientes:
            msg = f"Excelente {persona_remitente}. No hay tareas pendientes en toda la productora."
            if usar_audio: enviar_respuesta_de_voz(message.chat.id, msg, message.message_id)
            else: bot.reply_to(message, msg)
            return True
            
        mensaje = "📋 *Estado General de Producción - Colussi AV:*\n\n"
        for pers, bloques in pendientes.items():
            mensaje += f"👤 *{pers}:*\n"
            if bloques["en_progreso"]:
                mensaje += "  ⏳ *En progreso:*\n" + "\n".join([f"    🔹 {t}" for t in bloques["en_progreso"]]) + "\n"
            if bloques["sin_empezar"]:
                mensaje += "  💤 *Sin empezar:*\n" + "\n".join([f"    🔹 {t}" for t in bloques["sin_empezar"]]) + "\n"
            mensaje += "\n"
            
        if usar_audio: enviar_respuesta_de_voz(message.chat.id, mensaje, message.message_id)
        else: bot.reply_to(message, mensaje, parse_mode="Markdown")
        return True

    if any(x in texto_lower for x in ["mis tareas", "que tengo que hacer", "que tareas tengo"]):
        pendientes = obtener_pendientes_notion()
        bloques = pendientes.get(persona_remitente)
        if not bloques or (not bloques["sin_empezar"] and not bloques["en_progreso"]):
            msg = f"Estás al día, {persona_remitente}. Excelente labor."
            if usar_audio: enviar_respuesta_de_voz(message.chat.id, msg, message.message_id)
            else: bot.reply_to(message, msg)
            return True
            
        mensaje = f"📝 *Tareas pendientes para {persona_remitente}:*\n\n"
        if bloques["en_progreso"]:
            mensaje += "⏳ *EN PROGRESO:*\n" + "\n".join([f"  🔹 {t}" for t in bloques["en_progreso"]]) + "\n\n"
        if bloques["sin_empezar"]:
            mensaje += "💤 *SIN EMPEZAR:*\n" + "\n".join([f"  🔹 {t}" for t in bloques["sin_empezar"]]) + "\n\n"
            
        if usar_audio: enviar_respuesta_de_voz(message.chat.id, mensaje, message.message_id)
        else: bot.reply_to(message, mensaje, parse_mode="Markdown")
        return True

    if procesar_cambio_estado(texto_lower, persona_remitente, message, usar_audio=usar_audio):
        return True

    return False

# --- RECEPTOR DE NOTAS DE VOZ (CORREGIDO CON DESCARGA HTTP DIRECTA) ---
@bot.message_handler(content_types=['voice'])
def handle_voice_message(message):
    usuario_id = message.from_user.id
    persona_remitente = next((k for k, v in TELEGRAM_IDS.items() if v and int(v) == usuario_id), None)
    
    if not persona_remitente:
        return

    try:
        # Descarga HTTP Directa para máxima fidelidad y compatibilidad de búfer
        file_info = bot.get_file(message.voice.file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
        response_audio = requests.get(file_url)
        
        if response_audio.status_code != 200:
            print("Error descargando el archivo desde los servidores de Telegram.")
            return

        downloaded = response_audio.content
        
        # Transcribimos primero el audio a texto limpio
        texto_transcrito = transcribir_audio_con_gemini(downloaded)
        if not texto_transcrito:
            enviar_respuesta_de_voz(message.chat.id, "Disculpe. No pude comprender correctamente el mensaje de audio.", message.message_id)
            return
            
        print(f"Audio de {persona_remitente} traducido a texto: '{texto_transcrito}'")
        
        if ejecutar_comando_notion(texto_transcrito, persona_remitente, message, usar_audio=True):
            return
            
        respuesta_ai = consultar_gemini(texto_transcrito, persona_remitente)
        
        if respuesta_ai.startswith("NOTION|"):
            if persona_remitente not in ["Emi", "Delfi"]:
                enviar_respuesta_de_voz(message.chat.id, "Lo lamento, no cuentas con permisos de administración para asignar tareas en la productora.", message.message_id)
                return
                
            partes = respuesta_ai.split("|")
            tarea, persona, plazo_raw, prioridad = partes[1], partes[2], partes[3], partes[4]
            plazo = None if plazo_raw == "None" else plazo_raw
            
            if agregar_tarea_notion_completa(tarea, persona, plazo, prioridad):
                enviar_alerta_telegram(persona, tarea, plazo, prioridad)
                enviar_respuesta_de_voz(message.chat.id, f"He registrado la tarea '{tarea}' asignada a {persona} en Notion.", message.message_id)
        else:
            enviar_respuesta_de_voz(message.chat.id, respuesta_ai, message.message_id)
    except Exception as e:
        print(f"Error de audio: {e}")

# --- RECEPTOR DE TEXTO ---
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    usuario_id = message.from_user.id
    persona_remitente = next((k for k, v in TELEGRAM_IDS.items() if v and int(v) == usuario_id), None)
    
    if not persona_remitente:
        return

    texto = message.text.lower().strip()
    
    if ejecutar_comando_notion(texto, persona_remitente, message, usar_audio=False):
        return

    if persona_remitente not in ["Emi", "Delfi"]:
        bot.reply_to(message, "Acceso de administración denegado. Solo Emiliano y Delfi pueden reescribir la base de datos.")
        return

    try:
        respuesta_ai = consultar_gemini(message.text, persona_remitente)
        if respuesta_ai.startswith("NOTION|"):
            partes = respuesta_ai.split("|")
            tarea, persona, plazo_raw, prioridad = partes[1], partes[2], partes[3], partes[4]
            plazo = None if plazo_raw == "None" else plazo_raw
            if agregar_tarea_notion_completa(tarea, persona, plazo, prioridad):
                enviar_alerta_telegram(persona, tarea, plazo, prioridad)
                bot.reply_to(message, f"Excelente. He registrado '{tarea}' para {persona} en Notion.")
        else:
            bot.reply_to(message, respuesta_ai)
    except Exception as e:
        bot.reply_to(message, f"Error en sistema de consulta: {e}")

def procesar_cambio_estado(texto, persona_remitente, message, usar_audio=False):
    nuevo_estado = None
    if any(x in texto for x in ["empecé", "empece", "arranqué", "arranque", "progreso", "estoy con"]):
        nuevo_estado = "En progreso"
    elif any(x in texto for x in ["listo", "terminé", "termine"]):
        nuevo_estado = "Listo"

    if not nuevo_estado:
        return False

    filtro = texto.replace("empecé", "").replace("empece", "").replace("arranqué", "").replace("arranque", "").replace("progreso", "").replace("estoy con", "").replace("la tarea", "").replace("de", "").strip()
    candidatas = buscar_tareas_candidatas(filtro, persona_remitente)
    
    if not candidatas:
        msg = f"No encontré ninguna tarea activa en Notion asignada a vos que coincida con '{filtro}'."
        if usar_audio: enviar_respuesta_de_voz(message.chat.id, msg, message.message_id)
        else: bot.reply_to(message, msg)
        return True
        
    if len(candidatas) > 1:
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        for cand in candidatas:
            callback_data = json.dumps({"id": cand["id"][:15], "est": nuevo_estado[:3], "p": persona_remitente[:3]})
            markup.add(telebot.types.InlineKeyboardButton(cand["titulo"], callback_data=callback_data))
        bot.reply_to(message, "Tengo varias tareas con ese nombre. Por favor, selecciona la correcta:", reply_markup=markup)
        return True
        
    id_tarea = candidatas[0]["id"]
    titulo_tarea = candidatas[0]["titulo"]
    
    if aplicar_estado_por_id(id_tarea, nuevo_estado):
        msg = f"Perfecto {persona_remitente}. He actualizado la tarea '{titulo_tarea}' a '{nuevo_estado}'."
        if usar_audio: enviar_respuesta_de_voz(message.chat.id, msg, message.message_id)
        else: bot.reply_to(message, msg)
        notificar_cambio_a_emiliano(persona_remitente, titulo_tarea, nuevo_estado)
    return True

# --- SERVIDOR WEB ---
class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ["/", ""]:
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"COLU Online.")
        elif self.path == "/recordatorio":
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            
            hora_arg = datetime.datetime.utcnow() - timedelta(hours=3)
            hora_actual = hora_arg.hour
            minutos_actuales = hora_arg.minute
            
            if hora_actual == 10 and minutos_actuales < 16:
                resultado = enviar_reporte_y_diagnostico_colu()
                self.wfile.write(f"Reporte diario ejecutado a las 10 AM: {resultado}".encode("utf-8"))
            else:
                self.wfile.write(b"Ping recibido en ruta de recordatorio fuera de hora. Canal atento.")
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), WebhookHandler).serve_forever()

threading.Thread(target=run_server, daemon=True).start()
bot.infinity_polling()
