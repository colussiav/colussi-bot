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
    "Eres 'COLU', el asistente virtual oficial de 'Colussi Audiovisuales'. "
    "Tu misión es facilitar la gestión del estudio para Emi, Delfi, Renzo, Santi y Ari. "
    "Conoces a la perfección el rubro audiovisual (cámaras, iluminación, postproducción, flujos de trabajo).\n\n"
    "REGLA DE FORMATO ABSOLUTA:\n"
    "Si el usuario te solicita CREAR una tarea nueva, debes responder ÚNICA Y EXCLUSIVAMENTE con el formato estructurado, "
    "sin saludos, sin introducciones, sin texto antes ni después. El formato debe ser exactamente:\n"
    "NOTION|Titulo de la tarea|PersonaAsignada|YYYY-MM-DD|Prioridad\n"
    "PersonaAsignada debe ser exactamente: Emi, Delfi, Renzo, Santi o Ari. Si no hay fecha, pon 'None'.\n\n"
    "Si el usuario solo te está charlando o haciendo una pregunta que no requiere crear una tarea en Notion, "
    "responde de forma clara, concisa, profesional y directa en texto normal, sin incluir jamás la palabra 'NOTION' ni barras '|'."
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
    
    if fecha_plazo and str(fecha_plazo).strip().lower() != "none" and str(fecha_plazo).strip() != "":
        properties["Plazo"] = {"date": {"start": fecha_plazo.strip()}}
        
    data = {"parent": {"database_id": NOTION_DATABASE_ID}, "properties": properties}
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            return True
        else:
            print(f"Error de Notion API: {response.status_code} - {response.text}")
            if "Plazo" in properties:
                del properties["Plazo"]
                data_rescate = {"parent": {"database_id": NOTION_DATABASE_ID}, "properties": properties}
                response_rescate = requests.post(url, json=data_rescate, headers=headers)
                return response_rescate.status_code == 200
            return False
    except Exception as e:
        print(f"Error de conexión con Notion: {e}")
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

# --- NOTION: OBTENER REALIZADAS / FINALIZADAS ---
def obtener_realizadas_notion(persona_filtro=None):
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    filter_data = {
        "filter": {
            "property": "Estado",
            "status": {"equals": "Listo"}
        }
    }
    
    try:
        response = requests.post(url, json=filter_data, headers=headers)
        if response.status_code != 200: return {}
        resultados = response.json().get("results", [])
        realizadas_por_persona = {}
        
        for pagina in resultados:
            propiedades = pagina.get("properties", {})
            titulo_data = propiedades.get("Nombre de la tarea", {}).get("title", [])
            nombre_tarea = titulo_data[0].get("text", {}).get("content", "Tarea sin nombre") if titulo_data else "Tarea sin nombre"
            persona = propiedades.get("Asignado", {}).get("select", {}).get("name") or "Sin Asignar"
            
            if persona_filtro and persona != persona_filtro:
                continue
                
            if persona not in realizadas_por_persona:
                realizadas_por_persona[persona] = []
            realizadas_por_persona[persona].append(nombre_tarea)
            
        return realizadas_por_persona
    except Exception as e:
        print(f"Error Query Realizadas: {e}")
        return {}

# --- NOTION: ENVIAR REPORTE MATUTINO AUTOMÁTICO (SOLO ADMIN) ---
def enviar_reporte_matutino_automatico():
    pendientes = obtener_pendientes_notion()
    if not pendientes:
        try: bot.send_message(ADMIN_TELEGRAM_ID, "🌅 *¡Buen día Emi!* Todo al día. No hay tareas pendientes en la productora.")
        except: pass
        return True
        
    mensaje = "🌅 *COLU - Reporte Matutino General:*\n\n"
    for pers, bloques in pendientes.items():
        mensaje += f"👤 *{pers}:*\n"
        if bloques["en_progreso"]: mensaje += "   ⏳ *En progreso:*\n" + "\n".join([f"     🔹 {t}" for t in bloques["en_progreso"]]) + "\n"
        if bloques["sin_empezar"]: mensaje += "   💤 *Sin empezar:*\n" + "\n".join([f"     🔹 {t}" for t in bloques["sin_empezar"]]) + "\n"
        mensaje += "\n"
    try:
        bot.send_message(ADMIN_TELEGRAM_ID, mensaje, parse_mode="Markdown")
        return True
    except Exception as e:
        print(f"Error sending morning report: {e}")
        return False
        
