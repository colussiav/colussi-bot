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
    "Responde siempre de forma clara, concisa y directa mediante texto. Ve directo al grano. "
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
    if fecha_plazo and fecha_plazo != "None":
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
    if fecha_plazo and fecha_plazo != "None": 
        mensaje += f"📅 *Plazo de entrega:* {fecha_plazo}\n"
    try: return requests.post(url, json={"chat_id": telegram_id, "text": mensaje, "parse_mode": "Markdown"}).status_code == 200
    except: return False

# --- CONEXIÓN ORIGINAL RESTAURADA CON GEMINI 3.1-FLASH-LITE ---
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
                    f"Mensaje de {nombre_emisor}: {prompt_usuario}"
                )}]
            }
        ],
        "generationConfig": {"temperature": 0.2}
    }
    try:
        res = requests.post(url, json=data, headers=headers)
        if res.status_code == 200: 
            return res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f"Error Gemini Original: {e}")
    return "Disculpe, Señor. Tuve un inconveniente al procesar la solicitud."

# --- PROCESAMIENTO DE AUDIO ORIGINAL RESTAURADO (STT) ---
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
        res = requests.post(url, json=data, headers=headers)
        if res.status_code == 200: return res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f"Error STT Original: {e}")
    return None

# --- EVALUADOR DE COMANDOS DIRECTOS DE NOTION ---
def ejecutar_comando_notion(texto, persona_remitente, message):
    texto_lower = texto.lower().strip()
    
    if any(x in texto_lower for x in ["reporte", "reporte general", "como venimos", "todas las tareas", "tareas tiene el equipo"]):
        if persona_remitente not in ["Emi", "Delfi"]:
            bot.reply_to(message, "Acceso denegado. No posees permisos de administración.")
            return True
        pendientes = obtener_pendientes_notion()
        if not pendientes:
            bot.reply_to(message, "Excelente. No hay tareas pendientes en toda la productora.")
            return True
        mensaje = "📋 *Estado General de Producción - Colussi AV:*\n\n"
        for pers, bloques in pendientes.items():
            mensaje += f"👤 *{pers}:*\n"
            if bloques["en_progreso"]: mensaje += "  ⏳ *En progreso:*\n" + "\n".join([f"    🔹 {t}" for t in bloques["en_progreso"]]) + "\n"
            if bloques["sin_empezar"]: mensaje += "  💤 *Sin empezar:*\n" + "\n".join([f"    🔹 {t}" for t in bloques["sin_empezar"]]) + "\n"
            mensaje += "\n"
        bot.send_message(message.chat.id, mensaje, parse_mode="Markdown")
        return True

    if any(x in texto_lower for x in ["mis tareas", "que tengo que hacer", "que tareas tengo"]):
        pendientes = obtener_pendientes_notion()
        bloques = pendientes.get(persona_remitente)
        if not bloques or (not bloques["sin_empezar"] and not bloques["en_progreso"]):
            bot.reply_to(message, f"¡Estás al día, {persona_remitente}! Excelente labor.")
            return True
        mensaje = f"📝 *Tareas pendientes para {persona_remitente}:*\n\n"
        if bloques["en_progreso"]: mensaje += "⏳ *EN PROGRESO:*\n" + "\n".join([f"  🔹 {t}" for t in bloques["en_progreso"]]) + "\n\n"
        if bloques["sin_empezar"]: mensaje += "💤 *SIN EMPEZAR:*\n" + "\n".join([f"  🔹 {t}" for t in bloques["sin_empezar"]]) + "\n\n"
        bot.send_message(message.chat.id, mensaje, parse_mode="Markdown")
        return True

    if procesar_cambio_estado(texto_lower, persona_remitente, message):
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
        if ejecutar_comando_notion(texto_transcrito, persona_remitente, message): return
        
        respuesta_ai = consultar_gemini(texto_transcrito, persona_remitente)
        if respuesta_ai.startswith("NOTION|"):
            if persona_remitente not in ["Emi", "Delfi"]: return
            partes = respuesta_ai.split("|")
            tarea, persona, plazo_raw, prioridad = partes[1], partes[2], partes[3], partes[4]
            plazo = None if plazo_raw == "None" else plazo_raw
            if agregar_tarea_notion_completa(tarea, persona, plazo, prioridad):
                enviar_alerta_telegram(persona, tarea, plazo, prioridad)
                bot.reply_to(message, f"✅ Entendido. He registrado la tarea '{tarea}' para {persona} en Notion.")
        else:
            bot.reply_to(message, respuesta_ai)
    except Exception as e:
        print(f"Error de audio: {e}")

# --- RECEPTOR DE TEXTO PRINCIPAL ---
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    usuario_id = message.from_user.id
    persona_remitente = next((k for k, v in TELEGRAM_IDS.items() if v and int(v) == usuario_id), None)
    if not persona_remitente: return

    texto = message.text.lower().strip()
    if ejecutar_comando_notion(texto, persona_remitente, message): return

    try:
        respuesta_ai = consultar_gemini(message.text, persona_remitente)
        if respuesta_ai.startswith("NOTION|"):
            if persona_remitente not in ["Emi", "Delfi"]:
                bot.reply_to(message, "Acceso denegado para modificar la base de datos.")
                return
            partes = respuesta_ai.split("|")
            tarea, persona, plazo_raw, prioridad = partes[1], partes[2], partes[3], partes[4]
            plazo = None if plazo_raw == "None" else plazo_raw
            if agregar_tarea_notion_completa(tarea, persona, plazo, prioridad):
                enviar_alerta_telegram(persona, tarea, plazo, prioridad)
                bot.reply_to(message, f"✅ He registrado la tarea '{tarea}' para {persona} en Notion.")
        else:
            bot.reply_to(message, respuesta_ai)
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

def procesar_cambio_estado(texto, persona_remitente, message):
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
        bot.reply_to(message, "Tengo varias coincidencias, selecciona la correcta:", reply_markup=markup)
        return True
        
    id_tarea, titulo_tarea = candidatas[0]["id"], candidatas[0]["titulo"]
    if aplicar_estado_por_id(id_tarea, nuevo_estado):
        bot.reply_to(message, f"📌 Tarea '{titulo_tarea}' cambiada a '{nuevo_estado}' con éxito.")
        notificar_cambio_a_emiliano(persona_remitente, titulo_tarea, nuevo_estado)
    return True

# --- SERVIDOR WEB ---
class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ["/", ""]:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"COLU Engine Online.")
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), WebhookHandler).serve_forever()

threading.Thread(target=run_server, daemon=True).start()
bot.infinity_polling()
