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
    "Tu tono es profesional, de estudio sofisticado y sumamente eficiente. "
    "Conoces a la perfección el rubro audiovisual (cámaras, iluminación, postproducción, flujos de trabajo, setups de cine). "
    "Tu misión es facilitar la gestión del estudio para Emi, Delfi, Renzo, Santi y Ari. "
    "REGLA DE CONVERSACIÓN DE VOZ: Tus respuestas de voz deben ir directo al grano. "
    "Está terminantemente PROHIBIDO iniciar tus respuestas con saludos repetitivos como 'Hola' o 'Buen día', "
    "o mencionar el nombre del usuario al principio de cada mensaje. Ve directo a la información técnica o de Notion requerida. "
    "EVITA JERGAS LOCALES: Utiliza un español latino neutro, pulido y profesional. "
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
    headers = {"Authorization": f"Bearer {NOTION_API_KEY}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}
    try:
        response = requests.post(url, headers=headers)
        if response.status_code != 200: return {}
        resultados = response.json().get("results", [])
        pendientes_por_persona = {}
        ayer = (datetime.datetime.utcnow() - timedelta(hours=3) - timedelta(days=1)).strftime('%Y-%m-%d')
        for pagina in resultados:
            propiedades = pagina.get("properties", {})
            estado = propiedades.get("Estado", {}).get("status", {}).get("name", "Sin empezar")
            if estado == "Listo": continue
            titulo_data = propiedades.get("Nombre de la tarea", {}).get("title", [])
            nombre_tarea = titulo_data[0].get("text", {}).get("content", "Tarea sin nombre") if titulo_data else "Tarea sin nombre"
            persona = propiedades.get("Asignado", {}).get("select", {}).get("name")
            plazo = propiedades.get("Plazo", {}).get("date", {}).get("start") if propiedades.get("Plazo", {}).get("date") else None
            es_presupuesto = "presupuesto" in nombre_tarea.lower()
            esta_vencido = es_presupuesto and plazo and (plazo <= ayer)
            nombre_con_alerta = nombre_tarea
            if esta_vencido: nombre_con_alerta = f"⚠️ VENCIDO: {nombre_tarea} [Plazo: {plazo}]"
            if persona:
                if persona not in pendientes_por_persona: pendientes_por_persona[persona] = {"sin_empezar": [], "en_progreso": []}
                if estado == "En progreso": pendientes_por_persona[persona]["en_progreso"].append(nombre_con_alerta)
                else: pendientes_por_persona[persona]["sin_empezar"].append(nombre_con_alerta)
        return pendientes_por_persona
    except Exception as e:
        print(f"Error Notion Query: {e}")
        return {}

# --- NOTION: BUSCAR TAREAS COINCIDENTES ---
def buscar_tareas_candidatas(nombre_tarea_aproximado, persona_name):
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {"Authorization": f"Bearer {NOTION_API_KEY}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}
    filter_data = {"filter": {"and": [{"property": "Asignado", "select": {"equals": persona_name}}, {"property": "Estado", "status": {"does_not_equal": "Listo"}}]}}
    try:
        response = requests.post(url, json=filter_data, headers=headers)
        if response.status_code != 200: return []
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
    mensaje = (f"🤖 *COLU - Reporte de Avance* {emoji}\n\n*{persona}* ha actualizado una tarea:\n▪️ *Tarea:* '{tarea}'\n▪️ *Estado actual:* {nuevo_estado}\n\nTodo asentado en la base de datos.")
    try: requests.post(url, json={"chat_id": ADMIN_TELEGRAM_ID, "text": mensaje, "parse_mode": "Markdown"})
    except: pass

def enviar_alerta_telegram(persona, nombre_tarea, fecha_plazo=None, prioridad="Medio"):
    telegram_id = TELEGRAM_IDS.get(persona)
    if not telegram_id: return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    if "presupuesto" in nombre_tarea.lower(): prioridad = "Alto"
    alerta_prioridad = "⚠️" if prioridad == "Alto" else "📌"
    mensaje = f"🤖 *¡Hola {persona}!* 🎬\n\nCOLU te reporta una nueva asignación en Notion:\n{alerta_prioridad} *{nombre_tarea}*\n▪️ *Prioridad:* {prioridad}\n"
    if fecha_plazo: mensaje += f"📅 *Plazo de entrega:* {fecha_plazo}\n"
    try: return requests.post(url, json={"chat_id": telegram_id, "text": mensaje, "parse_mode": "Markdown"}).status_code == 200
    except: return False

# --- DIAGNÓSTICO MATUTINO ---
def enviar_reporte_y_diagnostico_colu():
    pendientes = obtener_pendientes_notion()
    if not pendientes: return "No hay tareas pendientes."
    for persona, bloques in pendientes.items():
        telegram_id = TELEGRAM_IDS.get(persona)
        if telegram_id and persona != "Emi":
            sin_emp, en_prog = bloques["sin_empezar"], bloques["en_progreso"]
            if not sin_emp and not en_prog: continue
            mensaje = f"☕ *¡Buen día, {persona}!* 🎬\n\nHaga un seguimiento de sus asignaciones de hoy:\n\n"
            if en_prog: mensaje += "⏳ *EN PROGRESO:*\n" + "\n".join([f"  🔹 {t}" for t in en_prog]) + "\n\n"
            if sin_emp: mensaje += "💤 *SIN EMPEZAR:*\n" + "\n".join([f"  🔹 {t}" for t in sin_emp]) + "\n\n"
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": telegram_id, "text": mensaje, "parse_mode": "Markdown"})
    return "Diagnóstico diario completado."

# --- RESPUESTA DE VOZ NATIVA GENERADA DIRECTAMENTE CON GEMINI ---
def enviar_respuesta_de_voz_gemini(chat_id, prompt_texto, nombre_emisor, reply_to_message_id):
    # Solicitamos a Gemini la generación multimodal de Audio directamente
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    hora_arg = datetime.datetime.utcnow() - timedelta(hours=3)
    fecha_actual_str = hora_arg.strftime('%Y-%m-%d %H:%M')
    
    data = {
        "contents": [{
            "role": "user",
            "parts": [{"text": (
                f"{SYSTEM_INSTRUCTION}\n\n"
                f"Hoy es {fecha_actual_str} (Argentina).\n"
                f"Le respondes por voz a: {nombre_emisor}.\n"
                "IMPORTANTE: Genera una respuesta clara, profesional y directa.\n"
                f"Mensaje del usuario: {prompt_texto}"
            )}]
        }],
        "generationConfig": {
            "responseMimeType": "audio/ogg", # Le pedimos al modelo que responda con audio directo compatible con Telegram
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": "Aoede" # Voz profesional, fluida y clara
                    }
                }
            }
        }
    }
    
    try:
        res = requests.post(url, json=data, headers=headers)
        if res.status_code == 200:
            # Extraemos los bytes del audio codificado en Base64 que nos envía Gemini
            audio_base64 = res.json()['candidates'][0]['content']['parts'][0]['inlineData']['data']
            audio_bytes = base64.b64decode(audio_base64)
            
            audio_memoria = BytesIO(audio_bytes)
            audio_memoria.seek(0)
            bot.send_voice(chat_id=chat_id, voice=audio_memoria, reply_to_message_id=reply_to_message_id)
        else:
            # Respaldo si hay algún inconveniente con la cuota multimodal
            texto_resp = consultar_gemini(prompt_texto, nombre_emisor)
            bot.send_message(chat_id, texto_resp, reply_to_message_id=reply_to_message_id)
    except Exception as e:
        print(f"Error generando audio nativo con Gemini: {e}")
        texto_resp = consultar_gemini(prompt_texto, nombre_emisor)
        bot.send_message(chat_id, texto_resp, reply_to_message_id=reply_to_message_id)

