import os
import sys
import re
import time
import random
import socket
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import unicodedata
from typing import Optional
from dotenv import load_dotenv

# Forzar codificación UTF-8 en consolas Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import discord
from discord import app_commands
from discord.ext import tasks
from aiohttp import web
import edge_tts
from gtts import gTTS

# Cargar variables de entorno
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
VOICE_CHANNEL_ID = int(os.getenv("VOICE_CHANNEL_ID", "1543395577289777202"))
TICKET_CHANNEL_ID = int(os.getenv("TICKET_CHANNEL_ID", "1527614381314015252"))
ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("ANNOUNCEMENT_CHANNEL_ID", "1527614353476554762"))
GUILD_ID = int(os.getenv("GUILD_ID", "1387608034641055785"))
PORT = int(os.getenv("PORT", "8080"))

# Configuración de Logging Dual (Consola + Archivo bot.log con rotación)
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.log")
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
console_handler = logging.StreamHandler(sys.stdout)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[file_handler, console_handler]
)
logger = logging.getLogger("Denzer247Bot")

# Cargar librería Opus de discord para Windows
if not discord.opus.is_loaded():
    try:
        bundled_opus = os.path.join(os.path.dirname(discord.__file__), "bin", "libopus-0.x64.dll")
        if os.path.exists(bundled_opus):
            discord.opus.load_opus(bundled_opus)
            logger.info("Librería Opus cargada correctamente.")
    except Exception as e:
        logger.warning(f"Aviso al cargar Opus: {e}")

# Carpeta para archivos temporales de audio
AUDIO_TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_audio")
os.makedirs(AUDIO_TEMP_DIR, exist_ok=True)

# Candado de instancia única local para evitar que se ejecuten 2 bots en la misma máquina
SINGLE_INSTANCE_SOCKET = None
def ensure_single_local_instance(port: int = 49152):
    """Garantiza que solo una instancia del bot corra en esta máquina."""
    global SINGLE_INSTANCE_SOCKET
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', port))
        SINGLE_INSTANCE_SOCKET = s
    except OSError:
        logger.error("❌ ERROR: Ya hay otra instancia de DenzerBot ejecutándose en esta PC.")
        logger.error("   Cierra la otra ventana o ejecuta detener_bot.bat antes de iniciar.")
        sys.exit(1)

def extract_natural_name(member: discord.Member) -> str:
    """
    Limpia y extrae el nombre natural y pronunciable de CUALQUIER usuario.
    Normaliza fuentes góticas/estilizadas y quita clanes/emojis.
    """
    raw_name = member.display_name or member.global_name or member.name or "amigo"

    norm = unicodedata.normalize('NFKC', str(raw_name))
    spaced = re.sub(r'[-$_./\\#@+!*~,;:|()\[\]{}<>]', ' ', norm)
    cleaned = re.sub(r'[^\w\s]', '', spaced)
    words = cleaned.split()

    if not words:
        clean_fallback = re.sub(r'[^\w]', '', unicodedata.normalize('NFKC', member.name))
        return clean_fallback if clean_fallback else "amigo"

    filtered = [w for w in words if len(w) > 1]
    main_name = filtered[0] if filtered else words[0]

    if main_name.lower().endswith('yt') and len(main_name) > 3:
        main_name = main_name[:-2]

    return main_name

def clean_chat_message(content: str) -> str:
    """Limpia el mensaje de texto para que suene fluido al leerse por TTS."""
    text = re.sub(r'<@!?[0-9]+>', '', content)
    text = re.sub(r'<#[0-9]+>', '', text)
    text = re.sub(r'https?://\S+', 'un enlace', text)
    text = re.sub(r'<a?:\w+:\d+>', '', text)
    text = ' '.join(text.split())
    if len(text) > 140:
        text = text[:137] + "..."
    return text.strip()

def format_uptime(seconds: float) -> str:
    """Convierte segundos en formato legible de horas y minutos."""
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"

def is_user_staff_or_owner(member: discord.Member, guild: discord.Guild) -> bool:
    """
    Comprueba si un usuario es Owner, Administrador o posee roles de Staff/Ventas.
    Los compradores normales NO podrán borrar tickets.
    """
    if not isinstance(member, discord.Member):
        return False

    # 1. Es el dueño del servidor (Owner)
    if guild and member.id == guild.owner_id:
        return True

    # 2. Permisos de Administrador o Gestionar Canales
    if member.guild_permissions.administrator or member.guild_permissions.manage_channels:
        return True

    # 3. Roles asignados de Staff, Owner, Admin, Vendedor, Moderador, Soporte
    staff_keywords = [
        "owner", "dueño", "dueña", "creador", "fundador",
        "admin", "administrador", "administradora",
        "staff", "mod", "moderador",
        "vendedor", "vendedores", "soporte"
    ]
    for role in member.roles:
        role_lower = role.name.lower()
        if any(keyword in role_lower for keyword in staff_keywords):
            return True

    return False

