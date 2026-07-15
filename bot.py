import os
import requests
import telebot

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
ADMIN_TELEGRAM_ID = 8802307065

bot = telebot.TeleBot(TELEGRAM_TOKEN)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.from_user.id != ADMIN_TELEGRAM_ID:
        return

    # Consultamos a Notion qué bases de datos ve el bot
    url = "https://api.notion.com/v1/search"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    data = {
        "filter": {
            "value": "database",
            "property": "object"
        }
    }
    
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            resultados = response.json().get("results", [])
            if not resultados:
                bot.reply_to(message, "El bot está conectado, pero no encuentra ninguna base de datos. ¿Le diste permiso de conexión a la página?")
                return
            
            respuesta = "¡Encontré estas bases de datos en tu Notion! 🎉\n\n"
            for db in resultados:
                titulo = db.get("title", [{}])[0].get("plain_text", "Sin título")
                db_id = db.get("id").replace("-", "")
                respuesta += f"📌 **Nombre:** {titulo}\n🔑 **ID de base de datos:** `{db_id}`\n\n"
            
            respuesta += "Copiá el ID de la que se llama 'Tareas Colussi AV' y ponelo en Render."
            bot.reply_to(message, respuesta)
        else:
            bot.reply_to(message, f"Error al conectar con Notion (Código {response.status_code}):\n{response.text}")
    except Exception as e:
        bot.reply_to(message, f"Hubo un problema: {str(e)}")

print("Bot de diagnóstico encendido...")
bot.infinity_polling()
