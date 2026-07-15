import os
import requests
import telebot
import json
import datetime
from datetime import timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Credenciales de Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")

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
    # Nota: Como Google te desactivó las credenciales anteriores por seguridad,
    # luego configuraremos una nueva clave limpia desde Render. Por ahora evitamos que tire error al iniciar.
    return None

def agendar_evento_google(titulo, inicio_iso, fin_iso, descripcion=""):
    return "La integración de Google Calendar requiere configurar una nueva clave privada segura en Render."

# --- FUNCIÓN NOTION SIMPLIFICADA DE DIAGNÓSTICO ---
def agregar_tarea_notion(nombre_tarea, persona):
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    data = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Nombre de la tarea": {
                "title": [
                    {
                        "text": {
                            "content": nombre_tarea
                        }
                    }
                ]
            },
            "Asignado": {
                "select": {
                    "name": persona
                }
            }
        }
    }
    try:
        response = requests.post(url, json=data, headers=headers)
        print(f"DEBUG NOTION - Status Code: {response.status_code}")
        print(f"DEBUG NOTION - Respuesta Completa: {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"DEBUG NOTION - Error de conexión: {e}")
        return False

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
                    "NOTION|Titulo de la tarea|PersonaAsignada\n"
                    "Ejemplo: NOTION|Enviar presupuesto a Garibaldi|Delfi\n"
                    "Nota: 'PersonaAsignada' debe ser estrictamente uno de estos nombres (con la primera letra en mayúscula): Emi, Delfi, Renzo, Santi o Ari.\n\n"
                    "Si no pide agendar ni registrar tareas, responde como tu amigable asistente virtual normalmente.\n\n"
                    f"Mensaje del usuario: {prompt_usuario}"
                )}]
            }
        ],
        "generationConfig": {"temperature": 0.3}
    }
    
    response = requests.post(url, json=data, headers=headers)
    if response.status_code == 200:
        try:
            return response.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        except (KeyError, IndexError):
            return "Error al procesar la respuesta del modelo."
    else:
        return f"Error de conexión (Código {response.status_code}): {response.text}"

# --- MANEJADORES DE TELEGRAM ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "¡Asistente listo y conectado con Notion! 🎬📝")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    usuario_id = message.from_user.id
    is_private = message.chat.type == "private"
    is_mentioned = BOT_USERNAME in message.text if (message.text and BOT_USERNAME) else False

    if is_private or is_mentioned:
        clean_text = message.text.replace(f"@{BOT_USERNAME}", "").strip() if BOT_USERNAME else message.text.strip()
        if not clean_text:
            bot.reply_to(message, "¡Hola! ¿En qué puedo ayudarte hoy?")
            return
        
        if usuario_id != ADMIN_TELEGRAM_ID:
            bot.reply_to(message, "Lo siento, solo Emiliano tiene permisos para modificar la agenda.")
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
                if len(partes) >= 3:
                    tarea = partes[1]
                    persona = partes[2]
                    
                    if agregar_tarea_notion(tarea, persona):
                        bot.reply_to(message, f"¡Excelente! Anoté en Notion: '{tarea}' asignada a {persona}. 📝")
                    else:
                        bot.reply_to(message, "No pude guardar la tarea en Notion. Verificá los permisos del bot.")
                else:
                    bot.reply_to(message, "Formato de tarea incorrecto.")
            
            # Conversación normal
            else:
                bot.reply_to(message, respuesta_ai)
                
        except Exception as e:
            bot.reply_to(message, f"Error: {str(e)}")

print("Bot final encendido...")
bot.infinity_polling()
