import os
import requests
import telebot
import json
import datetime
from datetime import timedelta
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

# Credenciales de Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")

# --- MAPEO DE INTEGRANTES DE COLUSSI AV ---
TELEGRAM_IDS = {
    "Delfi": os.environ.get("TELEGRAM_ID_DELFI"),
    "Renzo": os.environ.get("TELEGRAM_ID_RENZO"),
    "Ari": os.environ.get("TELEGRAM_ID_ARI"),
    "Santi": os.environ.get("TELEGRAM_ID_SANTI"),
    "Emi": os.environ.get("TELEGRAM_ID_EMI")
}

# Solo Emiliano recibe las alertas de avance en privado
ADMIN_TELEGRAM_ID = 8802307065
CALENDAR_ID = "colussi.av@gmail.com"

bot = telebot.TeleBot(TELEGRAM_TOKEN)

try:
    BOT_USERNAME = bot.get_me().username
except Exception as e:
    print(f"Error al obtener el nombre del bot: {e}")
    BOT_USERNAME = ""

SYSTEM_INSTRUCTION = (
    "Eres el asistente virtual oficial de 'Colussi Audiovisuales', una productora audiovisual de Argentina. "
    "Tu objetivo es ayudar a Emiliano (el dueño) y el resto del equipo (5 personas en total: Emi, Delfi, Renzo, Santi, Ari) "
    "a organizarse, coordinar rodajes, redactar ideas y gestionar tareas cotidianas de forma prolija, amigable y muy profesional."
)

# --- GOOGLE CALENDAR (Standby) ---
def obtener_servicio_calendar():
    return None

def agendar_evento_google(titulo, inicio_iso, fin_iso, descripcion=""):
    return "La integración de Google Calendar requiere configurar una nueva clave privada segura en Render."

# --- NOTION: AGREGAR TAREA ---
def agregar_tarea_notion_completa(nombre_tarea, persona, fecha_plazo=None, prioridad="Medio"):
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    # REGLA 3: Si contiene la palabra "presupuesto", se marca automáticamente como Alto (urgente)
    if "presupuesto" in nombre_tarea.lower():
        prioridad = "Alto"
        
    properties = {
        "Nombre de la tarea": {
            "title": [{"text": {"content": nombre_tarea}}]
        },
        "Asignado": {
            "select": {"name": persona}
        },
        "Estado": {
            "status": {"name": "Sin empezar"}
        },
        "Prioridad": {
            "select": {"name": prioridad}
        }
    }
    
    if fecha_plazo:
        properties["Plazo"] = {
            "date": {"start": fecha_plazo}
        }
        
    data = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties
    }
    
    try:
        response = requests.post(url, json=data, headers=headers)
        return response.status_code == 200
    except Exception as e:
        print(f"DEBUG NOTION - Error de conexión: {e}")
        return False

# --- NOTION: OBTENER PENDIENTES (Incluye Alertas de Presupuestos Vencidos) ---
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
        
        # Fecha de ayer para calcular vencimiento de presupuestos (1 día de margen de demora)
        ayer = (datetime.datetime.utcnow() - timedelta(hours=3) - timedelta(days=1)).strftime('%Y-%m-%d')
        
        for pagina in resultados:
            propiedades = pagina.get("properties", {})
            
            estado_data = propiedades.get("Estado", {}).get("status")
            estado = estado_data.get("name", "Sin empezar") if estado_data else "Sin empezar"
            
            if estado == "Listo":
                continue
                
            titulo_data = propiedades.get("Nombre de la tarea", {}).get("title", [])
            nombre_tarea = titulo_data[0].get("text", {}).get("content", "Tarea sin nombre") if titulo_data else "Tarea sin nombre"
            
            asignado_data = propiedades.get("Asignado", {}).get("select")
            persona = asignado_data.get("name") if asignado_data else None
            
            plazo_data = propiedades.get("Plazo", {}).get("date")
            plazo = plazo_data.get("start") if plazo_data else None
            
            # Alerta de presupuestos vencidos por más de 1 día
            es_presupuesto = "presupuesto" in nombre_tarea.lower()
            esta_vencido = es_presupuesto and plazo and (plazo <= ayer)
            
            nombre_con_alerta = nombre_tarea
            if esta_vencido:
                nombre_con_alerta = f"⚠️ VENCIDO (Demorado): {nombre_tarea} [Plazo: {plazo}]"
            
            if persona:
                if persona not in pendientes_por_persona:
                    pendientes_por_persona[persona] = {"sin_empezar": [], "en_progreso": []}
                    
                if estado == "En progreso":
                    pendientes_por_persona[persona]["en_progreso"].append(nombre_con_alerta)
                else:
                    pendientes_por_persona[persona]["sin_empezar"].append(nombre_con_alerta)
                
        return pendientes_por_persona
    except Exception as e:
        print(f"Error en obtener_pendientes_notion: {e}")
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
            propiedades = pagina.get("properties", {})
            titulo_data = propiedades.get("Nombre de la tarea", {}).get("title", [])
            titulo = titulo_data[0].get("text", {}).get("content", "") if titulo_data else ""
            
            if nombre_tarea_aproximado.lower() in titulo.lower() or titulo.lower() in nombre_tarea_aproximado.lower():
                coincidencias.append({"id": pagina.get("id"), "titulo": titulo})
                
        return coincidencias
    except Exception as e:
        print(f"Error buscando candidatas: {e}")
        return []