# --- NOTION: ENVIAR REPORTE PERSONALIZADO A CADA INTEGRANTE ---
def forzar_reporte_masivo_equipo():
    pendientes = obtener_pendientes_notion()
    if not pendientes:
        try: bot.send_message(ADMIN_TELEGRAM_ID, "📋 Intenté mandar el reporte masivo, pero no hay tareas pendientes en toda la productora.")
        except: pass
        return True
        
    for persona, telegram_id in TELEGRAM_IDS.items():
        if not telegram_id: continue
        
        bloques = pendientes.get(persona)
        if not bloques or (not bloques["sin_empezar"] and not bloques["en_progreso"]):
            mensaje = f"📝 *¡Hola {persona}!* 🎬\n\nCOLU te reporta que estás al día. ¡Excelente labor! No tenés tareas pendientes en Notion."
        else:
            mensaje = f"📝 *¡Hola {persona}!* 🎬\n\nCOLU te reporta tus tareas pendientes actuales en Notion:\n\n"
            if bloques["en_progreso"]: 
                mensaje += "⏳ *EN PROGRESO:*\n" + "\n".join([f"  🔹 {t}" for t in bloques["en_progreso"]]) + "\n\n"
            if bloques["sin_empezar"]: 
                mensaje += "💤 *SIN EMPEZAR:*\n" + "\n".join([f"  🔹 {t}" for t in bloques["sin_empezar"]]) + "\n\n"
        
        try:
            bot.send_message(telegram_id, mensaje, parse_mode="Markdown")
        except Exception as e:
            print(f"No se pudo enviar el reporte individual a {persona}: {e}")
            
    return True

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

# --- NOTION: APLICAR CAMBIO DE ESTADO ---
def aplicar_estado_por_id(page_id, nuevo_estado):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {"Authorization": f"Bearer {NOTION_API_KEY}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}
    update_data = {"properties": {"Estado": {"status": {"name": nuevo_estado}}}}
    try:
        res = requests.patch(url, json=update_data, headers=headers)
        return res.status_code == 200
    except Exception as e:
        print(f"Error al cambiar estado en Notion: {e}")
        return False

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
    if fecha_plazo and str(fecha_plazo).strip().lower() != "none" and str(fecha_plazo).strip() != "": 
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
                    f"Hoy es {fecha_actual_str} (Argentina).\n"
                    f"Mensaje de {nombre_emisor}: {prompt_usuario}"
                )}]
            }
        ],
        "generationConfig": {"temperature": 0.1}
    }
    try:
        res = requests.post(url, json=data, headers=headers)
        if res.status_code == 200: 
            return res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f"Error Gemini: {e}")
    return "Disculpe, Señor. Tuve un inconveniente al procesar la solicitud."

# --- PROCESAMIENTO DE AUDIO ---
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
                    {"text": "Transcribe este audio de voz a texto de forma exacta, literal y limpia sin comentarios adicionales."}
                ]
            }
        ],
        "generationConfig": {"temperature": 0.0}
    }
    try:
        res = requests.post(url, json=data, headers=headers)
        if res.status_code == 200: return res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f"Error STT: {e}")
    return None

