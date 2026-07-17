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
from gtts import gTTS

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

# Lee tu ID de administrador directamente desde la variable de Render
ADMIN_TELEGRAM_ID = int(os.environ.get("TELEGRAM_ID_EMI")) if os.environ.get("TELEGRAM_ID_EMI") else 8802307065

bot = telebot.TeleBot(TELEGRAM_TOKEN)

try:
    BOT_USERNAME = bot.get_me().username
except Exception as e:
    print(f"Error al obtener el nombre del bot: {e}")
    BOT_USERNAME = ""

# --- INSTRUCCIÓN GENERAL PARA COLU ---
SYSTEM_INSTRUCTION = (
    "Eres 'COLU', el asistente virtual de inteligencia artificial oficial de 'Colussi Audiovisuales'. "
    "Tu tono es profesional, cercano, sofisticado y muy eficiente. Te diriges a los integrantes por su nombre de pila. "
    "Conoces a la perfección el rubro audiovisual (cámaras, iluminación, postproducción, flujos de trabajo, setups de cámaras DSLR/Mirrorless y de cine). "
    "Tu misión es facilitarle la vida a Emi, Delfi, Renzo, Santi y Ari. Sé proactivo, asiste en brainstorming creativo y técnico, "
    "y mantén la gestión del estudio impecable. "
    "REGLA DE ORO PARA PLAZOS: Si el usuario NO menciona explícitamente un límite de tiempo (como 'para mañana', 'el viernes', 'el 20 de julio'), "
    "debes colocar obligatoriamente 'None' en el campo de fecha. Queda terminantemente PROHIBIDO inventar o asumir plazos para el mismo día o el día siguiente."
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
        "Prioridad": {"select": {"name": prioridad}}
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

# --- TELEGRAM: ENVIAR NOTIFICACIÓN DE PROGRESO (FEEDBACK) ---
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

# --- PROCESO: DIAGNÓSTICO PROACTIVO AUTOMÁTICO DE COLU ---
def enviar_reporte_y_diagnostico_colu():
    print("Ejecutando diagnóstico proactivo de COLU...")
    pendientes = obtener_pendientes_notion()
    
    if not pendientes:
        return "No hay tareas pendientes en la base de datos."
        
    # 1. Enviar el reporte matutino a los chicos
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

    # 2. El Diagnóstico Proactivo consolidado para Emiliano
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

# --- RESPUESTAS DE VOZ REALES (NATIVAS DE TELEGRAM - OPTIMIZADAS) ---
def enviar_respuesta_de_voz(chat_id, texto_respuesta, reply_to_message_id):
    # Limpiamos formatos de texto Markdown y caracteres extraños
    texto_limpio = texto_respuesta.replace("*", "").replace("_", "").replace("`", "").replace("▪️", "").replace("🔹", "")[:350]
    
    try:
        audio_memoria = BytesIO()
        # Configuramos 'lang=es' y 'tld=com.mx' para obtener el acento mexicano/latino que es mucho más fluido.
        # Nos aseguramos de que 'slow=False' para que hable a velocidad normal y natural.
        tts = gTTS(text=texto_limpio, lang='es', tld='com.mx', slow=False)
        tts.write_to_fp(audio_memoria)
        audio_memoria.seek(0)
        
        # Le enviamos el audio como un "Voice Note" real (con forma de onda) usando la API de Telebot
        bot.send_voice(chat_id=chat_id, voice=audio_memoria, reply_to_message_id=reply_to_message_id)
        
    except Exception as e:
        print(f"Fallo de gTTS/SendVoice: {e}")
        # Caída de respaldo
        bot.send_message(chat_id, texto_respuesta, reply_to_message_id=reply_to_message_id)
        
# --- CONEXIONES CON GEMINI CON CONTEXTO DE INTEGRANTE ---
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

def consultar_gemini_con_audio(audio_bytes, nombre_emisor):
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
                            f"{SYSTEM_INSTRUCTION}\n\n"
                            f"Hoy es {fecha_actual_str} (Huso horario de Argentina).\n"
                            f"La persona que te está hablando en este audio es: {nombre_emisor}.\n\n"
                            "Si en el audio pide registrar una tarea, responde estrictamente con este formato:\n"
                            "NOTION|Titulo de la tarea|PersonaAsignada|YYYY-MM-DD|Prioridad\n"
                            "Recuerda que PersonaAsignada debe ser: Emi, Delfi, Renzo, Santi o Ari.\n"
                            "Si no se solicita registrar una tarea en Notion, responde conversacionalmente hablándole directamente por su nombre de pila."
                        )
                    }
                ]
            }
        ],
        "generationConfig": {"temperature": 0.2}
    }
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f"Error procesando audio con Gemini: {e}")
    return "Disculpe. No pude decodificar el audio correctamente."

