import os
import requests
import telebot

# Las credenciales las leeremos de forma segura en Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

SYSTEM_INSTRUCTION = (
    "Eres el asistente virtual oficial de 'Colussi Audiovisuales', una productora audiovisual de Argentina. "
    "Tu objetivo es ayudar a Emiliano (el dueño) y el resto del equipo (5 personas en total) "
    "a organizarse, coordinar rodajes, redactar ideas y gestionar tareas cotidianas de forma prolija, amigable y muy profesional."
)

def consultar_gemini(prompt_usuario):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    # Pasamos la instrucción del sistema como un rol de sistema antes del mensaje del usuario
    data = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"Instrucciones del sistema: {SYSTEM_INSTRUCTION}\n\nMensaje del usuario: {prompt_usuario}"}]
            }
        ],
        "generationConfig": {
            "temperature": 0.7
        }
    }
    
    response = requests.post(url, json=data, headers=headers)
    
    if response.status_code == 200:
        json_response = response.json()
        try:
            return json_response['candidates'][0]['content']['parts'][0]['text']
        except (KeyError, IndexError):
            return "Error al procesar la respuesta del modelo."
    else:
        return f"Error de conexión con Google (Código {response.status_code}):\n{response.text}"
        
        

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "¡Hola! Soy el Asistente de Colussi Audiovisuales. 🎬\n\n"
        "Estoy listo para ayudarte a ti y a todo el equipo a organizar tareas, "
        "armar listas de equipos o estructurar ideas para rodajes.\n\n"
        "En grupos, solo mencióname para que pueda responderte."
    )
    bot.reply_to(message, welcome_text)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    is_private = message.chat.type == "private"
    bot_username = bot.get_me().username
    is_mentioned = bot_username in message.text if message.text else False

    if is_private or is_mentioned:
        clean_text = message.text.replace(f"@{bot_username}", "").strip()
        if not clean_text:
            bot.reply_to(message, "¡Hola! ¿En qué puedo ayudarte hoy?")
            return
        try:
            respuesta_ai = consultar_gemini(clean_text)
            bot.reply_to(message, respuesta_ai)
        except Exception as e:
            bot.reply_to(message, f"Error inesperado:\n{str(e)}")

print("Bot Colussi Audiovisuales encendido de forma directa en Render...")
bot.infinity_polling()