# --- EVALUADOR DE COMANDOS DIRECTOS DE NOTION (FLEXIBILIZADO Y CON REALIZADAS) ---
def ejecutar_comando_notion(texto, persona_remitente, message):
    texto_lower = texto.lower().strip()
    
    # 1. COMANDO MASIVO PARA TODO EL EQUIPO (Solo Emi)
    if any(x in texto_lower for x in ["enviar reporte matutino", "mandar reporte", "enviar reporte general", "reporte masivo"]):
        if persona_remitente != "Emi":
            bot.reply_to(message, "Acceso denegado. Solo Emi puede forzar el reporte del equipo.")
            return True
        
        bot.reply_to(message, "⏳ Procesando y enviando los reportes personalizados a cada miembro del equipo...")
        exito = forzar_reporte_masivo_equipo()
        if exito:
            bot.send_message(message.chat.id, "✅ Reportes individuales enviados a todo el equipo con éxito.")
        else:
            bot.send_message(message.chat.id, "❌ Hubo un error al intentar despachar los reportes.")
        return True

    # 2. DETECTOR DE TAREAS REALIZADAS / FINALIZADAS / COMPLETADAS
    palabras_realizadas = ["realizada", "realizadas", "terminada", "terminadas", "completada", "completadas", "finalizada", "finalizadas", "listo", "hecho"]
    es_consulta_realizadas = any(p in texto_lower for p in palabras_realizadas) and ("que" in texto_lower or "mis" in texto_lower or "cuales" in texto_lower or "ver" in texto_lower or "tarea" in texto_lower or "tareas" in texto_lower)
    
    if es_consulta_realizadas:
        es_general = persona_remitente in ["Emi", "Delfi"] and ("equipo" in texto_lower or "todas" in texto_lower or "general" in texto_lower)
        persona_filtro = None if es_general else persona_remitente
        
        realizadas = obtener_realizadas_notion(persona_filtro)
        
        if not realizadas:
            bot.reply_to(message, "🎉 No encontré tareas con estado 'Listo' registradas en Notion.")
            return True
            
        mensaje = "🎉 *Listado de Tareas Realizadas (Listo):*\n\n"
        for pers, lista_tareas in realizadas.items():
            mensaje += f"👤 *{pers}:*\n"
            mensaje += "\n".join([f"  ✅ {t}" for t in lista_tareas]) + "\n\n"
            
        bot.send_message(message.chat.id, mensaje, parse_mode="Markdown")
        return True

    # 3. REPORTE GENERAL PENDIENTE EN UN SOLO CHAT (Admins)
    if any(x in texto_lower for x in ["reporte general", "como venimos equipo", "todas las tareas equipo", "tareas tiene el equipo"]):
        if persona_remitente not in ["Emi", "Delfi"]:
            bot.reply_to(message, "Acceso denegado. No posees permisos de administración.")
            return True
        pendientes = obtener_pendientes_notion()
        if not pendientes:
            bot.reply_to(message, "Excelente. No hay tareas pendientes en toda la productora.")
            return True
        mensaje = "📋 *Estado General de Production - Colussi AV:*\n\n"
        for pers, bloques in pendientes.items():
            mensaje += f"👤 *{pers}:*\n"
            if bloques["en_progreso"]: mensaje += "   ⏳ *En progreso:*\n" + "\n".join([f"     🔹 {t}" for t in bloques["en_progreso"]]) + "\n"
            if bloques["sin_empezar"]: mensaje += "   💤 *Sin empezar:*\n" + "\n".join([f"     🔹 {t}" for t in bloques["sin_empezar"]]) + "\n"
            mensaje += "\n"
        bot.send_message(message.chat.id, mensaje, parse_mode="Markdown")
        return True

    # 4. MIS TAREAS INDIVIDUALES PENDIENTES (Detección ultra-flexible)
    palabras_tarea = ["tarea", "tareas", "pendiente", "pendientes", "hacer", "tengo que"]
    es_consulta_personal = ("que" in texto_lower or "mis" in texto_lower or "cuales" in texto_lower or "tengo" in texto_lower) and any(p in texto_lower for p in palabras_tarea)
    
    if es_consulta_personal:
        pendientes = obtener_pendientes_notion()
        bloques = pendientes.get(persona_remitente)
        
        if not bloques or (not bloques["sin_empezar"] and not bloques["en_progreso"]):
            bot.reply_to(message, f"¡Estás al día, {persona_remitente}! Excelente labor.")
            return True
            
        mensaje = f"📝 *Tareas pendientes para {persona_remitente}:*\n\n"
        if bloques["en_progreso"]: mensaje += "⏳ *EN PROGRESO:*\n" + "\n".join([f"  🔹 {t}" for t in bloques["en_progreso"]]) + "\n\n"
        if bloques["sin_empezar"]: mensaje += "💤 *SIN EMPEZAR:*\n" + "\n".join([f"  🔹 {t}" for t in bloques["sin_empezar"]]) + "\n\n"
        
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            telebot.types.InlineKeyboardButton("✅ Finalizar tarea", callback_data="menu_finalizar"),
            telebot.types.InlineKeyboardButton("⚡ Empezar tarea", callback_data="menu_empezar")
        )
        
        bot.send_message(message.chat.id, mensaje, parse_mode="Markdown", reply_markup=markup)
        return True

    if procesar_cambio_estado(texto_lower, persona_remitente, message):
        return True
    return False