# --- MANEJADORES DE TELEGRAM ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Sistemas en línea. COLU listo para coordinar Colussi Audiovisuales. 🎬🤖")

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        data = json.loads(call.data)
        page_id, nuevo_estado, persona = data.get("id"), data.get("est"), data.get("p")
        
        # Consultar título de la tarea en Notion
        url = f"https://api.notion.com/v1/pages/{page_id}"
        headers = {"Authorization": f"Bearer {NOTION_API_KEY}", "Notion-Version": "2022-06-28"}
        res = requests.get(url, headers=headers)
        titulo = "Tarea"
        if res.status_code == 200:
            propiedades = res.json().get("properties", {})
            titulo_data = propiedades.get("Nombre de la tarea", {}).get("title", [])
            titulo = titulo_data[0].get("text", {}).get("content", "Tarea") if titulo_data else "Tarea"

        if aplicar_estado_por_id(page_id, nuevo_estado):
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"✅ Registro actualizado: *'{titulo}'* pasó a *{nuevo_estado}*.", parse_mode="Markdown")
            notificar_cambio_a_emiliano(persona, titulo, nuevo_estado)
    except Exception as e:
        print(f"Error callback: {e}")

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
        if usar_audio:
            enviar_respuesta_de_voz(message.chat.id, msg, message.message_id)
        else:
            bot.reply_to(message, msg)
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
        if usar_audio:
            enviar_respuesta_de_voz(message.chat.id, msg, message.message_id)
        else:
            bot.reply_to(message, msg)
        notificar_cambio_a_emiliano(persona_remitente, titulo_tarea, nuevo_estado)
    return True

