import os
import requests
import telebot
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Credenciales de Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# CONFIGURACIÓN DE SEGURIDAD (Solo Emiliano tiene acceso al calendario)
ADMIN_TELEGRAM_ID = 8802307065
CALENDAR_ID = "colussi.av@gmail.com"

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Intentamos obtener el username del bot al arrancar
try:
    BOT_USERNAME = bot.get_me().username
except Exception as e:
    print(f"Error al obtener el nombre del bot: {e}")
    BOT_USERNAME = ""

SYSTEM_INSTRUCTION = (
    "Eres el asistente virtual oficial de 'Colussi Audiovisuales', una productora audiovisual de Argentina. "
    "Tu objetivo es ayudar a Emiliano (el dueño) y el resto del equipo (5 personas en total) "
    "a organizarse, coordinar rodajes, redactar ideas y gestionar tareas cotidianas de forma prolija, amigable y muy profesional."
)

# --- CONFIGURACIÓN DE GOOGLE CALENDAR ---
def obtener_servicio_calendar():
    ruta_credenciales = "credentials.json"
    if not os.path.exists(ruta_credenciales):
        return None
    
    scopes = ['https://www.googleapis.com/auth/calendar']
    creds = service_account.Credentials.from_service_account_file(
        ruta_credenciales, scopes=scopes
    )
    return build('calendar', 'v3', credentials=creds)

def agendar_evento_google(titulo, inicio_iso, fin_iso, descripcion=""):
    service = obtener_servicio_calendar()
    if not service:
        return "Error: No se encontró el archivo credentials.json en el servidor."
    
    event = {
        'summary': titulo,
        'description': descripcion,
        'start': {
            'dateTime': inicio_iso,
            'timeZone': 'America/Argentina/Cordoba',
        },
        'end': {
            'dateTime': fin_iso,
            'timeZone': 'America/Argentina/Cordoba',
        },
    }
    
    try:
        service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        return f"¡Listo, Emiliano! Agendé '{titulo}' en tu Google Calendar para esa fecha."
    except Exception as e:
        return f"Hubo un error al intentar guardar en Google Calendar: {str(e)}"

# --- CONEXIÓN CON GEMINI ---
def consultar_gemini(prompt_usuario):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    # Formateamos el prompt para que actúe de intermediario inteligente
    data = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": (
                    f"Instrucciones del sistema: {SYSTEM_INSTRUCTION}\n\n"
                    f"Hoy es {datetime.now().strftime('%Y-%m-%d %H:%M')}.\n"
                    "Si el usuario te está pidiendo agendar un evento, responde EXCLUSIVAMENTE en este formato estructurado para que mi código lo procese:\n"
                    "AGENDAR|Titulo del evento|YYYY-MM-DDTHH:MM:SS|YYYY-MM-DDTHH:MM:SS|Breve descripcion\n"
                    "Ejemplo: AGENDAR|Sesión de fotos|2026-07-14T16:00:00|2026-07-14T17:00:00|Coordinar con Emiliano.\n"
                    "Si el usuario NO está pidiendo agendar algo, responde normalmente con tu personalidad amigable.\n\n"
                    f"Mensaje del usuario: {prompt_usuario}"
                )}]
            }
        ],
        "generationConfig": {
            "temperature": 0.3
        }
    }
    
    response = requests.post(url, json=data, headers=headers)
    if response.status_code == 200:
        try:
            return response.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        except (KeyError, IndexError):
            return "Error al procesar la respuesta del modelo."
    else:
        return f"Error de conexión con Google (Código {response.status_code}):\n{response.text}"       

# --- MANEJADORES DE TELEGRAM ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "¡Hola! Soy el Asistente de Colussi Audiovisuales. 🎬\n\n"
        "Estoy listo para ayudarte a ti y a todo el equipo a organizar tareas, "
        "armar listas de equipos o estructurar ideas para rodajes.\n\n"
        "Emiliano: ya tengo tu ID de administrador configurado de forma segura."
    )
    bot.reply_to(message, welcome_text)

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
        
        # Filtro estricto de seguridad para el calendario
        pide_agendar = any(palabra in clean_text.lower() for palabra in ["agenda", "reunion", "sesion", "rodaje", "grabar", "cita"])
        if pide_agendar and usuario_id != ADMIN_TELEGRAM_ID:
            bot.reply_to(message, "Lo siento, solo Emiliano tiene permisos para modificar o ver la agenda de la productora.")
            return

        try:
            respuesta_ai = consultar_gemini(clean_text)
            
            # Si Gemini detecta que hay que agendar, procesamos la estructura
            if respuesta_ai.startswith("AGENDAR|"):
                partes = respuesta_ai.split("|")
                if len(partes) >= 5:
                    titulo = partes[1]
                    inicio = partes[2]
                    fin = partes[3]
                    desc =  partes[4]
                    
                    resultado = agendar_evento_google(titulo, inicio, fin, desc)
                    bot.reply_to(message, resultado)
                else:
                    bot.reply_to(message, "No pude interpretar correctamente los datos para agendar. ¿Me lo repites?")
            else:
                # Respuesta normal de conversación
                bot.reply_to(message, respuesta_ai)
                
        except Exception as e:
            bot.reply_to(message, f"Error inesperado:\n{str(e)}")

print("Bot Colussi Audiovisuales encendido de forma directa en Render...")
bot.infinity_polling()