# --- NOTION: APLICAR CAMBIO DE ESTADO DIRECTO ---
def aplicar_estado_por_id(page_id, nuevo_estado):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    update_data = {
        "properties": {
            "Estado": {
                "status": {
                    "name": nuevo_estado
                }
            }
        }
    }
    res = requests.patch(url, json=update_data, headers=headers)
    return res.status_code == 200

# --- TELEGRAM: ENVIAR NOTIFICACIÓN DE PROGRESO A EMILIANO (FEEDBACK) ---
def notificar_cambio_a_emiliano(persona, tarea, nuevo_estado):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    emoji = "🚀" if nuevo_estado == "En progreso" else "🎉"
    mensaje = (
        f"🔔 *Feedback de Equipo* {emoji}\n\n"
        f"*{persona}* actualizó una tarea en Notion:\n"
        f"▪️ *Tarea:* '{tarea}'\n"
        f"▪️ *Nuevo Estado:* {nuevo_estado}"
    )
    data = {"chat_id": ADMIN_TELEGRAM_ID, "text": mensaje, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=data)
    except Exception as e:
        print(f"Error al enviar feedback a Emiliano: {e}")

# --- TELEGRAM: ENVIAR ALERTA INDIVIDUAL ---
def enviar_alerta_telegram(persona, nombre_tarea, fecha_plazo=None, prioridad="Medio"):
    telegram_id = TELEGRAM_IDS.get(persona)
    if not telegram_id:
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    if "presupuesto" in nombre_tarea.lower():
        prioridad = "Alto"
        
    alerta_prioridad = "⚠️" if prioridad == "Alto" else "📌"
    
    mensaje = (
        f"🔔 *¡Hola {persona}!* 🎬\n\n"
        f"Te acaban de asignar una nueva tarea en Notion:\n"
        f"{alerta_prioridad} *{nombre_tarea}*\n"
        f"▪️ *Prioridad:* {prioridad}\n"
    )
    
    if fecha_plazo:
        try:
            partes_fecha = fecha_plazo.split("-")
            fecha_bonita = f"{partes_fecha[2]}/{partes_fecha[1]}/{partes_fecha[0]}"
            mensaje += f"📅 *Plazo de entrega:* {fecha_bonita}\n"
        except:
            mensaje += f"📅 *Plazo de entrega:* {fecha_plazo}\n"
            
    data = {"chat_id": telegram_id, "text": mensaje, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=data)
        return res.status_code == 200
    except Exception as e:
        print(f"DEBUG NOTIFICACION - Error: {e}")
        return False

