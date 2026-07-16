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

ADMIN_TELEGRAM_ID = 8802307065
bot = telebot.TeleBot(TELEGRAM_TOKEN)

try:
    BOT_USERNAME = bot.get_me().username
except:
    BOT_USERNAME = ""

# --- FUNCIONES NOTION ---
def agregar_tarea_notion_completa(nombre_tarea, persona, fecha_plazo=None, prioridad="Medio"):
    url = "https://api.notion.com/v1/pages"
    headers = {"Authorization": f"Bearer {NOTION_API_KEY}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}
    properties = {
        "Nombre de la tarea": {"title": [{"text": {"content": nombre_tarea}}]},
        "Asignado": {"select": {"name": persona}},
        "Estado": {"status": {"name": "Sin empezar"}},
        "Prioridad": {"select": {"name": prioridad}}
    }
    if fecha_plazo: properties["Plazo"] = {"date": {"start": fecha_plazo}}
    response = requests.post(url, json={"parent": {"database_id": NOTION_DATABASE_ID}, "properties": properties}, headers=headers)
    return response.status_code == 200

def actualizar_estado_tarea(nombre_tarea_aproximado, persona_name, nuevo_estado):
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {"Authorization": f"Bearer {NOTION_API_KEY}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}
    
    # Buscamos tareas no terminadas (si estamos moviendo a en progreso)
    # o cualquier tarea activa
    filter_data = {"filter": {"property": "Asignado", "select": {"equals": persona_name}}}
    
    response = requests.post(url, json=filter_data, headers=headers)
    if response.status_code != 200: return None
    
    resultados = response.json().get("results", [])
    for pagina in resultados:
        propiedades = pagina.get("properties", {})
        titulo_data = propiedades.get("Nombre de la tarea", {}).get("title", [])
        titulo = titulo_data[0].get("text", {}).get("content", "") if titulo_data else ""
        
        if nombre_tarea_aproximado.lower() in titulo.lower() or titulo.lower() in nombre_tarea_aproximado.lower():
            page_id = pagina.get("id")
            update_url = f"https://api.notion.com/v1/pages/{page_id}"
            update_data = {"properties": {"Estado": {"status": {"name": nuevo_estado}}}}
            res_update = requests.patch(update_url, json=update_data, headers=headers)
            if res_update.status_code == 200:
                return titulo
    return None

# --- FUNCIONES REPORTES ---
def obtener_pendientes_notion():
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {"Authorization": f"Bearer {NOTION_API_KEY}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}
    try:
        response = requests.post(url, headers=headers)
        if response.status_code != 200: return {}
        resultados = response.json().get("results", [])
        pendientes_por_persona = {}
        for pagina in resultados:
            propiedades = pagina.get("properties", {})
            estado = propiedades.get("Estado", {}).get("status", {}).get("name", "Sin empezar")
            if estado == "Listo": continue
            titulo = propiedades.get("Nombre de la tarea", {}).get("title", [{}])[0].get("text", {}).get("content", "Tarea")
            persona = propiedades.get("Asignado", {}).get("select", {}).get("name")
            if persona:
                if persona not in pendientes_por_persona: pendientes_por_persona[persona] = {"sin_empezar": [], "en_progreso": []}
                if estado == "En progreso": pendientes_por_persona[persona]["en_progreso"].append(titulo)
                else: pendientes_por_persona[persona]["sin_empezar"].append(titulo)
        return pendientes_por_persona
    except: return {}

def enviar_reporte_matutino():
    pendientes = obtener_pendientes_notion()
    for persona, bloques in pendientes.items():
        telegram_id = TELEGRAM_IDS.get(persona)
        if telegram_id:
            mensaje = f"☕ *¡Buen día, {persona}!* 🎬\n\n"
            if bloques["en_progreso"]:
                mensaje += "⏳ *EN PROGRESO:*\n" + "\n".join([f"  🔹 {t}" for t in bloques["en_progreso"]]) + "\n\n"
            if bloques["sin_empezar"]:
                mensaje += "💤 *SIN EMPEZAR:*\n" + "\n".join([f"  🔹 {t}" for t in bloques["sin_empezar"]]) + "\n\n"
            mensaje += "¡Que tengas una gran jornada! 🚀"
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": telegram_id, "text": mensaje, "parse_mode": "Markdown"})
    return "Reportes enviados."

# --- MANEJADOR DE MENSAJES ---
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    usuario_id = message.from_user.id
    is_private = message.chat.type == "private"
    persona_remitente = next((k for k, v in TELEGRAM_IDS.items() if v and int(v) == usuario_id), None)
    
    # 1. ATAJOS DE EQUIPO (Progreso / Terminado)
    if is_private and persona_remitente:
        texto = message.text.lower()
        # Detectar "En progreso"
        if any(x in texto for x in ["empecé", "empece", "arranqué", "arranque", "progreso", "estoy con"]):
            filtro = texto.replace("empecé", "").replace("empece", "").replace("arranqué", "").replace("arranque", "").replace("progreso", "").replace("estoy con", "").replace("la tarea", "").strip()
            tarea = actualizar_estado_tarea(filtro, persona_remitente, "En progreso")
            if tarea: bot.reply_to(message, f"🚀 ¡Bien ahí {persona_remitente}! Pasé '{tarea}' a *En progreso*.")
            else: bot.reply_to(message, "No encontré esa tarea activa.")
            return

        # Detectar "Listo"
        elif any(x in texto for x in ["listo", "terminé", "termine"]):
            filtro = texto.replace("listo", "").replace("terminé", "").replace("termine", "").replace("la tarea", "").strip()
            tarea = actualizar_estado_tarea(filtro, persona_remitente, "Listo")
            if tarea: bot.reply_to(message, f"🎉 ¡Buen trabajo {persona_remitente}! Marcada como *Listo*: '{tarea}'.")
            else: bot.reply_to(message, "No encontré esa tarea.")
            return

    # 2. LÓGICA DE EMILIANO (Asignación)
    if (is_private or BOT_USERNAME in message.text) and usuario_id == ADMIN_TELEGRAM_ID:
        # ... (aquí mantenes tu lógica actual de consultar_gemini y agregar_tarea_notion_completa) ...
        # (Para no repetirme, asegúrate de mantener el resto del código que ya tenías)
        pass

# ... (El resto del código del servidor y polling igual al anterior)