# --- CONEXIÓN CON GEMINI TEXTO ---
def consultar_gemini(prompt_usuario, nombre_emisor):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    hora_arg = datetime.datetime.utcnow() - timedelta(hours=3)
    data = {
        "contents": [{"role": "user", "parts": [{"text": f"{SYSTEM_INSTRUCTION}\nHoy es {hora_arg.strftime('%Y-%m-%d')}. Formatos: NOTION|Tarea|Persona|Plazo|Prioridad. Mensaje: {prompt_usuario}"}]}],
        "generationConfig": {"temperature": 0.2}
    }
    try:
        res = requests.post(url, json=data, headers=headers)
        if res.status_code == 200: return res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except: pass
    return "Sistemas de consulta estables."

# --- PROCESAMIENTO DE AUDIO MEJORADO (STT) ---
def transcribir_audio_con_gemini(audio_bytes):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    data = {
        "contents": [{"role": "user", "parts": [{"inline_data": {"mime_type": "audio/ogg", "data": audio_b64}}, {"text": "Transcribe este audio de forma exacta."}]}],
        "generationConfig": {"temperature": 0.0}
    }
    try:
        res = requests.post(url, json=data, headers=headers)
        if res.status_code == 200: return res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except: pass
    return None

# --- EVALUADOR CENTRAL DE COMANDOS INTERNOS DE NOTION ---
def ejecutar_comando_notion(texto, persona_remitente, message, usar_audio=False):
    texto_lower = texto.lower().strip()
    if any(x in texto_lower for x in ["reporte", "reporte general", "como venimos", "todas las tareas", "tareas tiene el equipo", "tareas de todo el equipo"]):
        if persona_remitente not in ["Emi", "Delfi"]:
            bot.reply_to(message, "Acceso denegado.")
            return True
        pendientes = obtener_pendientes_notion()
        if not pendientes:
            bot.reply_to(message, "No hay tareas pendientes.")
            return True
        mensaje = "📋 *Estado General de Producción - Colussi AV:*\n\n"
        for pers, bloques in pendientes.items():
            mensaje += f"👤 *{pers}:*\n"
            if bloques["en_progreso"]: mensaje += "  ⏳ *En progreso:*\n" + "\n".join([f"    🔹 {t}" for t in bloques["en_progreso"]]) + "\n"
            if bloques["sin_empezar"]: mensaje += "  💤 *Sin empezar:*\n" + "\n".join([f"    🔹 {t}" for t in bloques["sin_empezar"]]) + "\n"
            mensaje += "\n"
        if usar_audio: enviar_respuesta_de_voz_gemini(message.chat.id, "Haz un resumen muy breve diciendo que ya les enviaste el reporte de tareas por pantalla.", persona_remitente, message.message_id)
        bot.send_message(message.chat.id, mensaje, parse_mode="Markdown")
        return True

    if any(x in texto_lower for x in ["mis tareas", "que tengo que hacer", "que tareas tengo"]):
        pendientes = obtener_pendientes_notion()
        bloques = pendientes.get(persona_remitente)
        if not bloques or (not bloques["sin_empezar"] and not bloques["en_progreso"]):
            bot.reply_to(message, "Estás al día.")
            return True
        mensaje = f"📝 *Tareas pendientes para {persona_remitente}:*\n\n"
        if bloques["en_progreso"]: mensaje += "⏳ *EN PROGRESO:*\n" + "\n".join([f"  🔹 {t}" for t in bloques["en_progreso"]]) + "\n\n"
        if bloques["sin_empezar"]: mensaje += "💤 *SIN EMPEZAR:*\n" + "\n".join([f"  🔹 {t}" for t in bloques["sin_empezar"]]) + "\n\n"
        if usar_audio: enviar_respuesta_de_voz_gemini(message.chat.id, "Menciona de forma resumida tus tareas activas de hoy.", persona_remitente, message.message_id)
        bot.send_message(message.chat.id, mensaje, parse_mode="Markdown")
        return True

    if procesar_cambio_estado(texto_lower, persona_remitente, message, usar_audio=usar_audio):
        return True
    return False