# ==========================================
# 💰 PRECIOS OFICIALES DE PRODUCTOS
# ==========================================

PRODUCT_PRICES = {
    "Panel de iOS": {
        "summary": "Mes: $20 USD | Perma: $50 USD",
        "details": [
            "• **Mes:** $20 USD",
            "• **Permanente:** $50 USD"
        ]
    },
    "Proxy de iOS": {
        "summary": "2 Semanas: $20 USD | Mes: $35 USD | Perma: $100 USD",
        "details": [
            "• **2 Semanas:** $20 USD",
            "• **Mes:** $35 USD",
            "• **Permanente:** $100 USD"
        ]
    },
    "Complex de PC": {
        "summary": "Semana: $6 USD | Mes: $20 USD | Perma: $55 USD",
        "details": [
            "• **Semana:** $6 USD",
            "• **Mes:** $20 USD",
            "• **Permanente:** $55 USD"
        ]
    },
    "BR Mods": {
        "summary": "Semana: $6 USD | Mes: $15 USD | Perma: $55 USD",
        "details": [
            "• **Semana:** $6 USD",
            "• **Mes:** $15 USD",
            "• **Permanente:** $55 USD"
        ]
    }
}

# ==========================================
# 🎫 SISTEMA DE TICKETS (CREACIÓN Y VISTAS)
# ==========================================

async def create_ticket_for_user(interaction: discord.Interaction, selected_product: str):
    """Crea el canal privado del ticket para el usuario, envía los precios y reinicia los combos."""
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ Esta función solo puede utilizarse dentro de un servidor.", ephemeral=True)
        return

    # Responder / Diferir de inmediato para evitar cualquier timeout de Discord
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    # Verificar si el usuario ya tiene un ticket activo
    user_id_str = str(interaction.user.id)
    for ch in guild.text_channels:
        if ch.topic and f"ticket_user_{user_id_str}" in ch.topic:
            # Reiniciar los combos en el mensaje original para que no queden marcados
            try:
                if interaction.message:
                    await interaction.message.edit(view=TicketPanelView())
            except Exception:
                pass

            await interaction.followup.send(
                f"⚠️ Ya tienes un ticket abierto actualmente.\n👉 **Haz clic aquí para entrar a tu ticket:** {ch.mention}",
                ephemeral=True
            )
            return

    try:
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', interaction.user.name).lower()[:10] or "cliente"
        # Nombre descriptivo del canal con producto (ej: ticket-brmods-rafa)
        slug_product = re.sub(r'[^a-zA-Z0-9]', '', selected_product).lower()[:8]
        channel_name = f"ticket-{slug_product}-{clean_name}"

        # Categoría: usar la categoría del canal actual o buscar abre Ticket / TICKETS
        category = interaction.channel.category if interaction.channel else None
        if not category:
            category = (
                discord.utils.get(guild.categories, name="abre Ticket 🤝")
                or discord.utils.get(guild.categories, name="🎫 TICKETS")
                or discord.utils.get(guild.categories, name="TICKETS")
            )

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                read_message_history=True,
                embed_links=True,
                attach_files=True
            )
        }

        # Dar acceso a roles de Vendedor / Staff si existen
        for role in guild.roles:
            if role.name.lower() in ["vendedor", "vendedores", "staff", "soporte", "admin", "administrador", "owner"]:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    embed_links=True
                )

        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"ticket_user_{user_id_str} | Cliente: {interaction.user.name} | Producto: {selected_product}"
        )

        # Obtener desglose de precios del producto elegido
        prices_info = PRODUCT_PRICES.get(selected_product, {})
        prices_list_text = "\n".join(prices_info.get("details", []))

        embed_ticket = discord.Embed(
            title="🎫 ¡Ticket de Compra Creado!",
            description=(
                f"👋 ¡Hola {interaction.user.mention}! Has abierto un ticket para adquirir:\n\n"
                f"🛒 **Producto solicitado:** `{selected_product}`\n\n"
                f"💵 **Precios oficiales disponibles:**\n{prices_list_text}\n\n"
                f"⏳ **Por favor espere a que los vendedores respondan.**\n\n"
                f"Un vendedor o administrador te atenderá a la brevedad posible con los métodos de pago y la entrega de tu pedido."
            ),
            color=discord.Color.from_rgb(0, 230, 118)
        )
        embed_ticket.add_field(name="👤 Cliente", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=True)
        embed_ticket.add_field(name="📦 Pedido", value=f"**{selected_product}**", inline=True)
        embed_ticket.set_footer(
            text="Denzel XT • Solo miembros del Staff / Owner pueden cerrar este ticket.",
            icon_url=guild.icon.url if guild.icon else None
        )

        await ticket_channel.send(
            content=f"👋 {interaction.user.mention} ¡Bienvenido a tu ticket de compra para **{selected_product}**!",
            embed=embed_ticket,
            view=TicketCloseView()
        )

        interaction.client.user_ticket_selections.pop(interaction.user.id, None)

        # REINICIAR LOS COMBOS EN EL MENSAJE PRINCIPAL A SU PLACEHOLDER ORIGINAL
        try:
            if interaction.message:
                await interaction.message.edit(view=TicketPanelView())
                logger.info("🔄 Combos del panel reiniciados a sus placeholders por defecto.")
        except Exception as e:
            logger.warning(f"Aviso al reiniciar combos en el mensaje: {e}")

        # Responder al usuario enviándolo directamente a su ticket
        await interaction.followup.send(
            f"✅ **¡Tu canal de ticket ha sido creado con éxito!**\n\n"
            f"👉 **Haz clic aquí para entrar a tu ticket:** {ticket_channel.mention}",
            ephemeral=True
        )
        logger.info(f"🎫 Ticket #{ticket_channel.name} creado para {interaction.user.name} ({interaction.user.id}) | Producto: {selected_product}")

    except discord.Forbidden:
        await interaction.followup.send(
            "❌ **Error de Permisos:** El bot no tiene el permiso 'Gestionar Canales' para crear tu ticket. Contacta a un administrador.",
            ephemeral=True
        )
    except Exception as e:
        logger.error(f"❌ Error al crear canal de ticket: {e}", exc_info=True)
        await interaction.followup.send(
            f"❌ Ocurrió un error al crear tu ticket: {e}",
            ephemeral=True
        )