# --- CAPTURADOR DE BOTONES INTERACTIVOS MENÚ PRINCIPAL ---
@bot.callback_query_handler(func=lambda call: call.data in ["menu_finalizar", "menu_empezar"])
def manejar_menu_tareas(call):
    usuario_id = call.from_user.id
    persona_remitente = next((k for k, v in TELEGRAM_IDS.items() if v and int(v) == usuario_id), None)
    
    if not persona_remitente:
        bot.answer_callback_query(call.id, "No estás registrado en el sistema.")
        return

    estado_buscado = "En progreso" if call.data == "menu_finalizar" else "Sin empezar"
    emoji_accion = "⏳" if call.data == "menu_finalizar" else "🎬"
    prefijo_callback = "fin_" if call.data == "menu_finalizar" else "emp_"
    texto_cons = "Buscando tareas en progreso..." if call.data == "menu_finalizar" else "Consultando Notion..."

    bot.answer_callback_query(call.id, texto_cons)
    
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    filter_data = {
        "filter": {
            "and": [
                {"property": "Asignado", "select": {"equals": persona_remitente}},
                {"property": "Estado", "status": {"equals": estado_buscado}}
            ]
        }
    }
    
    try:
        response = requests.post(url, json=filter_data, headers=headers)
        if response.status_code != 200:
            bot.send_message(call.message.chat.id, "❌ Error al conectar con Notion.")
            return
            
        resultados = response.json().get("results", [])
        if not resultados:
            msg_vacio = "No tenés tareas 'En progreso' para finalizar." if call.data == "menu_finalizar" else "No tenés tareas asignadas 'Sin empezar' en este momento."
            bot.send_message(call.message.chat.id, f"🎉 {msg_vacio}")
            return
            
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        for pagina in resultados:
            page_id = pagina.get("id")
            titulo_data = pagina.get("properties", {}).get("Nombre de la tarea", {}).get("title", [])
            titulo = titulo_data[0].get("text", {}).get("content", "Tarea sin nombre") if titulo_data else "Tarea sin nombre"
            
            callback_data = f"{prefijo_callback}{page_id[:20]}"
            markup.add(telebot.types.InlineKeyboardButton(titulo, callback_data=callback_data))
            
        texto_instruccion = f"{emoji_accion} *{persona_remitente}*, seleccioná qué tarea vas a marcar como completada:" if call.data == "menu_finalizar" else f"🎬 *{persona_remitente}*, seleccioná qué tarea vas a ver:"
        bot.send_message(call.message.chat.id, texto_instruccion, parse_mode="Markdown", reply_markup=markup)
        
    except Exception as e:
        print(f"Error al desplegar menú de tareas: {e}")
        bot.send_message(call.message.chat.id, "❌ Ocurrió un inconveniente al procesar tus tareas.")

