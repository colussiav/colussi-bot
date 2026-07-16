import os
import requests
import telebot
import json
import datetime
from datetime import timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

# Credenciales de Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")

# --- MAPEO DE USUARIOS ---
TELEGRAM_IDS = {
    "Delfi": os.environ.get("TELEGRAM_ID_DELFI"),
    "Renzo": os.environ.get("TELEGRAM_ID_RENZO"),
    "Ari": os.environ.get("TELEGRAM_ID_ARI"),
    "Santi": os.environ.get("TELEGRAM_ID_SANTI"),
    "Emi": os.environ.get("TELEGRAM_ID_EMI")
}

# CONFIGURACIÓN DE SEGURIDAD (Solo Emiliano tiene acceso)
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

# --- GOOGLE CALENDAR ---
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

# --- NOTION: ACTUALIZAR ESTADO ---
def actualizar_estado_tarea(nombre_tarea_aproximado, persona_name, nuevo_estado):
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    filter_data = {
        "filter": {
            "and": [
                {
                    "property": "Asignado",
                    "select": {
                        "equals": persona_name
                    }
                },
                {
                    "property": "Estado",
                    "status": {
                        "does_not_equal": "Listo"
                    }
                }
            ]
        }
    }
    
    try:
        response = requests.post(url, json=filter_data, headers=headers)
        if response.status_code != 200:
            return None
            
        resultados = response.json().get("results", [])
        page_id_to_update = None
        nombre_real_tarea = ""
        
        for pagina in resultados:
            propiedades = pagina.get("properties", {})
            titulo_data = propiedades.get("Nombre de la tarea", {}).get("title", [])
            titulo = titulo_data[0].get("text", {}).get("content", "") if titulo_data else ""
            
            if nombre_tarea_aproximado.lower() in titulo.lower() or titulo.lower() in nombre_tarea_aproximado.lower():
                page_id_to_update = pagina.get("id")
                nombre_real_tarea = titulo
                break
                
        if page_id_to_update:
            update_url = f"https://api.notion.com/v1/pages/{page_id_to_update}"
            update_data = {
                "properties": {
                    "Estado": {
                        "status": {
                            "name": nuevo_estado
                        }
                    }
                }
            }
            res_update = requests.patch(update_url, json=update_data, headers=headers)
            if res_update.status_code == 200:
                return nombre_real_tarea
                
        return None
    except Exception as e:
        print(f"Error al actualizar tarea a {nuevo_estado}: {e}")
        return None

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
            
            if persona:
                if persona not in pendientes_por_persona:
                    pendientes_por_persona[persona] = {"sin_empezar": [], "en_progreso": []}
                    
                if estado == "En progreso":
                    pendientes_por_persona[persona]["en_progreso"].append(nombre_tarea)
                else:
                    pendientes_por_persona[persona]["sin_empezar"].append(nombre_tarea)
                
        return pendientes_por_persona
    except Exception as e:
        print(f"Error en obtener_pendientes_notion: {e}")
        return {}

# --- TELEGRAM: ENVIAR ALERTA INDIVIDUAL ---
def enviar_alerta_telegram(persona, nombre_tarea, fecha_plazo=None, prioridad="Medio"):
    telegram_id = TELEGRAM_IDS.get(persona)
    if not telegram_id:
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
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

# --- CONEXIÓN CON GEMINI ---
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
                    "Si te pide anotar una tarea para un miembro del equipo (Emi, Delfi, Renzo, Santi o Ari), responde EXCLUSIVAMENTE con este formato:\n"
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
    return "Error de conexión con el motor de inteligencia artificial."