class TicketSelectIOS(discord.ui.Select):
    """Menú desplegable para productos de iOS con precios."""
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Panel de iOS",
                value="Panel de iOS",
                description="Mes: $20 USD | Permanente: $50 USD",
                emoji="📱"
            ),
            discord.SelectOption(
                label="Proxy de iOS",
                value="Proxy de iOS",
                description="2 Sem: $20 USD | Mes: $35 USD | Perma: $100 USD",
                emoji="🌐"
            )
        ]
        super().__init__(
            placeholder="🍎 Selecciona un producto de iOS...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_select_ios",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        interaction.client.user_ticket_selections[interaction.user.id] = selected
        logger.info(f"📱 [SELECCIÓN iOS] {interaction.user.name} eligió: {selected}. Creando ticket...")
        await create_ticket_for_user(interaction, selected)


class TicketSelectPC(discord.ui.Select):
    """Menú desplegable para productos de PC con precios."""
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Complex de PC",
                value="Complex de PC",
                description="Semana: $6 USD | Mes: $20 USD | Perma: $55 USD",
                emoji="💻"
            ),
            discord.SelectOption(
                label="BR Mods",
                value="BR Mods",
                description="Semana: $6 USD | Mes: $15 USD | Perma: $55 USD",
                emoji="🔥"
            )
        ]
        super().__init__(
            placeholder="💻 Selecciona un producto de PC...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_select_pc",
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        interaction.client.user_ticket_selections[interaction.user.id] = selected
        logger.info(f"💻 [SELECCIÓN PC] {interaction.user.name} eligió: {selected}. Creando ticket...")
        await create_ticket_for_user(interaction, selected)


class TicketPanelView(discord.ui.View):
    """Vista principal con los 2 combos y el botón de Generar Ticket (Persistente)."""
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelectIOS())
        self.add_item(TicketSelectPC())

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        logger.error(f"❌ Error en interacción de vista de tickets [{item}]: {error}", exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Ocurrió un error al procesar tu selección. Por favor intenta de nuevo.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Ocurrió un error al procesar tu selección. Por favor intenta de nuevo.", ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(
        label="Generar Ticket",
        style=discord.ButtonStyle.success,
        emoji="🎫",
        custom_id="ticket_btn_create",
        row=2
    )
    async def generate_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        logger.info(f"🎫 Botón 'Generar Ticket' presionado por {interaction.user.name} ({interaction.user.id})")
        client = interaction.client
        selected_product = client.user_ticket_selections.get(interaction.user.id)

        # Si aún no seleccionó nada en el menú desplegable
        if not selected_product:
            await interaction.response.send_message(
                "⚠️ **Debes seleccionar un producto primero.**\n"
                "Por favor, elige una opción en el menú de **iOS** o **PC** (Panel, Proxy, Complex o BR Mods).",
                ephemeral=True
            )
            return

        await create_ticket_for_user(interaction, selected_product)


