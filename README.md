# 🤖 Bot de Discord 24/7 - Canal de Voz Inmortal con Chat TTS y Voz Latina

Este bot está programado para mantenerse conectado de manera ininterrumpida (**24 horas, 7 días a la semana**) en el canal de voz indicado, protegerse contra desconexiones, saludar con voz latina personalizada y leer el chat de texto para personas sin micrófono.

---

## 📌 Configuración

- **Nombre:** `𝐃𝐄𝐍𝐙𝐄𝐋-𝐗𝐈𝐓💸`
- **Servidor:** `𝑫𝒆𝒏𝒛𝒆𝒍 𝑿𝕿 💵`
- **Canal de Voz Fijado:** Configurable mediante `VOICE_CHANNEL_ID` en variables de entorno.
- **Enlace de Invitación:** Genera el enlace desde el Discord Developer Portal (OAuth2 > URL Generator > Bot + applications.commands).

---

## 🎙️ Funciones de Voz Neuronal Latina (`es-MX-DaliaNeural`)

### 1. 👋 Saludo de Entrada: "Bienvenido Papi [Username]"
Cada vez que CUALQUIER usuario entra al canal de voz `➕ Crear VC`, el bot extrae su nombre limpio (eliminando clanes o fuentes ilegibles) y lo saluda en voz alta con frases como:
- *"Hola [Nombre], bienvenido papi, qué bueno que llegaste a la sala."*
- *"Miren quién llegó... Bienvenido papi [Nombre], ponte cómodo."*
- *"Hola papi [Nombre], bienvenido a Denzel XT. Disfruta la llamada."*
- *"Qué onda [Nombre], bienvenido a la sala más dura. Qué gusto tenerte aquí."*

*(Nota: Las despedidas al salir fueron eliminadas por completo según lo solicitado).*

### 2. 💬 TTS de Chat (Para Personas Sin Micrófono)
Cuando alguien escribe en el chat integrado del canal de voz `➕ Crear VC`:
1. El bot detecta el mensaje automáticamente.
2. Reacciona al mensaje con el emoji 🎙️ para confirmar que fue leído.
3. Lo dice en voz alta en la llamada con la voz latina:
   - *"[Nombre] dice: [Mensaje]"*

> 💡 **Tip Importante:**
> Para que el bot pueda leer todos los mensajes sin necesidad de que lo etiqueten, activa la casilla **MESSAGE CONTENT INTENT** en el portal de desarrolladores:
> 👉 [Activar Message Content Intent en Discord Developer Portal](https://discord.com/developers/applications) (Sección *Bot* -> *Privileged Gateway Intents* -> Guardar cambios).
> Si aún no lo has activado, también lee cualquier mensaje donde lo mencionen (ejemplo: `@DENZEL-XIT hola a todos`).

---

## 🎫 Sistema de Tickets y Tienda de Productos

El bot incluye un sistema interactivo de compras mediante tickets privados:

- **Canal Oficial del Panel:** `TICKET_CHANNEL_ID` (Por defecto: `1527614381314015252`).
- **Publicación Automática:** Al encenderse, el bot comprueba el canal y envía el panel interactivo si no existe.
- **Comando Administrativo:** `/panel_tickets` (permite a los administradores reenviar el panel cuando lo deseen).

### Flujo de Compra:
1. **Menú Desplegable 1 (iOS):**
   - 📱 *Panel de iOS*
   - 🌐 *Proxy de iOS*
2. **Menú Desplegable 2 (PC):**
   - 💻 *Complex de PC*
   - 🔥 *BR Mods*
3. **Botón '🎫 Generar Ticket':**
   - Valida la selección del cliente y previene duplicados.
   - Crea un canal de texto privado exclusivo (`#ticket-{usuario}`).
   - Asigna permisos automáticos al comprador, al bot y a roles de soporte/vendedores/staff.
   - Responde al usuario de forma privada con un enlace directo a su nuevo ticket.
4. **Dentro del Ticket:**
   - Envía el mensaje: *"Por favor espere a que los vendedores respondan."*
   - Muestra los datos del cliente y el producto elegido.
   - Botón rojo **'🔒 Cerrar Ticket'** con confirmación y auto-eliminación en 5 segundos.

---

## 🛡️ Mecanismos de Protección 24/7

1. **Anti-Desconexión (`Anti-Kick`)**: Vuelve a entrar automáticamente en menos de 1 segundo si lo desconectan.
2. **Anti-Movimiento (`Anti-Move`)**: Regresa al canal asignado si lo arrastran a otra sala.
3. **Anti-AFK Continuo**: Emite paquetes de silencio de fondo entre mensajes y saludos para evitar que Discord cierre la llamada por inactividad.
4. **Guardián Watchdog**: Verifica cada 15 segundos la conexión al canal.
5. **Estados Dinámicos**: Cambia su presencia cada 20 segundos automáticamente.

---

## ☁️ Despliegue 24/7 en la Nube (Railway / Render / VPS)

El proyecto incluye `Dockerfile`, `Procfile` y `nixpacks.toml` listos para funcionar sin apagar la PC:

1. **Crear o mantener proyecto en [Railway.app](https://railway.app):**
   - Inicia sesión y selecciona tu servicio conectado al repositorio: [`rafadenzkit3`](https://github.com/purorodriguez903-oss/rafadenzkit3).
2. **Configurar Variables de Entorno en Railway:**
   - Ve a la pestaña **Variables** de tu servicio y asegúrate de tener:
     - `DISCORD_TOKEN` = Tu token secreto de bot.
     - `VOICE_CHANNEL_ID` = `1543395577289777202`
     - `GUILD_ID` = `1387608034641055785`
     - `TICKET_CHANNEL_ID` = `1527614381314015252`
3. **¡Listo!** Cada cambio subido a `rafadenzkit3` se desplegará automáticamente en Railway manteniéndolo activo 24/7.

---

## 🚀 Archivos de Control Local (Windows)

- **Visible:** [iniciar_bot.bat](file:///c:/Users/RafaPlug11/Pictures/DenzerBotDiscord/iniciar_bot.bat)
- **100% Invisible en segundo plano:** [iniciar_oculto.vbs](file:///c:/Users/RafaPlug11/Pictures/DenzerBotDiscord/iniciar_oculto.vbs)
- **Auto-arranque con Windows:** [iniciar_con_windows.bat](file:///c:/Users/RafaPlug11/Pictures/DenzerBotDiscord/iniciar_con_windows.bat)
- **Actualizar avatar/banner:** [actualizar_perfil.bat](file:///c:/Users/RafaPlug11/Pictures/DenzerBotDiscord/actualizar_perfil.bat)
- **Detener el bot:** [detener_bot.bat](file:///c:/Users/RafaPlug11/Pictures/DenzerBotDiscord/detener_bot.bat)