# --- MANEJADORES DE TELEGRAM ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "¡Asistente listo y conectado con Notion! 🎬📝")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    usuario_id = message.from_user.id
    is_private = message.chat.type == "private"
    is_mentioned = BOT_USERNAME in message.text if (message.text and BOT_USERNAME) else False

    # Identificar quién está mandando el mensaje
    persona_remitente = None
    for key, val in TELEGRAM_IDS.items():
        if val and int(val) == usuario_id:
            persona_remitente = key
            break

    # 1. FLUJOS EXCLUSIVOS DEL EQUIPO (En privado)
    if is_private and persona_remitente:
        texto = message.text.lower().strip()
        
        # --- NUEVO ATAJO: CONSULTAR MIS PROPIAS TAREAS ---
        if any(x in texto for x in ["mis tareas", "tengo tareas", "tengo alguna tarea", "que tengo que hacer", "que tareas tengo"]):
            print(f"DEBUG CONSULTA - {persona_remitente} consultó sus tareas.")
            pendientes = obtener_pendientes_notion()
            
            # Buscamos el bloque de tareas de esta persona
            bloques = pendientes.get(persona_remitente)
            
            if not bloques or (not bloques["sin_empezar"] and not bloques["en_progreso"]):
                bot.reply_to(message, f"🙌 ¡Al día, {persona_remitente}! No tenés ninguna tarea pendiente asignada en Notion. ¡Excelente!")
                return
                
            mensaje = f"📝 *Tus tareas pendientes actuales en Colussi AV, {persona_remitente}:*\n\n"
            
            if bloques["en_progreso"]:
                mensaje += "⏳ *EN PROGRESO:*\n"
                mensaje += "\n".join([f"  🔹 {t}" for t in bloques["en_progreso"]]) + "\n\n"
                
            if bloques["sin_empezar"]:
                mensaje += "💤 *SIN EMPEZAR:*\n"
                mensaje += "\n".join([f"  🔹 {t}" for t in bloques["sin_empezar"]]) + "\n\n"
                
            bot.reply_to(message, mensaje, parse_mode="Markdown")
            return
        
        # --- ATAJO: EN PROGRESO ---
        elif any(x in texto for x in ["empecé", "empece", "arranqué", "arranque", "progreso", "estoy con"]):
            filtro = texto.replace("empecé", "").replace("empece", "").replace("arranqué", "").replace("arranque", "").replace("progreso", "").replace("estoy con", "").replace("la tarea", "").replace("de", "").strip()
            tarea = actualizar_estado_tarea(filtro, persona_remitente, "En progreso")
            if tarea:
                bot.reply_to(message, f"🚀 ¡Bien ahí, {persona_remitente}! Pasé la tarea *'{tarea}'* a *En progreso* en Notion.")
            else:
                bot.reply_to(message, "No encontré esa tarea activa asignada a vos.")
            return

        # --- ATAJO: LISTO / COMPLETADO ---
        elif any(x in texto for x in ["listo", "terminé", "termine"]):
            filtro = texto.replace("listo", "").replace("terminé", "").replace("termine", "").replace("la tarea", "").replace("de", "").strip()
            tarea = actualizar_estado_tarea(filtro, persona_remitente, "Listo")
            if tarea:
                bot.reply_to(message, f"🎉 ¡Buen trabajo, {persona_remitente}! Marqué la tarea *'{tarea}'* como *Listo* en Notion.")
            else:
                bot.reply_to(message, "No encontré esa tarea asignada a vos.")
            return

    # 2. LÓGICA DE EMILIANO (Asignación o conversación normal)
    if is_private or is_mentioned:
        clean_text = message.text.replace(f"@{BOT_USERNAME}", "").strip() if BOT_USERNAME else message.text.strip()
        if not clean_text:
            bot.reply_to(message, "¡Hola! ¿En qué puedo ayudarte hoy?")
            return
        
        if usuario_id != ADMIN_TELEGRAM_ID:
            bot.reply_to(message, "Lo siento, solo Emiliano tiene permisos de administración.")
            return

        try:
            respuesta_ai = consultar_gemini(clean_text)
            
            # Caso Calendar
            if respuesta_ai.startswith("AGENDAR|"):
                partes = respuesta_ai.split("|")
                if len(partes) >= 5:
                    resultado = agendar_evento_google(partes[1], partes[2], partes[3], partes[4])
                    bot.reply_to(message, resultado)
                else:
                    bot.reply_to(message, "No pude procesar los datos para el calendario.")
            
            # Caso Notion
            elif respuesta_ai.startswith("NOTION|"):
                partes = respuesta_ai.split("|")
                if len(partes) >= 5:
                    tarea = partes[1]
                    persona = partes[2]
                    plazo_raw = partes[3]
                    prioridad = partes[4]
                    
                    plazo = None if plazo_raw == "None" else plazo_raw
                    
                    if agregar_tarea_notion_completa(tarea, persona, plazo, prioridad):
                        notificado = enviar_alerta_telegram(persona, tarea, plazo, prioridad)
                        aviso = f"¡Excelente! Anoté en Notion: '{tarea}' asignada a {persona} con prioridad *{prioridad}*. 📝"
                        if plazo:
                            aviso += f" Plazo: {plazo}."
                        if notificado:
                            aviso += f"\n💬 Ya le envié la notificación privada a su Telegram."
                        else:
                            aviso += f"\n⚠️ No se pudo enviar mensaje por Telegram (¿ID cargado y chat iniciado?)."
                        bot.reply_to(message, aviso)
                    else:
                        bot.reply_to(message, "No pude guardar la tarea en Notion.")
                else:
                    bot.reply_to(message, "Formato de tarea incorrecto.")
            
            # Conversación normal
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
    print(f"Servidor web escuchando en el puerto {port}...")
    server.serve_forever()

server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()

print("Bot final encendido...")
bot.infinity_polling()
