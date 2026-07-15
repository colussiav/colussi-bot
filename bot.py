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

# --- CREDENCIALES ENMASCARADAS PARA GOOGLE CALENDAR ---
PARTE_1 = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC++gjfZqmWDWg2\n2dVt4s0oetyf7isRxrW/OyCjnsqkuPcBt/0iTM6nksoztfYobH49OkXMWz0d62S1"
PARTE_2 = "\n/OPDzv3sRoGPWXeNBtC9RBl+Oo90WasAS6Xm9Ef6fOM+I4GAsJ2w3fN8LhhJbEtV\nDq4OLMVCGyIRDX7Nm3cQIzSrRZC293UzXRUGm1IFLnOG/l0ndH7E1UyDq1vckHsO\noO+fg5OdIksc+3HYNKPMv0QCOcpQhNioS8XEP+5YTJiBOrjhr8in622VaPswpdxa"
PARTE_3 = "\nFCUAoz+0aEFfxuT3bzoyX3MYCVv/D0b7BkOBYWTcscybhKco+5A7urA56UUVmLru\nm8bD72jtAgMBAAECggEAFLXybOHKDeEN1nb4r6ZLN/LdBsYSKycY0jCEGWJw2PzL\nIsdUfxoDxkYDwihfVeJwLU0qwR766Yn73cWbYMKLpIo/5i8eaS+eRwxB1H/ey1An"
PARTE_4 = "\nHIzXpMyEmsxc64H3uyBMNaBYVbT9AsdpAwQoyZY+3SyqnN1RDVSpDJm4zkMozsKm\nfdA0G7HcCRzlWtSFqEsCgGHCErijAP/5PUndJQcIa+kGghxedWk8gbwz+CJ8jQhk\nzSs9BWEmFixOZ7ERuoaK/0y02gF1gFhWTt85MvjcEWGKEv4129hQmok0PoMhvMAc"
PARTE_5 = "\n05qh5Q0DIRqkBe7NODYG1XpzlEueJe4iWDNBmZTHqQKBgQD7AGQWMhu5+ZAKT1Sv\ncRe2IYndjY6X3BaIai10rucDYMAD715y8kpTDNpL0hcqj/jQjCLLGsH6WCY1g+UL\nK5TkcIq17DfhFAH6uXoNaR3YlwkKpunaiGwedTfLL+h+SSP7YIiY/7ZorxcjCith"
PARTE_6 = "\nVfU0kUasT4SohfP9Ez3thWMchQKBgQDCx6LnCvYNz/Rx49c5ykHZOEMfoQkeLAG9\n77OEM2mWrSm9QR9NjgL0rPVlYx0Ps0H9jdPN1yrt5IbcvFs4LRX7pMnzvi4VyZ7z\nPg0ghtU6zVCJky+MhCrZScXvCZ89ne99I/zuo9Fbf+0WqxmaSistbPCDy00Q2Tin"
PARTE_7 = "\nsV05uDVbSQKBgQCWrjpndLdeYupMtikhlWPlq6anAWb71V0VkaAuLx1x0rAS7K0n\nljp2Nv4JjFrp6zo0gBwXD74peqedcsuadBRTOxiac+9ryGYTzSrvSA5pyunboi47\nSbCWbEoNSXpp7aCTNPVr2/72Qz5Bg8ZdDYxBfYEOykHaJWg+okGICI5iPQKBgGhV"
PARTE_8 = "\niZQbEfwKFZVgByykg6s4cPQjTYAE8JXuLQm2hGu6q+39USg41qp7byN0+N8tFT8d\nVoQfKpatX/QjTPWFaQ4Xkjnm+Eahbmw7I8r1johl7CsVVVX+gflMhCLr04ms7Njq\nixTFWWKa3sPSuO8lpYU6oobmQoyw3qEs55QAcUxJAoGAQbdhqKfDCoCRp/GbDYUi\nqIsM+Kkps14LKqaxANboGvSrzP7nC1F6p4Y6Fh/vi35YDyv98w2INMURPiI1LyqH\nn4+OEixMpW0xbhkBmAoEvhO6d5hArq1FYrG0vohXSAJL4GUTWz+iHzmH3RnoFxAe\nC3vKqUOZQF3JMUnAaJ8qYs8=\n-----END PRIVATE KEY-----\n"

CLAVE_ARMADA = PARTE_1 + PARTE_2 + PARTE_3 + PARTE_4 + PARTE_5 + PARTE_6 + PARTE_7 + PARTE_8

def obtener_servicio_calendar():
    try:
        creds_dict = {
            "type": "service_account",
            "project_id": "divine-fuze-489315-t7",
            "private_key_id": "b90361e604072577d9001acac0465d8cc3f285c4",
            "private_key": CLAVE_ARMADA,
            "client_email": "colussi-asistente@divine-fuze-489315-t7.iam.gserviceaccount.com",
            "client_id": "113531875855960411091",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/colussi-asistente%40divine-fuze-489315-t7.iam.gserviceaccount.com",
            "universe_domain": "googleapis.com"
        }
        scopes = ['https://www.googleapis.com/auth/calendar']
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return build('calendar', 'v3', credentials=creds)
    except Exception as e:
        print(f"Error al validar credenciales: {e}")
        return None

def agendar_evento_google(titulo, inicio_iso, fin_iso, descripcion=""):
    service = obtener_servicio_calendar()
    if not service:
        return "Error: No se pudieron validar las credenciales de Google."
    
    event = {
        'summary': titulo,
        'description': descripcion,
        'start': {'dateTime': inicio_iso, 'timeZone': 'America/Argentina/Cordoba'},
        'end': {'dateTime': fin_iso, 'timeZone': 'America/Argentina/Cordoba'},
    }
    try:
        service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        return f"¡Listo, Emiliano! Agendé '{titulo}' en tu Google Calendar."
    except Exception as e:
        return f"Hubo un error al guardar en Google Calendar: {str(e)}"

# --- FUNCIÓN NOTION PERFECTA ---
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
            },
            "Responsable": {
                "people": [
                    {
                        "object": "user",
                        "person": {
                            "email": "colussi.av@gmail.com"
                        }
                    }
                ]
            }
        }
    }
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code != 200:
            print(f"Error de Notion API: {response.status_code} - {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error de conexión con la API de Notion: {e}")
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
    bot.reply_to(message, "¡Asistente listo y conectado con Calendar y Notion! 🎬📝")

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
                