# --- RECEPTOR DE NOTAS DE VOZ ---
@bot.message_handler(content_types=['voice'])
def handle_voice_message(message):
    usuario_id = message.from_user.id
    persona_remitente = next((k for k, v in TELEGRAM_IDS.items() if v and int(v) == usuario_id), None)
    if not persona_remitente: return
    try:
        file_info = bot.get_file(message.voice.file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
        response_audio = requests.get(file_url)
        if response_audio.status_code != 200: return
        downloaded = response_audio.content
        texto_transcrito = transcribir_audio_con_gemini(downloaded)
        if not texto_transcrito: return
        
        print(f"Audio transcrito: '{texto_transcrito}'")
        if ejecutar_comando_notion(texto_transcrito, persona_remitente, message, usar_audio=True): return
        
        respuesta_ai = consultar_gemini(texto_transcrito, persona_remitente)
        if respuesta_ai.startswith("NOTION|"):
            if persona_remitente not in ["Emi", "Delfi"]: return
            partes = respuesta_ai.split("|")
            tarea, persona, plazo_raw, prioridad = partes[1], partes[2], partes[3], partes[4]
            plazo = None if plazo_raw == "None" else plazo_raw
            if agregar_tarea_notion_completa(tarea, persona, plazo, prioridad):
                enviar_alerta_telegram(persona, tarea, plazo, prioridad)
                enviar_respuesta_de_voz_gemini(message.chat.id, f"Confirma que has registrado la tarea de {tarea} en el sistema.", persona_remitente, message.message_id)
        else:
            enviar_respuesta_de_voz_gemini(message.chat.id, texto_transcrito, persona_remitente, message.message_id)
    except Exception as e:
        print(f"Error de audio: {e}")

# --- RECEPTOR DE TEXTO ---
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    usuario_id = message.from_user.id
    persona_remitente = next((k for k, v in TELEGRAM_IDS.items() if v and int(v) == usuario_id), None)
    if not persona_remitente: return
    texto = message.text.lower().strip()
    if ejecutar_comando_notion(texto, persona_remitente, message, usar_audio=False): return
    if persona_remitente not in ["Emi", "Delfi"]: return
    try:
        respuesta_ai = consultar_gemini(message.text, persona_remitente)
        if respuesta_ai.startswith("NOTION|"):
            partes = respuesta_ai.split("|")
            tarea, persona, plazo_raw, prioridad = partes[1], partes[2], partes[3], partes[4]
            plazo = None if plazo_raw == "None" else plazo_raw
            if agregar_tarea_notion_completa(tarea, persona, plazo, prioridad):
                enviar_alerta_telegram(persona, tarea, plazo, prioridad)
                bot.reply_to(message, f"Registrado exitosamente.")
        else:
            bot.reply_to(message, respuesta_ai)
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

def procesar_cambio_estado(texto, persona_remitente, message, usar_audio=False):
    nuevo_estado = None
    if any(x in texto for x in ["empecé", "empece", "arranqué", "arranque", "progreso", "estoy con"]): nuevo_estado = "En progreso"
    elif any(x in texto for x in ["listo", "terminé", "termine"]): nuevo_estado = "Listo"
    if not nuevo_estado: return False
    filtro = texto.replace("empecé", "").replace("empece", "").replace("arranqué", "").replace("arranque", "").replace("progreso", "").replace("estoy con", "").replace("la tarea", "").replace("de", "").strip()
    candidatas = buscar_tareas_candidatas(filtro, persona_remitente)
    if not candidatas: return False
    if len(candidatas) > 1:
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        for cand in candidatas:
            callback_data = json.dumps({"id": cand["id"][:15], "est": nuevo_estado[:3], "p": persona_remitente[:3]})
            markup.add(telebot.types.InlineKeyboardButton(cand["titulo"], callback_data=callback_data))
        bot.reply_to(message, "Selecciona la tarea:", reply_markup=markup)
        return True
    id_tarea, titulo_tarea = candidatas[0]["id"], candidatas[0]["titulo"]
    if aplicar_estado_por_id(id_tarea, nuevo_estado):
        msg = f"Actualizada con éxito."
        if usar_audio: enviar_respuesta_de_voz_gemini(message.chat.id, f"Informa brevemente que la tarea {titulo_tarea} pasó a estado {nuevo_estado}.", persona_remitente, message.message_id)
        else: bot.reply_to(message, msg)
        notificar_cambio_a_emiliano(persona_remitente, titulo_tarea, nuevo_estado)
    return True

# --- SERVIDOR WEB ---
class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ["/", ""]:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"COLU Online.")
        elif self.path == "/recordatorio":
            self.send_response(200)
            self.end_headers()
            enviar_reporte_y_diagnostico_colu()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), WebhookHandler).serve_forever()

threading.Thread(target=run_server, daemon=True).start()
bot.infinity_polling()