class TicketConfirmCloseView(discord.ui.View):
    """Confirmación para cerrar el ticket (Solo Staff/Owner)."""
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Sí, cerrar y borrar", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Doble verificación de permisos de Staff/Owner
        if not is_user_staff_or_owner(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "⛔ **Acceso denegado:** No tienes permisos para borrar este ticket.",
                ephemeral=True
            )
            return

        await interaction.response.send_message("🔒 **Cerrando ticket...** El canal se eliminará en 5 segundos.")
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Ticket cerrado por {interaction.user.name} (Staff/Owner)")
        except Exception as e:
            logger.error(f"Error borrando canal de ticket: {e}")

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ Operación cancelada. El ticket permanece abierto.", ephemeral=True)


class TicketCloseView(discord.ui.View):
    """Botón persistente para cerrar el ticket con restricción de roles."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Cerrar Ticket",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="ticket_btn_close"
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Comprobar si el usuario tiene rol de Owner, Admin o Staff
        if not is_user_staff_or_owner(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "⛔ **Acceso Denegado:** Solo los miembros del **Staff, Vendedores, Administradores u Owners** tienen permitido cerrar este ticket.\n"
                "Por favor espera a que el equipo termine de atenderte.",
                ephemeral=True
            )
            return

        confirm_view = TicketConfirmCloseView()
        await interaction.response.send_message(
            "⚠️ **¿Estás seguro de que deseas cerrar y eliminar este ticket?**",
            view=confirm_view,
            ephemeral=True
        )


# ==========================================
# 🤖 CLASE PRINCIPAL DEL BOT (DENZER VOICE + TICKETS + ANUNCIOS)
# ==========================================

class DenzerVoiceBot(discord.Client):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.tree = app_commands.CommandTree(self)
        self.target_channel_id = VOICE_CHANNEL_ID
        self.ticket_channel_id = TICKET_CHANNEL_ID
        self.announcement_channel_id = ANNOUNCEMENT_CHANNEL_ID
        self.guild_id = GUILD_ID
        self.connection_lock = asyncio.Lock()
        self.audio_queue = asyncio.Queue()
        self.is_playing_speech = False
        self.user_join_cooldowns = {}
        self.user_ticket_selections = {}
        self.start_time = time.time()
        self.current_status_index = 0
        self.watchdog_fail_count = 0
        self.last_voice_reconnect = 0
        self.is_connecting_voice = False

        self.setup_slash_commands()

    async def setup_hook(self):
        """Registra vistas persistentes de Discord antes de iniciar eventos."""
        self.add_view(TicketPanelView())
        self.add_view(TicketCloseView())
        logger.info("🧩 Vistas persistentes del Sistema de Tickets registradas correctamente.")

    async def on_interaction(self, interaction: discord.Interaction):
        """Monitoreo de interacciones en tiempo real."""
        logger.info(f"📥 Interacción recibida | Usuario: {interaction.user.name} | Tipo: {interaction.type.name}")

    def create_ticket_panel_embed(self, guild: Optional[discord.Guild] = None) -> discord.Embed:
        """Crea el mensaje Embed estético para el panel de tickets con la lista de precios oficial."""
        embed = discord.Embed(
            title="🛒 Tienda Denzel XT | Sistema de Tickets",
            description=(
                "¡Bienvenido a la tienda oficial de **Denzel XT**! 💸\n\n"
                "Selecciona el producto que deseas adquirir en los menús desplegables de abajo.\n"
                "Se creará tu canal privado al instante donde los vendedores te atenderán.\n"
            ),
            color=discord.Color.from_rgb(255, 215, 0)
        )
        embed.add_field(
            name="🍎 Productos iOS",
            value=(
                "📱 **Panel de iOS**\n"
                "└ *Mes:* **$20 USD** • *Perma:* **$50 USD**\n\n"
                "🌐 **Proxy de iOS**\n"
                "└ *2 Semanas:* **$20 USD** • *Mes:* **$35 USD** • *Perma:* **$100 USD**"
            ),
            inline=False
        )
        embed.add_field(
            name="💻 Productos PC",
            value=(
                "💻 **Complex de PC**\n"
                "└ *Semana:* **$6 USD** • *Mes:* **$20 USD** • *Perma:* **$55 USD**\n\n"
                "🔥 **BR Mods**\n"
                "└ *Semana:* **$6 USD** • *Mes:* **$15 USD** • *Perma:* **$55 USD**"
            ),
            inline=False
        )
        embed.set_footer(
            text="Denzel XT • Precios oficiales en USD • Soporte y Ventas 24/7",
            icon_url=guild.icon.url if (guild and guild.icon) else None
        )
        return embed

    def create_announcement_content(self, guild: Optional[discord.Guild] = None) -> tuple[discord.Embed, discord.ui.View]:
        """Crea el Embed y Botón de Anuncio para incentivar compras y dirigir a tickets."""
        embed = discord.Embed(
            title="🔥 ¡MEJORA TU NIVEL CON DENZEL XT! | PANELES, PROXIES Y MODS 💸",
            description=(
                "¿Quieres dominar tus partidas con la mayor seguridad y el mejor rendimiento? 🚀\n"
                "En **Denzel XT** te ofrecemos herramientas VIP 100% optimizadas y con soporte garantizado.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🍎 **PRODUCTOS DISPONIBLES PARA iOS:**\n"
                "• 📱 **Panel de iOS:** *Mes: $20 USD • Permanente: $50 USD*\n"
                "• 🌐 **Proxy de iOS:** *2 Semanas: $20 USD • Mes: $35 USD • Permanente: $100 USD*\n\n"
                "💻 **PRODUCTOS DISPONIBLES PARA PC:**\n"
                "• 💻 **Complex de PC:** *Semana: $6 USD • Mes: $20 USD • Permanente: $55 USD*\n"
                "• 🔥 **BR Mods:** *Semana: $6 USD • Mes: $15 USD • Permanente: $55 USD*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "🛒 **¿CÓMO COMPRAR O PEDIR INFORMACIÓN?**\n"
                f"¡Es muy fácil y rápido! Abre tu ticket de atención inmediata en:\n"
                f"👉 <#{self.ticket_channel_id}>\n\n"
                "1️⃣ Ve a <#" + str(self.ticket_channel_id) + ">\n"
                "2️⃣ Selecciona tu producto en el combo desplegable.\n"
                "3️⃣ Se creará tu canal privado donde los vendedores te darán los métodos de pago y la entrega inmediata."
            ),
            color=discord.Color.from_rgb(0, 255, 136)
        )
        embed.set_footer(
            text="Denzel XT • Ventas oficiales • Atención Inmediata 24/7",
            icon_url=guild.icon.url if (guild and guild.icon) else None
        )

        # Botón directo que conduce al canal de tickets
        view = discord.ui.View()
        channel_url = f"https://discord.com/channels/{self.guild_id}/{self.ticket_channel_id}"
        view.add_item(
            discord.ui.Button(
                label="🎫 Comprar / Abrir Ticket Aquí",
                url=channel_url,
                style=discord.ButtonStyle.link,
                emoji="🛒"
            )
        )
        return embed, view

    async def ensure_ticket_panel(self):
        """Verifica si el panel de tickets ya está publicado en el canal asignado; si no, lo envía o actualiza."""
        try:
            channel = self.get_channel(self.ticket_channel_id)
            if not channel:
                try:
                    channel = await self.fetch_channel(self.ticket_channel_id)
                except Exception as e:
                    logger.warning(f"⚠️ No se pudo acceder al canal de tickets (ID: {self.ticket_channel_id}): {e}")
                    return

            panel_found = False
            async for msg in channel.history(limit=30):
                if msg.author.id == self.user.id and msg.embeds:
                    for emb in msg.embeds:
                        if emb.title and "Sistema de Tickets" in emb.title:
                            panel_found = True
                            try:
                                await msg.edit(
                                    embed=self.create_ticket_panel_embed(channel.guild),
                                    view=TicketPanelView()
                                )
                                logger.info(f"📋 Panel de tickets en #{channel.name} (ID: {msg.id}) actualizado con precios y combos reiniciados.")
                            except Exception as e:
                                logger.warning(f"Aviso actualizando panel: {e}")
                            break
                if panel_found:
                    break

            if not panel_found:
                embed = self.create_ticket_panel_embed(channel.guild)
                view = TicketPanelView()
                await channel.send(embed=embed, view=view)
                logger.info(f"📨 Panel de tickets enviado exitosamente al canal #{channel.name} ({channel.id}).")
        except Exception as e:
            logger.error(f"❌ Error al revisar/enviar panel de tickets: {e}")

    async def ensure_announcement(self):
        """Verifica si el mensaje de venta/anuncio ya está publicado en el canal de anuncios; si no, lo envía o actualiza."""
        try:
            channel = self.get_channel(self.announcement_channel_id)
            if not channel:
                try:
                    channel = await self.fetch_channel(self.announcement_channel_id)
                except Exception as e:
                    logger.warning(f"⚠️ No se pudo acceder al canal de anuncios (ID: {self.announcement_channel_id}): {e}")
                    return

            announcement_found = False
            async for msg in channel.history(limit=25):
                if msg.author.id == self.user.id and msg.embeds:
                    for emb in msg.embeds:
                        if emb.title and "MEJORA TU NIVEL CON DENZEL XT" in emb.title:
                            announcement_found = True
                            try:
                                embed, view = self.create_announcement_content(channel.guild)
                                await msg.edit(embed=embed, view=view)
                                logger.info(f"📢 Anuncio de venta en #{channel.name} (ID: {msg.id}) actualizado correctamente.")
                            except Exception as e:
                                logger.warning(f"Aviso actualizando anuncio: {e}")
                            break
                if announcement_found:
                    break

            if not announcement_found:
                embed, view = self.create_announcement_content(channel.guild)
                await channel.send(embed=embed, view=view)
                logger.info(f"📨 Anuncio oficial de compra publicado exitosamente en #{channel.name} ({channel.id}).")
        except Exception as e:
            logger.error(f"❌ Error al revisar/publicar anuncio: {e}")

    def setup_slash_commands(self):
        @self.tree.command(name="tts", description="Lee tu mensaje en voz alta en el canal de voz para los que no tienen mic")
        @app_commands.describe(mensaje="El texto que quieres que la voz latina diga en la llamada")
        async def tts_cmd(interaction: discord.Interaction, mensaje: str):
            author_name = extract_natural_name(interaction.user)
            clean_msg = clean_chat_message(mensaje)
            if not clean_msg:
                await interaction.response.send_message("❌ Mensaje vacío o no válido.", ephemeral=True)
                return

            speech_text = f"{author_name} dice: {clean_msg}"
            await interaction.response.send_message(f"🎙️ **{author_name} dice:** {clean_msg}")

            try:
                audio_file = await self.generate_speech_audio(speech_text)
                await self.audio_queue.put(audio_file)
            except Exception as e:
                logger.error(f"Error generando TTS de comando /tts: {e}")

        @self.tree.command(name="panel_tickets", description="Publica el panel oficial de tickets en un canal")
        @app_commands.describe(canal="Canal donde publicar el panel (opcional, por defecto el configurado)")
        @app_commands.default_permissions(administrator=True)
        async def panel_tickets_cmd(interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None):
            target = canal or self.get_channel(self.ticket_channel_id) or interaction.channel
            embed = self.create_ticket_panel_embed(interaction.guild)
            view = TicketPanelView()
            await target.send(embed=embed, view=view)
            await interaction.response.send_message(f"✅ Panel de tickets publicado en {target.mention}.", ephemeral=True)

        @self.tree.command(name="enviar_anuncio", description="Publica el anuncio de venta de paneles y mods en el canal de anuncios")
        @app_commands.describe(canal="Canal donde publicar el anuncio (opcional, por defecto el canal de anuncios)")
        @app_commands.default_permissions(administrator=True)
        async def announcement_cmd(interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None):
            target = canal or self.get_channel(self.announcement_channel_id) or interaction.channel
            embed, view = self.create_announcement_content(interaction.guild)
            await target.send(embed=embed, view=view)
            await interaction.response.send_message(f"✅ Anuncio de compra publicado con éxito en {target.mention}.", ephemeral=True)

    async def start_cloud_health_server(self):
        """Servidor HTTP liviano para Railway/Render."""
        try:
            app = web.Application()
            async def handle_ping(request):
                uptime_str = format_uptime(time.time() - self.start_time)
                return web.Response(text=f"OK - Denzer Bot Online (Uptime: {uptime_str})")

            app.router.add_get("/", handle_ping)
            app.router.add_get("/health", handle_ping)

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", PORT)
            await site.start()
            logger.info(f"🌐 Servidor de salud activo en puerto {PORT}.")
        except Exception as e:
            logger.debug(f"Aviso servidor de salud HTTP: {e}")

    async def on_ready(self):
        logger.info("=" * 65)
        logger.info(f"🟢 BOT EN LÍNEA: {self.user.name} ({self.user.id})")
        logger.info(f"🔊 Canal de Voz Objetivo: {self.target_channel_id}")
        logger.info(f"🎫 Canal de Tickets Objetivo: {self.ticket_channel_id}")
        logger.info(f"📢 Canal de Anuncios: {self.announcement_channel_id}")
        logger.info("🛒 Sistema de Tickets de Compra con Precios: Activo")
        logger.info("🔒 Restricción de Cierre de Tickets (Solo Staff/Owner): Activo")
        logger.info("=" * 65)

        # Iniciar servidor web de salud para Railway si aplica
        await self.start_cloud_health_server()

        # Asegurar que el panel de tickets esté publicado y actualizado con los precios
        await self.ensure_ticket_panel()

        # Asegurar que el anuncio de venta esté publicado en el canal de anuncios
        await self.ensure_announcement()

        # Sincronizar comandos Slash en el servidor
        try:
            guild_obj = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild_obj)
            await self.tree.sync(guild=guild_obj)
            logger.info("⚡ Comandos Slash sincronizados (/tts, /panel_tickets, /enviar_anuncio).")
        except Exception as e:
            logger.warning(f"Aviso al sincronizar slash commands: {e}")

        # Iniciar loops en segundo plano
        if not self.voice_watchdog.is_running():
            self.voice_watchdog.start()
        if not self.voice_keepalive.is_running():
            self.voice_keepalive.start()
        if not self.audio_worker.is_running():
            self.audio_worker.start()
        if not self.status_rotator.is_running():
            self.status_rotator.start()

    async def ensure_voice_connection(self):
        """Asegura la conexión al canal de voz de forma segura."""
        if self.is_connecting_voice or self.connection_lock.locked():
            return

        now = time.time()
        if now - self.last_voice_reconnect < 10.0:
            return
        self.last_voice_reconnect = now

        async with self.connection_lock:
            self.is_connecting_voice = True
            try:
                target_channel = self.get_channel(self.target_channel_id)
                if not target_channel:
                    try:
                        target_channel = await self.fetch_channel(self.target_channel_id)
                    except Exception as e:
                        logger.error(f"❌ No se encontró el canal {self.target_channel_id}: {e}")
                        return

                guild = target_channel.guild
                voice_client = guild.voice_client

                if voice_client and voice_client.is_connected() and voice_client.channel.id == self.target_channel_id:
                    self.watchdog_fail_count = 0
                    return

                if voice_client and voice_client.is_connected() and voice_client.channel.id != self.target_channel_id:
                    try:
                        await asyncio.wait_for(voice_client.move_to(target_channel), timeout=5.0)
                        self.watchdog_fail_count = 0
                        return
                    except Exception:
                        pass

                if voice_client:
                    try:
                        await voice_client.disconnect(force=True)
                    except Exception:
                        pass
                    await asyncio.sleep(1.0)

                logger.info(f"🔄 Conectando a canal '{target_channel.name}' (ID: {self.target_channel_id})...")
                try:
                    await target_channel.connect(reconnect=False, timeout=15.0, self_deaf=False)
                    logger.info(f"✅ ¡Conectado con éxito a '{target_channel.name}'!")
                    self.watchdog_fail_count = 0
                except Exception as ce:
                    logger.warning(f"Aviso de conexión al canal de voz: {ce}")

            except Exception as e:
                logger.debug(f"Aviso en ensure_voice_connection: {e}")
            finally:
                self.is_connecting_voice = False

    @tasks.loop(seconds=30)
    async def voice_keepalive(self):
        """Mantiene el estado."""
        try:
            target_channel = self.get_channel(self.target_channel_id)
            if not target_channel or not target_channel.guild.voice_client:
                return
        except Exception as e:
            logger.debug(f"Aviso keepalive: {e}")

    async def generate_speech_audio(self, text_to_say: str) -> str:
        """Genera el audio en MP3."""
        file_path = os.path.join(AUDIO_TEMP_DIR, f"tts_{int(asyncio.get_event_loop().time() * 1000)}.mp3")
        try:
            tts = edge_tts.Communicate(text_to_say, voice="es-MX-DaliaNeural", rate="+3%", pitch="-1Hz")
            await tts.save(file_path)
        except Exception:
            def make_gtts():
                g = gTTS(text=text_to_say, lang="es", tld="com.mx")
                g.save(file_path)
            await asyncio.to_thread(make_gtts)
        return file_path

    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Saludos y eventos de voz."""
        if member.id == self.user.id:
            return

        if member.bot:
            return

        if after.channel and after.channel.id == self.target_channel_id and (before.channel is None or before.channel.id != self.target_channel_id):
            loop_time = asyncio.get_event_loop().time()
            last_join = self.user_join_cooldowns.get(member.id, 0)
            if loop_time - last_join < 2:
                return

            self.user_join_cooldowns[member.id] = loop_time
            clean_name = extract_natural_name(member)

            saludos = [
                f"Hola {clean_name}, bienvenido papi, qué bueno que llegaste a la sala.",
                f"Miren quién llegó... Bienvenido papi {clean_name}, ponte cómodo.",
                f"Hola papi {clean_name}, bienvenido a Denzel XT. Disfruta la llamada.",
                f"Qué onda {clean_name}, bienvenido papi, qué gusto tenerte aquí en la sala más dura."
            ]
            frase_saludo = random.choice(saludos)

            try:
                audio_file = await self.generate_speech_audio(frase_saludo)
                await self.audio_queue.put(audio_file)
            except Exception as e:
                logger.error(f"Error generando audio de bienvenida: {e}")

    async def on_message(self, message: discord.Message):
        """TTS de chat para llamadas."""
        if message.author.bot or message.author.id == self.user.id:
            return

        if message.channel.id in (self.ticket_channel_id, self.announcement_channel_id):
            return
        if hasattr(message.channel, "name") and message.channel.name.startswith("ticket-"):
            return

        is_target_channel = (message.channel.id == self.target_channel_id)
        is_mentioned = self.user.mentioned_in(message)

        if not is_target_channel and not is_mentioned:
            return

        if not message.content:
            return

        cleaned_text = clean_chat_message(message.content)
        if not cleaned_text:
            return

        author_name = extract_natural_name(message.author)
        speech_text = f"{author_name} dice: {cleaned_text}"

        try:
            try:
                await message.add_reaction("🎙️")
            except Exception:
                pass

            audio_file = await self.generate_speech_audio(speech_text)
            await self.audio_queue.put(audio_file)
        except Exception as e:
            logger.error(f"Error TTS chat: {e}")

    @tasks.loop(seconds=1)
    async def audio_worker(self):
        """Procesador de cola de audio."""
        if self.audio_queue.empty() or self.is_playing_speech:
            return

        target_channel = self.get_channel(self.target_channel_id)
        if not target_channel or not target_channel.guild.voice_client:
            return

        voice_client = target_channel.guild.voice_client
        if not voice_client.is_connected():
            return

        audio_file = await self.audio_queue.get()
        if not os.path.exists(audio_file):
            return

        self.is_playing_speech = True

        if voice_client.is_playing():
            voice_client.stop()
            await asyncio.sleep(0.1)

        finish_event = asyncio.Event()

        def after_play(err):
            if err:
                logger.error(f"Error reproducción: {err}")
            try:
                if os.path.exists(audio_file):
                    os.remove(audio_file)
            except Exception:
                pass
            self.loop.call_soon_threadsafe(finish_event.set)

        try:
            audio_source = discord.FFmpegPCMAudio(audio_file)
            voice_client.play(audio_source, after=after_play)
            await asyncio.wait_for(finish_event.wait(), timeout=15.0)
        except Exception as e:
            logger.error(f"Audio worker error: {e}")
        finally:
            self.is_playing_speech = False

    @tasks.loop(seconds=20)
    async def voice_watchdog(self):
        """Guardián de conexión de voz pasivo."""
        try:
            target_channel = self.get_channel(self.target_channel_id)
            if not target_channel:
                return

            guild = target_channel.guild
            voice_client = guild.voice_client

            if not voice_client or not voice_client.is_connected():
                self.watchdog_fail_count += 1
                if self.watchdog_fail_count >= 3:
                    await self.ensure_voice_connection()
            else:
                self.watchdog_fail_count = 0
                if voice_client.channel.id != self.target_channel_id:
                    await self.ensure_voice_connection()

        except Exception as e:
            logger.debug(f"[Guardián] Error: {e}")

    @tasks.loop(seconds=20)
    async def status_rotator(self):
        """Rota presencia en Discord."""
        try:
            uptime_str = format_uptime(time.time() - self.start_time)
            status_list = [
                f"24/7 Online ⏱️ {uptime_str}",
                "Denzel XT 💸 | 100% Inmortal",
                "Tickets de Venta Activos 🎫",
                "Usa /tts para hablar 💬"
            ]

            status_text = status_list[self.current_status_index]
            self.current_status_index = (self.current_status_index + 1) % len(status_list)

            activity = discord.Activity(
                type=discord.ActivityType.listening,
                name=status_text
            )
            await self.change_presence(status=discord.Status.online, activity=activity)
        except Exception as e:
            logger.debug(f"Error rotando estado: {e}")

    @voice_watchdog.before_loop
    @voice_keepalive.before_loop
    @audio_worker.before_loop
    @status_rotator.before_loop
    async def before_tasks(self):
        await self.wait_until_ready()

def run_bot():
    ensure_single_local_instance()

    if not TOKEN:
        logger.error("❌ ERROR: DISCORD_TOKEN no configurado en .env")
        sys.exit(1)

    try:
        intents_full = discord.Intents.default()
        intents_full.guilds = True
        intents_full.voice_states = True
        intents_full.messages = True
        intents_full.message_content = True
        bot = DenzerVoiceBot(intents=intents_full)
        bot.run(TOKEN)
    except discord.errors.PrivilegedIntentsRequired:
        intents_basic = discord.Intents.default()
        intents_basic.guilds = True
        intents_basic.voice_states = True
        intents_basic.messages = True
        bot = DenzerVoiceBot(intents=intents_basic)
        bot.run(TOKEN)

if __name__ == "__main__":
    run_bot()