# --- CAPTURADOR PARA CUANDO SE SELECCIONA UNA TAREA ESPECÍFICA, ACTIVACIÓN O FINALIZACIÓN ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("emp_") or call.data.startswith("fin_") or call.data.startswith("act_"))
def manejar_seleccion_tarea(call):
    usuario_id = call.from_user.id
    persona_remitente = next((k for k, v in TELEGRAM_IDS.items() if v and int(v) == usuario_id), None)
    
    if not persona_remitente:
        bot.answer_callback_query(call.id, "No estás registrado.")
        return

    id_truncado = call.data.replace("fin_", "").replace("emp_", "").replace("act_", "")
    
    url_base = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    try:
        if call.data.startswith("act_"):
            bot.answer_callback_query(call.id, "Iniciando tarea en Notion...")
            response = requests.post(url_base, headers=headers)
            resultados = response.json().get("results", [])
            pagina_encontrada = next((p for p in resultados if p.get("id", "").startswith(id_truncado)), None)
            
            if pagina_encontrada:
                page_id_real = pagina_encontrada.get("id")
                titulo_data = pagina_encontrada.get("properties", {}).get("Nombre de la tarea", {}).get("title", [])
                titulo_tarea = titulo_data[0].get("text", {}).get("content", "Tarea sin nombre") if titulo_data else "Tarea sin nombre"
                
                if aplicar_estado_por_id(page_id_real, "En progreso"):
                    bot.send_message(call.message.chat.id, f"🚀 ¡Tarea *'{titulo_tarea}'* pasada a *En progreso*! A darle átomos. 🎬", parse_mode="Markdown")
                    notificar_cambio_a_emiliano(persona_remitente, titulo_tarea, "En progreso")
                else:
                    bot.send_message(call.message.chat.id, "❌ No se pudo cambiar el estado en Notion.")
            else:
                bot.send_message(call.message.chat.id, "❌ No se localizó la tarea para iniciar.")
            return

        bot.answer_callback_query(call.id, "Buscando datos en Notion...")
        response = requests.post(url_base, headers=headers)
        if response.status_code != 200:
            bot.send_message(call.message.chat.id, "❌ Error al conectar con Notion.")
            return

        resultados = response.json().get("results", [])
        pagina_encontrada = next((p for p in resultados if p.get("id", "").startswith(id_truncado)), None)

        if not pagina_encontrada:
            bot.send_message(call.message.chat.id, "❌ No se encontró la tarea seleccionada en Notion.")
            return

        page_id_real = pagina_encontrada.get("id")
        propiedades = pagina_encontrada.get("properties", {})
        titulo_data = propiedades.get("Nombre de la tarea", {}).get("title", [])
        titulo_tarea = titulo_data[0].get("text", {}).get("content", "Tarea sin nombre") if titulo_data else "Tarea sin nombre"

        if call.data.startswith("fin_"):
            if aplicar_estado_por_id(page_id_real, "Listo"):
                bot.send_message(call.message.chat.id, f"🎉 ¡Excelente! La tarea *'{titulo_tarea}'* ha sido marcada como *Listo* en Notion.", parse_mode="Markdown")
                notificar_cambio_a_emiliano(persona_remitente, titulo_tarea, "Listo")
            else:
                bot.send_message(call.message.chat.id, "❌ No se pudo cambiar el estado a Listo.")
        
        elif call.data.startswith("emp_"):
            archivos_data = propiedades.get("Adjuntar archivo", {}).get("files", [])
            link_drive = None
            if archivos_data:
                link_drive = archivos_data[0].get("external", {}).get("url") or archivos_data[0].get("file", {}).get("url")

            descripcion = ""
            
            mensaje_detalle = f"📋 *FICHA DE VISTA PREVIA*\n\n📌 *Título:* {titulo_tarea}\n"
            if descripcion:
                mensaje_detalle += f"📝 *Descripción:* {descripcion}\n"
            if link_drive:
                mensaje_detalle += f"🔗 *Material (Drive):* [Abrir enlace]({link_drive})\n"
            if not descripcion and not link_drive:
                mensaje_detalle += f"\nℹ️ _Esta tarea no incluye descripción adicional ni archivos adjuntos._\n"

            markup_arrancar = telebot.types.InlineKeyboardMarkup(row_width=1)
            markup_arrancar.add(telebot.types.InlineKeyboardButton("🚀 Empezar esta tarea", callback_data=f"act_{id_truncado}"))

            bot.send_message(call.message.chat.id, mensaje_detalle, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=markup_arrancar)

    except Exception as e:
        print(f"Error en la selección de tarea: {e}")
        bot.send_message(call.message.chat.id, "❌ Ocurrió un error al procesar la solicitud.")

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
        
        print(f"Audio transcrito de {persona_remitente}: '{texto_transcrito}'")
        
        if ejecutar_comando_notion(texto_transcrito, persona_remitente, message): 
            return
        
        respuesta_ai = consultar_gemini(texto_transcrito, persona_remitente)
        if "NOTION|" in respuesta_ai:
            if not respuesta_ai.startswith("NOTION|"):
                respuesta_ai = "NOTION|" + respuesta_ai.split("NOTION|")[1]
            
            partes = respuesta_ai.split("|")
            tarea, persona, plazo_raw, prioridad = partes[1], partes[2], partes[3], partes[4]
            plazo = None if str(plazo_raw).strip().lower() == "none" else plazo_raw
            if agregar_tarea_notion_completa(tarea, persona, plazo, prioridad):
                enviar_alerta_telegram(persona, tarea, plazo, prioridad)
                bot.reply_to(message, f"✅ He registrado la tarea '{tarea}' para {persona} en Notion.")
            else:
                bot.reply_to(message, "❌ Hubo un problema al intentar impactar la tarea en la base de datos de Notion. Revisa el mapeo de columnas.")
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
        if "NOTION|" in respuesta_ai:
            if persona_remitente not in ["Emi", "Delfi"]:
                bot.reply_to(message, "Acceso denegado para modificar la base de datos.")
                return
            
            if not respuesta_ai.startswith("NOTION|"):
                respuesta_ai = "NOTION|" + respuesta_ai.split("NOTION|")[1]
                
            partes = respuesta_ai.split("|")
            tarea, persona, plazo_raw, prioridad = partes[1], partes[2], partes[3], partes[4]
            plazo = None if str(plazo_raw).strip().lower() == "none" else plazo_raw
            if agregar_tarea_notion_completa(tarea, persona, plazo, prioridad):
                enviar_alerta_telegram(persona, tarea, plazo, prioridad)
                bot.reply_to(message, f"✅ He registrado la tarea '{tarea}' para {persona} en Notion.")
            else:
                bot.reply_to(message, "❌ Hubo un problema al intentar crear la tarea en Notion. Verifica que las columnas coincidan.")
        else:
            bot.reply_to(message, respuesta_ai)
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