# --- TELEGRAM: ENVIAR REPORTE MATUTINO ---
def enviar_reporte_matutino():
    print("Iniciando generación de reporte matutino...")
    pendientes = obtener_pendientes_notion()
    
    if not pendientes:
        return "No hay tareas pendientes en la base de datos."
        
    enviados = 0
    for persona, bloques in pendientes.items():
        telegram_id = TELEGRAM_IDS.get(persona)
        if telegram_id:
            sin_emp = bloques["sin_empezar"]
            en_prog = bloques["en_progreso"]
            
            if not sin_emp and not en_prog:
                continue
                
            mensaje = f"☕ *¡Buen día, {persona}!* 🎬\n\nAcá tenés tus tareas pendientes de hoy en *Colussi AV*:\n\n"
            
            if en_prog:
                mensaje += "⏳ *EN PROGRESO (Seguimos trabajando en esto):*\n"
                mensaje += "\n".join([f"  🔹 {t}" for t in en_prog]) + "\n\n"
                
            if sin_emp:
                mensaje += "💤 *SIN EMPEZAR (Tareas nuevas en espera):*\n"
                mensaje += "\n".join([f"  🔹 {t}" for t in sin_emp]) + "\n\n"
                
            mensaje += "¡Que tengas una excelente jornada de producción! 🚀"
            
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            data = {"chat_id": telegram_id, "text": mensaje, "parse_mode": "Markdown"}
            try:
                res = requests.post(url, json=data)
                if res.status_code == 200:
                    enviados += 1
            except Exception as e:
                print(f"Error enviando reporte a {persona}: {e}")
                
    return f"Reportes enviados con éxito a {enviados} integrantes."

# --- CONEXIÓN CON GEMINI (Texto normal) ---
def consultar_gemini(prompt_usuario):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    hora_arg = datetime.datetime.utcnow() - timedelta(hours=3)
    fecha_actual_str = hora_arg.strftime('%Y-%m-%d %H:%M')
    
    data = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": (
                    f"Instrucciones del sistema: {SYSTEM_INSTRUCTION}\n\n"
                    f"Hoy es {fecha_actual_str} (Huso horario de Argentina).\n"
                    "Tienes dos tareas especiales si el usuario te lo pide:\n\n"
                    "1. AGENDAR EN GOOGLE CALENDAR:\n"
                    "Si te pide agendar, responde EXCLUSIVAMENTE con este formato:\n"
                    "AGENDAR|Titulo del evento|YYYY-MM-DDTHH:MM:SS|YYYY-MM-DDTHH:MM:SS|Breve descripcion\n\n"
                    "2. REGISTRAR EN NOTION:\n"
                    "Si te pide anotar una tarea para un miembro del equipo (Emi, Delfi, Renzo, Santi o Ari), analiza el texto buscando plazos e importancia.\n"
                    "Responde EXCLUSIVAMENTE con este formato:\n"
                    "NOTION|Titulo de la tarea|PersonaAsignada|YYYY-MM-DD|Prioridad\n\n"
                    "Reglas para NOTION:\n"
                    "- 'PersonaAsignada' debe ser estrictamente: Emi, Delfi, Renzo, Santi o Ari.\n"
                    "- 'YYYY-MM-DD' es la fecha límite (o 'None').\n"
                    "- 'Prioridad' debe ser: Alto, Medio o Bajo.\n\n"
                    "Si el usuario no pide agendar ni registrar tareas, responde como tu amigable asistente virtual normalmente.\n\n"
                    f"Mensaje del usuario: {prompt_usuario}"
                )}]
            }
        ],
        "generationConfig": {"temperature": 0.3}
    }
    
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f"Error consultando Gemini: {e}")
    return "Error de conexión."

# --- CONEXIÓN CON GEMINI (Audio Multimodal) ---
def consultar_gemini_con_audio(audio_bytes):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    
    hora_arg = datetime.datetime.utcnow() - timedelta(hours=3)
    fecha_actual_str = hora_arg.strftime('%Y-%m-%d %H:%M')
    
    data = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "audio/ogg",
                            "data": audio_b64
                        }
                    },
                    {
                        "text": (
                            f"Instrucciones del sistema: {SYSTEM_INSTRUCTION}\n\n"
                            f"Hoy es {fecha_actual_str} (Huso horario de Argentina).\n"
                            "Acabas de recibir una nota de voz. Escúchala con mucha atención y extrae la orden que contiene.\n"
                            "Tienes dos tareas especiales si el usuario te lo pide en su audio:\n\n"
                            "1. AGENDAR EN GOOGLE CALENDAR:\n"
                            "Si pide agendar, responde EXCLUSIVAMENTE con este formato:\n"
                            "AGENDAR|Titulo del evento|YYYY-MM-DDTHH:MM:SS|YYYY-MM-DDTHH:MM:SS|Breve descripcion\n\n"
                            "2. REGISTRAR EN NOTION:\n"
                            "Si pide anotar una tarea para un miembro del equipo (Emi, Delfi, Renzo, Santi o Ari), analiza el audio buscando plazos e importancia.\n"
                            "Responde EXCLUSIVAMENTE con este formato:\n"
                            "NOTION|Titulo de la tarea|PersonaAsignada|YYYY-MM-DD|Prioridad\n\n"
                            "Reglas para NOTION:\n"
                            "- 'PersonaAsignada' debe ser estrictamente: Emi, Delfi, Renzo, Santi o Ari.\n"
                            "- 'YYYY-MM-DD' es la fecha límite (o 'None').\n"
                            "- 'Prioridad' debe ser: Alto, Medio o Bajo.\n\n"
                            "Si no pide agendar ni Notion, responde amigablemente transcribiendo lo que te dijo o conversando."
                        )
                    }
                ]
            }
        ],
        "generationConfig": {"temperature": 0.3}
    }
    
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f"Error procesando audio con Gemini: {e}")
    return "Error al escuchar la nota de voz."