# --- RECEPTOR DE NOTAS DE VOZ ---
@bot.message_handler(content_types=['voice'])
def handle_voice_message(message):
    usuario_id = message.from_user.id
    persona_remitente = next((k for k, v in TELEGRAM_IDS.items() if v and int(v) == usuario_id), None)
    
    if not persona_remitente:
        return

    try:
        file_info = bot.get_file(message.voice.file_id)
        downloaded = bot.download_file(file_info.file_path)
        respuesta_ai = consultar_gemini_con_audio(downloaded, persona_remitente)
        
        # Procesar cambio de estado
        if procesar_cambio_estado(respuesta_ai.lower().strip(), persona_remitente, message, usar_audio=True):
            return
            
        # Restricciones de creación (Solo Emi y Delfi)
        if respuesta_ai.startswith("NOTION|"):
            if persona_remitente not in ["Emi", "Delfi"]:
                enviar_respuesta_de_voz(message.chat.id, "Lo lamento, no cuentas con permisos de administración para asignar tareas en la productora.", message.message_id)
                return
                
            partes = respuesta_ai.split("|")
            tarea, persona, plazo_raw, prioridad = partes[1], partes[2], partes[3], partes[4]
            plazo = None if plazo_raw == "None" else plazo_raw
            
            if agregar_tarea_notion_completa(tarea, persona, plazo, prioridad):
                enviar_alerta_telegram(persona, tarea, plazo, prioridad)
                enviar_respuesta_de_voz(message.chat.id, f"Entendido. He registrado la tarea '{tarea}' asignada a {persona} en Notion.", message.message_id)
        else:
            # Respuesta conversacional/técnica por voz
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
    
    # 1. Reporte manual solicitado por Emi o Delfi (Corregida palabra clave "reporte" sola)
    if any(x in texto for x in ["reporte", "reporte general", "como venimos", "todas las tareas"]):
        if persona_remitente not in ["Emi", "Delfi"]:
            bot.reply_to(message, "Lo lamento, no cuentas con los permisos de acceso requeridos.")
            return
        pendientes = obtener_pendientes_notion()
        if not pendientes:
            bot.reply_to(message, "Excelente, Emiliano. No hay tareas pendientes en toda la productora.")
            return
        mensaje = "📋 *Estado General de Producción - Colussi AV:*\n\n"
        for pers, bloques in pendientes.items():
            mensaje += f"👤 *{pers}:*\n"
            if bloques["en_progreso"]:
                mensaje += "  ⏳ *En progreso:*\n" + "\n".join([f"    🔹 {t}" for t in bloques["en_progreso"]]) + "\n"
            if bloques["sin_empezar"]:
                mensaje += "  💤 *Sin empezar:*\n" + "\n".join([f"    🔹 {t}" for t in bloques["sin_empezar"]]) + "\n"
            mensaje += "\n"
        bot.reply_to(message, mensaje, parse_mode="Markdown")
        return

    # 2. Consulta de tareas individuales
    if any(x in texto for x in ["mis tareas", "que tengo que hacer", "que tareas tengo"]):
        pendientes = obtener_pendientes_notion()
        bloques = pendientes.get(persona_remitente)
        if not bloques or (not bloques["sin_empezar"] and not bloques["en_progreso"]):
            bot.reply_to(message, f"Estás al día, {persona_remitente}. Excelente labor.")
            return
        mensaje = f"📝 *Tareas pendientes para {persona_remitente}:*\n\n"
        if bloques["en_progreso"]:
            mensaje += "⏳ *EN PROGRESO:*\n" + "\n".join([f"  🔹 {t}" for t in bloques["en_progreso"]]) + "\n\n"
        if bloques["sin_empezar"]:
            mensaje += "💤 *SIN EMPEZAR:*\n" + "\n".join([f"  🔹 {t}" for t in bloques["sin_empezar"]]) + "\n\n"
        bot.reply_to(message, mensaje, parse_mode="Markdown")
        return

    # 3. Procesar solicitudes de avance por texto
    if procesar_cambio_estado(texto, persona_remitente, message, usar_audio=False):
        return

    # 4. Restricción de creación
    if persona_remitente not in ["Emi", "Delfi"]:
        bot.reply_to(message, "Acceso de administración denegado. Solo Emiliano y Delfi pueden reescribir la base de datos.")
        return

    # Gemini procesa texto (Consultas técnicas, creativas o formatos de tareas)
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
            
            # Obtener la hora de Argentina (UTC-3)
            hora_arg = datetime.datetime.utcnow() - timedelta(hours=3)
            hora_actual = hora_arg.hour
            minutos_actuales = hora_arg.minute
            
            # El Cron-Job pasa cada 10 min. Evaluamos que sea la hora 9 (9:00 AM) y los primeros 10 min
            if hora_actual == 9 and minutos_actuales < 11:
                resultado = enviar_reporte_y_diagnostico_colu()
                self.wfile.write(f"Reporte diario ejecutado: {resultado}".encode("utf-8"))
            else:
                # El resto del día, solo responde OK para mantenerse despierto sin saturarte de mensajes
                self.wfile.write(b"Ping recibido de Cron-Job. COLU despierto y atento.")
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), WebhookHandler).serve_forever()

threading.Thread(target=run_server, daemon=True).start()
bot.infinity_polling()