def procesar_cambio_estado(texto, persona_remitente, message):
    nuevo_estado = None
    if any(x in texto for x in ["empecé", "empece", "arranqué", "arranque", "progreso", "estoy con"]): nuevo_estado = "En progreso"
    elif any(x in texto for x in ["listo", "terminé", "termine", "finalizada", "finalizadas"]): nuevo_estado = "Listo"
    if not nuevo_estado: return False
    
    filtro = texto.replace("empecé", "").replace("empece", "").replace("arranqué", "").replace("arranque", "").replace("progreso", "").replace("estoy con", "").replace("la tarea", "").replace("de", "").replace("finalizada", "").replace("finalizadas", "").replace("lista", "").strip()
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

# --- SERVIDOR WEB CON WEBHOOK PARA REPORTES MATUTINOS ---
class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ["/", "", "/index.html"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"COLU Engine Online.")
        elif self.path == "/morning-report":
            print("Activando reporte matutino individual para el equipo y general para el admin...")
            # 1. Envía el reporte individual personalizado a cada integrante de la productora
            exito_masivo = forzar_reporte_masivo_equipo()
            # 2. Te envía el reporte matutino general a vos como administrador
            exito_admin = enviar_reporte_matutino_automatico()
            
            if exito_masivo or exito_admin:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Reportes matutinos despachados correctamente.")
            else:
                self.send_response(500)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Error al procesar los reportes.")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return

def run_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), WebhookHandler).serve_forever()

threading.Thread(target=run_server, daemon=True).start()
bot.infinity_polling()