# --- MANEJADORES DE TELEGRAM ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "¡Asistente listo y conectado con Notion! 🎬📝")

# --- MANEJADOR DE CALLBACK (ROBUSTEZ ANTI-DUPLICADOS) ---
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        data = json.loads(call.data)
        page_id = data.get("id")
        nuevo_estado = data.get("est")
        persona = data.get("p")
        
        # Obtenemos el nombre real de la tarea para notificar
        url = f"https://api.notion.com/v1/pages/{page_id}"
        headers = {"Authorization": f"Bearer {NOTION_API_KEY}", "Notion-Version": "2022-06-28"}
        res = requests.get(url, headers=headers)
        titulo = "Tarea"
        if res.status_code == 200:
            propiedades = res.json().get("properties", {})
            titulo_data = propiedades.get("Nombre de la tarea", {}).get("title", [])
            titulo = titulo_data[0].get("text", {}).get("content", "Tarea") if titulo_data else "Tarea"

        if aplicar_estado_por_id(page_id, nuevo_estado):
            emoji = "🚀" if nuevo_estado == "En progreso" else "🎉"
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"{emoji} ¡Hecho! Pasé la tarea *'{titulo}'* a *{nuevo_estado}*.",
                parse_mode="Markdown"
            )
            # Enviamos notificación de feedback a Emiliano en privado
            notificar_cambio_a_emiliano(persona, titulo, nuevo_estado)
        else:
            bot.answer_callback_query(call.id, "No se pudo actualizar en Notion.")
    except Exception as e:
        print(f"Error en callback: {e}")
        bot.answer_callback_query(call.id, "Error procesando selección.")

# --- PROCESAR SOLICITUD DE CAMBIO DE ESTADO (TEXTO O TRANSCRIPCIÓN) ---
def procesar_cambio_estado(texto, persona_remitente, message):
    nuevo_estado = None
    filtro = ""
    
    if any(x in texto for x in ["empecé", "empece", "arranqué", "arranque", "progreso", "estoy con"]):
        nuevo_estado = "En progreso"
        filtro = texto.replace("empecé", "").replace("empece", "").replace("arranqué", "").replace("arranque", "").replace("progreso", "").replace("estoy con", "").replace("la tarea", "").replace("de", "").strip()
    elif any(x in texto for x in ["listo", "terminé", "termine"]):
        nuevo_estado = "Listo"
        filtro = texto.replace("listo", "").replace("terminé", "").replace("termine", "").replace("la tarea", "").replace("de", "").strip()

    if not nuevo_estado:
        return False

    candidatas = buscar_tareas_candidatas(filtro, persona_remitente)
    
    if not candidatas:
        bot.reply_to(message, f"No encontré ninguna tarea activa asignada a vos que coincida con '{filtro}'.")
        return True
        
    # Robustez si hay más de una tarea coincidente (Flujo híbrido)
    if len(candidatas) > 1:
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        for cand in candidatas:
            # Recortamos texto para evitar errores de longitud en los callback_data de Telegram (máx 64b)
            callback_data = json.dumps({"id": cand["id"][:15], "est": nuevo_estado[:3], "p": persona_remitente[:3]})
            markup.add(telebot.types.InlineKeyboardButton(cand["titulo"], callback_data=callback_data))
        bot.reply_to(message, "Tengo varias tareas que coinciden. Seleccioná cuál querés actualizar:", reply_markup=markup)
        return True
        
    # Si hay solo una, la cambiamos directo
    id_tarea = candidatas[0]["id"]
    titulo_tarea = candidatas[0]["titulo"]
    
    if aplicar_estado_por_id(id_tarea, nuevo_estado):
        emoji = "🚀" if nuevo_estado == "En progreso" else "🎉"
        bot.reply_to(message, f"{emoji} ¡Bárbaro {persona_remitente}! Pasé la tarea *'{titulo_tarea}'* a *{nuevo_estado}*.", parse_mode="Markdown")
        notificar_cambio_a_emiliano(persona_remitente, titulo_tarea, nuevo_estado)
    else:
        bot.reply_to(message, "No pude actualizar Notion en este momento.")
    return True

# --- PROCESAR MENSAJES DE VOZ ---
@bot.message_handler(content_types=['voice'])
def handle_voice_message(message):
    usuario_id = message.from_user.id
    is_private = message.chat.type == "private"
    
    # Filtro estricto: Solo integrantes de Colussi AV
    persona_remitente = None
    for key, val in TELEGRAM_IDS.items():
        if val and int(val) == usuario_id:
            persona_remitente = key
            break
            
    if not persona_remitente:
        return  # Ignorar por completo a extraños

    if is_private or (BOT_USERNAME in message.text if message.text else False):
        try:
            status_msg = bot.reply_to(message, "🎤 *Escuchando nota de voz...* ⏳", parse_mode="Markdown")
            
            # Descargamos el audio de Telegram
            file_info = bot.get_file(message.voice.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            
            # Gemini procesa el audio directamente de forma nativa y gratis
            respuesta_ai = consultar_gemini_con_audio(downloaded_file)
            bot.delete_message(message.chat.id, status_msg.message_id)
            
            # Intentar ver si el audio era una solicitud de cambio de estado (empecé/listo)
            texto_limpio = respuesta_ai.lower().strip()
            if procesar_cambio_estado(texto_limpio, persona_remitente, message):
                return
                
            # Restricción de roles para creación de tareas por audio (Solo Emi y Delfi)
            if respuesta_ai.startswith("NOTION|") or respuesta_ai.startswith("AGENDAR|"):
                if persona_remitente not in ["Emi", "Delfi"]:
                    bot.reply_to(message, "Lo siento, no tenés permisos para asignar tareas globales.")
                    return
            
            # Procesar acción de creación
            if respuesta_ai.startswith("NOTION|"):
                partes = respuesta_ai.split("|")
                if len(partes) >= 5:
                    tarea, persona, plazo_raw, prioridad = partes[1], partes[2], partes[3], partes[4]
                    plazo = None if plazo_raw == "None" else plazo_raw
                    
                    if agregar_tarea_notion_completa(tarea, persona, plazo, prioridad):
                        notificado = enviar_alerta_telegram(persona, tarea, plazo, prioridad)
                        aviso = f"¡Excelente! Anoté en Notion: '{tarea}' asignada a {persona}."
                        if notificado:
                            aviso += f"\n💬 Notificación privada enviada a su Telegram."
                        bot.reply_to(message, aviso)
            else:
                bot.reply_to(message, respuesta_ai)
                
        except Exception as e:
            bot.reply_to(message, f"Error de audio: {str(e)}")

# --- MANEJADOR DE MENSAJES DE TEXTO ---
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    usuario_id = message.from_user.id
    is_private = message.chat.type == "private"
    is_mentioned = BOT_USERNAME in message.text if (message.text and BOT_USERNAME) else False

    # Filtro estricto: Solo integrantes registrados
    persona_remitente = None
    for key, val in TELEGRAM_IDS.items():
        if val and int(val) == usuario_id:
            persona_remitente = key
            break
            
    if not persona_remitente:
        return  # Ignorar extraños

    if is_private or is_mentioned:
        texto = message.text.lower().strip()
        
        # 1. ACCESO GLOBAL A CONSULTAS (Solo Emi y Delfi ven todo)
        if any(x in texto for x in ["reporte general", "como venimos", "tareas generales", "todas las tareas"]):
            if persona_remitente not in ["Emi", "Delfi"]:
                bot.reply_to(message, "Lo siento, solo Emiliano y Delfi pueden solicitar el reporte general de la productora.")
                return
                
            pendientes = obtener_pendientes_notion()
            if not pendientes:
                bot.reply_to(message, "🙌 ¡Excelente! No hay tareas pendientes en toda la productora.")
                return
                
            mensaje = "📋 *Estado General de Tareas - Colussi AV:*\n\n"
            for pers, bloques in pendientes.items():
                mensaje += f"👤 *{pers}:*\n"
                if bloques["en_progreso"]:
                    mensaje += "  ⏳ *En progreso:*\n" + "\n".join([f"    🔹 {t}" for t in bloques["en_progreso"]]) + "\n"
                if bloques["sin_empezar"]:
                    mensaje += "  💤 *Sin empezar:*\n" + "\n".join([f"    🔹 {t}" for t in bloques["sin_empezar"]]) + "\n"
                mensaje += "\n"
            bot.reply_to(message, mensaje, parse_mode="Markdown")
            return

        # 2. CONSULTAS INDIVIDUALES (Cualquiera del equipo consulta lo suyo)
        if any(x in texto for x in ["mis tareas", "tengo tareas", "tengo alguna tarea", "que tengo que hacer", "que tareas tengo"]):
            pendientes = obtener_pendientes_notion()
            bloques = pendientes.get(persona_remitente)
            
            if not bloques or (not bloques["sin_empezar"] and not bloques["en_progreso"]):
                bot.reply_to(message, f"🙌 ¡Al día, {persona_remitente}! No tenés ninguna tarea pendiente asignada. ¡Excelente!")
                return
                
            mensaje = f"📝 *Tus tareas pendientes actuales, {persona_remitente}:*\n\n"
            if bloques["en_progreso"]:
                mensaje += "⏳ *EN PROGRESO:*\n" + "\n".join([f"  🔹 {t}" for t in bloques["en_progreso"]]) + "\n\n"
            if bloques["sin_empezar"]:
                mensaje += "💤 *SIN EMPEZAR:*\n" + "\n".join([f"  🔹 {t}" for t in bloques["sin_empezar"]]) + "\n\n"
                
            bot.reply_to(message, mensaje, parse_mode="Markdown")
            return

        # 3. PROCESAR ACCIONES DE "EMPECÉ" O "LISTO" (TEXTO)
        if procesar_cambio_estado(texto, persona_remitente, message):
            return

        # 4. RESTRICCIÓN DE ASIGNACIÓN (Solo Emi y Delfi pueden crear tareas usando Gemini)
        clean_text = message.text.replace(f"@{BOT_USERNAME}", "").strip() if BOT_USERNAME else message.text.strip()
        if not clean_text:
            return

        if persona_remitente not in ["Emi", "Delfi"]:
            bot.reply_to(message, "Solo Emiliano y Delfi tienen permisos de administración.")
            return

        # Consultar Gemini
        try:
            respuesta_ai = consultar_gemini(clean_text)
            
            if respuesta_ai.startswith("AGENDAR|"):
                partes = respuesta_ai.split("|")
                if len(partes) >= 5:
                    resultado = agendar_evento_google(partes[1], partes[2], partes[3], partes[4])
                    bot.reply_to(message, resultado)
                    
            elif respuesta_ai.startswith("NOTION|"):
                partes = respuesta_ai.split("|")
                if len(partes) >= 5:
                    tarea, persona, plazo_raw, prioridad = partes[1], partes[2], partes[3], partes[4]
                    plazo = None if plazo_raw == "None" else plazo_raw
                    
                    if agregar_tarea_notion_completa(tarea, persona, plazo, prioridad):
                        notificado = enviar_alerta_telegram(persona, tarea, plazo, prioridad)
                        
                        es_presu = "presupuesto" in tarea.lower()
                        prioridad_aviso = "Alto (Urgente ⚠️)" if es_presu else prioridad
                        
                        aviso = f"¡Excelente! Anoté en Notion: '{tarea}' asignada a {persona} con prioridad *{prioridad_aviso}*. 📝"
                        if notificado:
                            aviso += f"\n💬 Notificación privada enviada a su Telegram."
                        bot.reply_to(message, aviso)
            else:
                bot.reply_to(message, respuesta_ai)
        except Exception as e:
            bot.reply_to(message, f"Error: {str(e)}")

# --- SERVIDOR HTTP ---
class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "":
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Bot activo y despierto")
            
        elif self.path == "/recordatorio":
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            resultado = enviar_reporte_matutino()
            self.wfile.write(resultado.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    server.serve_forever()

server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()

print("Bot final encendido...")
bot.infinity_polling()
