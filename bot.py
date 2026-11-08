import os
import sys
import re
import io
import time
import random
import socket
import asyncio
import datetime
import logging
from logging.handlers import RotatingFileHandler
import unicodedata
from typing import Optional, Union
from PIL import Image
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
SECURITY_LOGS_CHANNEL_ID = int(os.getenv("SECURITY_LOGS_CHANNEL_ID", "1568911585743863909"))
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "1527614361785471006"))
LEAVE_CHANNEL_ID = int(os.getenv("LEAVE_CHANNEL_ID", "1543366821564911616"))
RULES_CHANNEL_ID = int(os.getenv("RULES_CHANNEL_ID", "1527654849150193694"))
SERVER_LINK_CHANNEL_ID = int(os.getenv("SERVER_LINK_CHANNEL_ID", "1521338694441631855"))
PERMANENT_INVITE_URL = os.getenv("PERMANENT_INVITE_URL", "https://discord.gg/2NTFjRqemq")
GUILD_ID = int(os.getenv("GUILD_ID", "1387608034641055785"))
PORT = int(os.getenv("PORT", "8080"))

# Configuración de Seguridad
BOT_AUTH_PASSWORD = "rafaxd"
INVITE_REGEX = re.compile(r'(?:https?:\/\/)?(?:www\.)?(?:discord\.(?:gg|io|me|li)|discord(?:app)?\.com\/invite)\/([a-zA-Z0-9\-]+)', re.IGNORECASE)

# Banner oficial para bienvenidas y despedidas
BANNER_IMAGE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "denzel_banner.jpg")

def format_account_age(created_at: datetime.datetime) -> str:
    """Calcula la antigüedad de la cuenta en español."""
    now = discord.utils.utcnow()
    delta = now - created_at
    days = delta.days
    if days < 1:
        return "hoy"
    elif days < 30:
        return f"{days} días"
    elif days < 365:
        months = days // 30
        return f"{months} mes" if months == 1 else f"{months} meses"
    else:
        years = days // 365
        return f"{years} año" if years == 1 else f"{years} años"

# Huellas digitales de la imagen de estafa (MrBeast / Casino Crypto)
SCAM_IMAGE_DHASH = 0x9c6c89976da4247d
SCAM_IMAGE_AHASH = 0x63678c084f4939f

def compute_image_dhash_int(im: Image.Image) -> int:
    gray = im.convert('L').resize((9, 8), Image.Resampling.LANCZOS)
    diff = 0
    for y in range(8):
        for x in range(8):
            if gray.getpixel((x, y)) > gray.getpixel((x + 1, y)):
                diff |= (1 << (y * 8 + x))
    return diff

def compute_image_ahash_int(im: Image.Image) -> int:
    gray = im.convert('L').resize((8, 8), Image.Resampling.LANCZOS)
    pixels = [gray.getpixel((x, y)) for y in range(8) for x in range(8)]
    avg = sum(pixels) / 64.0
    val = 0
    for i, p in enumerate(pixels):
        if p > avg:
            val |= (1 << i)
    return val

def is_scam_image(image_bytes: bytes) -> bool:
    """Detecta la plantilla de estafa MrBeast/Crypto sin tocar fotos normales de los usuarios."""
    try:
        im = Image.open(io.BytesIO(image_bytes))
        d_hash = compute_image_dhash_int(im)
        a_hash = compute_image_ahash_int(im)
        d_dist = bin(SCAM_IMAGE_DHASH ^ d_hash).count('1')
        a_dist = bin(SCAM_IMAGE_AHASH ^ a_hash).count('1')
        return (d_dist <= 8 or a_dist <= 8)
    except Exception:
        return False

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

    # 0. Dueño, creadores y Rafa (Whitelist Absoluta e Inmune a Sanciones)
    if member.id in (1562511458791854093, 1236983422665228289, 1342982123568762922):
        return True
    if "rafa" in member.name.lower() or "rafa" in (member.display_name or "").lower():
        return True

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

        # Registrar en el canal de seguridad y logs 24/7
        try:
            bot_client = interaction.client
            await bot_client.log_security_event(
                guild=guild,
                title="🎫 Nuevo Ticket de Compra Creado",
                description=(
                    f"👤 **Cliente:** {interaction.user.mention} (`{interaction.user.name}` - `{interaction.user.id}`)\n"
                    f"🛒 **Producto solicitado:** `{selected_product}`\n"
                    f"📁 **Canal creado:** {ticket_channel.mention} (`#{ticket_channel.name}`)"
                ),
                color=discord.Color.from_rgb(0, 230, 118)
            )
        except Exception as log_err:
            logger.warning(f"Aviso registrando ticket en logs: {log_err}")

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
        
        # Registrar en el canal de logs 24/7
        try:
            bot_client = interaction.client
            channel_name = interaction.channel.name if interaction.channel else "desconocido"
            await bot_client.log_security_event(
                guild=interaction.guild,
                title="🔒 Ticket Cerrado y Eliminado",
                description=(
                    f"📁 **Canal:** `#{channel_name}`\n"
                    f"👤 **Cerrado por:** {interaction.user.mention} (`{interaction.user.name}` - Staff/Owner)"
                ),
                color=discord.Color.dark_grey()
            )
        except Exception:
            pass

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
# 🔐 SISTEMA DE AUTORIZACIÓN DE BOTS (ANTI-RAID CON PASSWORD)
# ==========================================

class BotAuthModal(discord.ui.Modal, title="🔐 Autorizar Bot (Owner)"):
    password_input = discord.ui.TextInput(
        label="Contraseña del Owner:",
        placeholder="Ingresa la contraseña para autorizar...",
        style=discord.TextStyle.short,
        min_length=3,
        max_length=50,
        required=True
    )

    def __init__(self, bot_id: int, bot_name: str, message: Optional[discord.Message] = None):
        super().__init__()
        self.bot_id = bot_id
        self.bot_name = bot_name
        self.message = message

    async def on_submit(self, interaction: discord.Interaction):
        if self.password_input.value.strip().lower() == BOT_AUTH_PASSWORD.lower():
            embed = discord.Embed(
                title="✅ BOT AUTORIZADO POR EL OWNER",
                description=(
                    f"🤖 **Bot:** <@{self.bot_id}> (`{self.bot_name}` - `{self.bot_id}`)\n"
                    f"👑 **Autorizado por:** {interaction.user.mention} (`{interaction.user.name}`)\n"
                    f"🔑 **Verificación:** Contraseña correcta confirmada (`rafaxd`).\n"
                    f"🛡️ **Estado:** Acceso legal permitido permanentemente."
                ),
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="Denzel XT • Sistema de Seguridad 24/7", icon_url=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None)

            try:
                if self.message:
                    await self.message.edit(content=f"✅ **Bot {self.bot_name} verificado y autorizado.**", embed=embed, view=None)
                elif interaction.message:
                    await interaction.message.edit(content=f"✅ **Bot {self.bot_name} verificado y autorizado.**", embed=embed, view=None)
            except Exception as e:
                logger.warning(f"Aviso actualizando mensaje de auth: {e}")

            await interaction.response.send_message(
                f"✅ **¡Contraseña correcta!** El bot **{self.bot_name}** ha sido verificado y autorizado en el servidor.",
                ephemeral=True
            )
            logger.info(f"✅ Bot {self.bot_name} ({self.bot_id}) autorizado con contraseña por Owner {interaction.user.name}")
        else:
            await interaction.response.send_message(
                "❌ **Contraseña incorrecta.** El bot NO ha sido autorizado. Verifica con el Owner la clave.",
                ephemeral=True
            )
            logger.warning(f"❌ Intento de autorización fallido para bot {self.bot_id} por {interaction.user.name} (contraseña errónea)")


class BotVerificationView(discord.ui.View):
    """Botones interactivos para que el Owner autorice o expulse bots nuevos."""
    def __init__(self, bot_id: int, bot_name: str):
        super().__init__(timeout=None)
        self.bot_id = bot_id
        self.bot_name = bot_name

        self.btn_auth = discord.ui.Button(
            label="Autorizar Bot",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"bot_auth_verify:{bot_id}"
        )
        self.btn_auth.callback = self.auth_callback
        self.add_item(self.btn_auth)

        self.btn_kick = discord.ui.Button(
            label="No reconozco el bot (Expulsar)",
            style=discord.ButtonStyle.danger,
            emoji="❌",
            custom_id=f"bot_auth_kick:{bot_id}"
        )
        self.btn_kick.callback = self.kick_callback
        self.add_item(self.btn_kick)

    async def auth_callback(self, interaction: discord.Interaction):
        if interaction.guild and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                "⛔ **Acceso Denegado:** Solo el **Dueño del Servidor (Owner)** puede ingresar la contraseña para autorizar nuevos bots.",
                ephemeral=True
            )
            return

        modal = BotAuthModal(bot_id=self.bot_id, bot_name=self.bot_name, message=interaction.message)
        await interaction.response.send_modal(modal)

    async def kick_callback(self, interaction: discord.Interaction):
        is_owner = (interaction.guild and interaction.user.id == interaction.guild.owner_id)
        is_admin = interaction.user.guild_permissions.administrator
        if not (is_owner or is_admin):
            await interaction.response.send_message(
                "⛔ **Acceso Denegado:** Solo el **Owner** o **Administradores** pueden expulsar bots.",
                ephemeral=True
            )
            return

        guild = interaction.guild
        bot_member = guild.get_member(self.bot_id) if guild else None
        kick_status = ""
        if bot_member:
            try:
                await bot_member.kick(reason=f"Anti-Raid: Bot no reconocido expulsado por {interaction.user.name}")
                kick_status = f"🔨 Bot **{self.bot_name}** expulsado inmediatamente."
            except Exception as e:
                kick_status = f"⚠️ Falló expulsión ({e})."
        else:
            kick_status = "⚠️ El bot ya no se encuentra en el servidor."

        embed = discord.Embed(
            title="🔨 BOT EXPULSADO DEL SERVIDOR (ANTI-RAID)",
            description=(
                f"🤖 **Bot:** `{self.bot_name}` (`{self.bot_id}`)\n"
                f"👤 **Acción realizada por:** {interaction.user.mention} (`{interaction.user.name}`)\n"
                f"🛡️ **Motivo:** Bot no reconocido por el Owner.\n"
                f"⚡ **Resultado:** {kick_status}"
            ),
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="Denzel XT • Sistema Anti-Raid 24/7", icon_url=guild.icon.url if guild and guild.icon else None)

        try:
            await interaction.message.edit(content=f"🔨 **Bot {self.bot_name} rechazado y expulsado.**", embed=embed, view=None)
        except Exception:
            pass

        await interaction.response.send_message(
            f"🔨 Bot **{self.bot_name}** rechazado y expulsado del servidor por seguridad.",
            ephemeral=True
        )
        logger.info(f"🔨 Bot {self.bot_name} ({self.bot_id}) expulsado por {interaction.user.name}")


# ==========================================
# 🤖 CLASE PRINCIPAL DEL BOT (DENZER VOICE + TICKETS + ANUNCIOS + SEGURIDAD 24/7)
# ==========================================

class DenzerVoiceBot(discord.Client):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.tree = app_commands.CommandTree(self)
        self.target_channel_id = VOICE_CHANNEL_ID
        self.ticket_channel_id = TICKET_CHANNEL_ID
        self.announcement_channel_id = ANNOUNCEMENT_CHANNEL_ID
        self.security_logs_channel_id = SECURITY_LOGS_CHANNEL_ID
        self.welcome_channel_id = WELCOME_CHANNEL_ID
        self.leave_channel_id = LEAVE_CHANNEL_ID
        self.rules_channel_id = RULES_CHANNEL_ID
        self.server_link_channel_id = SERVER_LINK_CHANNEL_ID
        self.permanent_invite_url = PERMANENT_INVITE_URL
        self.guild_id = GUILD_ID
        self.connection_lock = asyncio.Lock()
        self.audio_queue = asyncio.Queue()
        self.is_playing_speech = False
        self.user_join_cooldowns = {}
        self.user_ticket_selections = {}
        self.recent_bans = {}
        self.recent_kicks = {}
        self.user_message_timestamps = {}
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
        """Monitoreo de interacciones en tiempo real y fallback de botones persistentes."""
        logger.info(f"📥 Interacción recibida | Usuario: {interaction.user.name} | Tipo: {interaction.type.name}")

        if interaction.type == discord.InteractionType.component and interaction.data:
            custom_id = interaction.data.get("custom_id", "")
            if custom_id.startswith("bot_auth_verify:"):
                try:
                    bot_id = int(custom_id.split(":")[1])
                except Exception:
                    bot_id = 0

                if interaction.guild and interaction.user.id != interaction.guild.owner_id:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            "⛔ **Acceso Denegado:** Solo el **Dueño del Servidor (Owner)** puede autorizar bots con contraseña.",
                            ephemeral=True
                        )
                    return

                modal = BotAuthModal(bot_id=bot_id, bot_name="Bot", message=interaction.message)
                if not interaction.response.is_done():
                    await interaction.response.send_modal(modal)
                return

            elif custom_id.startswith("bot_auth_kick:"):
                try:
                    bot_id = int(custom_id.split(":")[1])
                except Exception:
                    bot_id = 0

                is_owner = (interaction.guild and interaction.user.id == interaction.guild.owner_id)
                is_admin = interaction.user.guild_permissions.administrator
                if not (is_owner or is_admin):
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            "⛔ **Acceso Denegado:** Solo el **Owner** o **Administradores** pueden expulsar bots.",
                            ephemeral=True
                        )
                    return

                guild = interaction.guild
                target_bot = guild.get_member(bot_id) if guild else None
                bot_name = target_bot.name if target_bot else f"ID {bot_id}"
                kick_status = ""
                if target_bot:
                    try:
                        await target_bot.kick(reason=f"Anti-Raid: Expulsado por Owner/Admin {interaction.user.name}")
                        kick_status = f"🔨 Bot **{bot_name}** expulsado del servidor."
                    except Exception as e:
                        kick_status = f"⚠️ Falló expulsión ({e})."
                else:
                    kick_status = "⚠️ El bot ya no está en el servidor."

                embed = discord.Embed(
                    title="🔨 BOT EXPULSADO DEL SERVIDOR (ANTI-RAID)",
                    description=(
                        f"🤖 **Bot:** `{bot_name}` (`{bot_id}`)\n"
                        f"👑 **Expulsado por:** {interaction.user.mention} (`{interaction.user.name}`)\n"
                        f"🛡️ **Motivo:** Bot no reconocido por el Owner.\n"
                        f"⚡ **Resultado:** {kick_status}"
                    ),
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                embed.set_footer(text="Denzel XT • Sistema de Seguridad 24/7", icon_url=guild.icon.url if guild and guild.icon else None)

                try:
                    await interaction.message.edit(content=f"🔨 **Bot {bot_name} rechazado y expulsado.**", embed=embed, view=None)
                except Exception:
                    pass

                if not interaction.response.is_done():
                    await interaction.response.send_message(f"🔨 Bot **{bot_name}** expulsado del servidor.", ephemeral=True)
                return

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
        logger.info(f"🛡️ Canal de Logs de Seguridad 24/7: {self.security_logs_channel_id}")
        logger.info(f"👋 Canal de Bienvenida: {self.welcome_channel_id}")
        logger.info(f"👋 Canal de Despedida: {self.leave_channel_id}")
        logger.info("🛒 Sistema de Tickets de Compra con Precios: Activo")
        logger.info("🔒 Restricción de Cierre de Tickets (Solo Staff/Owner): Activo")
        logger.info("🛡️ Suite de Protección (Anti-Nuke, Anti-Raid, Anti-Scam): Activa")
        logger.info("=" * 65)

        # Iniciar servidor web de salud para Railway si aplica
        await self.start_cloud_health_server()

        # Asegurar canal de seguridad y logs 24/7 (situado arriba de anuncios)
        target_guild = self.get_guild(self.guild_id)
        if target_guild:
            await self.get_or_create_security_logs_channel(target_guild)

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

    # ==========================================
    # 🛡️ SISTEMA DE LOGS 24/7 Y GESTIÓN DE CANAL
    # ==========================================

    async def get_or_create_security_logs_channel(self, guild: Optional[discord.Guild] = None) -> Optional[discord.TextChannel]:
        """Obtiene o crea el canal 🛡️・logs-24-7 ubicado arriba de anuncios."""
        if not guild:
            guild = self.get_guild(self.guild_id)
        if not guild:
            return None

        # 1. Buscar por ID configurado
        if self.security_logs_channel_id:
            ch = guild.get_channel(self.security_logs_channel_id)
            if ch:
                return ch
            try:
                ch = await guild.fetch_channel(self.security_logs_channel_id)
                if ch:
                    return ch
            except Exception:
                pass

        # 2. Buscar por topic o nombre
        for ch in guild.text_channels:
            if ch.topic and "denzel_xt_security_logs_24_7" in ch.topic:
                self.security_logs_channel_id = ch.id
                return ch
            if ch.name in ["🛡️・logs-24-7", "logs-24-7", "🛡-logs-24-7"]:
                self.security_logs_channel_id = ch.id
                return ch

        # 3. Crear el canal justo arriba de anuncios
        try:
            ann_channel = guild.get_channel(self.announcement_channel_id)
            target_pos = ann_channel.position if ann_channel else 1

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    embed_links=True,
                    manage_channels=True,
                    manage_messages=True,
                    read_message_history=True
                )
            }
            if guild.owner:
                overwrites[guild.owner] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_messages=True,
                    read_message_history=True
                )
            for member in guild.members:
                if "rafa" in member.name.lower() or member.id in (1562511458791854093, 1236983422665228289):
                    overwrites[member] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_messages=True,
                        read_message_history=True
                    )
            for role in guild.roles:
                if role.permissions.administrator or any(k in role.name.lower() for k in ["admin", "staff", "owner", "dueño", "fundador"]):
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True, read_message_history=True)

            new_ch = await guild.create_text_channel(
                name="🛡️・logs-24-7",
                category=None,
                position=target_pos,
                overwrites=overwrites,
                topic="denzel_xt_security_logs_24_7 | Canal oficial de Registros de Seguridad 24/7 de Denzel XT"
            )
            if ann_channel:
                await new_ch.edit(position=ann_channel.position)

            self.security_logs_channel_id = new_ch.id
            logger.info(f"🛡️ Canal de logs de seguridad creado: #{new_ch.name} (ID: {new_ch.id})")
            return new_ch
        except Exception as e:
            logger.error(f"❌ Error al crear canal de logs de seguridad: {e}", exc_info=True)
            return None

    async def log_security_event(self, guild: discord.Guild, title: str, description: str, color: discord.Color, thumbnail: Optional[str] = None):
        """Envía un registro al canal 🛡️・logs-24-7 de forma limpia y confiable."""
        try:
            channel = await self.get_or_create_security_logs_channel(guild)
            if not channel:
                return

            embed = discord.Embed(
                title=title,
                description=description,
                color=color,
                timestamp=discord.utils.utcnow()
            )
            if thumbnail:
                embed.set_thumbnail(url=thumbnail)
            embed.set_footer(text="Denzel XT • Logs de Seguridad 24/7", icon_url=guild.icon.url if guild and guild.icon else None)
            await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"❌ Error al enviar evento al canal de logs: {e}")

    # ==========================================
    # 🛡️ DEFENSAS ANTI-NUKE
    # ==========================================

    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        """Anti-Nuke: Si alguien intenta borrar canales, baneo automático."""
        guild = channel.guild
        if guild.id != self.guild_id:
            return

        executor = None
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.channel_delete, limit=2):
                if entry.target and entry.target.id == channel.id:
                    executor = entry.user
                    break
                if abs((discord.utils.utcnow() - entry.created_at).total_seconds()) < 10:
                    executor = entry.user
                    break
        except Exception as e:
            logger.warning(f"Error consultando audit logs de canal borrado: {e}")

        if not executor:
            return

        if executor.id == guild.owner_id or executor.id == self.user.id:
            await self.log_security_event(
                guild=guild,
                title="ℹ️ Canal Eliminado por Autorizado",
                description=f"📁 **Canal:** `#{channel.name}`\n👤 **Autorizado:** {executor.mention} (`{executor.id}`)",
                color=discord.Color.blue()
            )
            return

        logger.warning(f"🚨 ANTI-NUKE: {executor.name} ({executor.id}) borró el canal #{channel.name}!")
        ban_status = ""
        try:
            await guild.ban(executor, reason="Anti-Nuke: Eliminación no autorizada de canal", delete_message_days=0)
            ban_status = "🔨 **BANEADO AUTOMÁTICAMENTE** del servidor."
        except Exception as e:
            ban_status = f"⚠️ Falló el baneo automático ({e}). Retirando permisos..."
            try:
                member = guild.get_member(executor.id)
                if member:
                    danger_roles = [r for r in member.roles if r.permissions.administrator or r.permissions.manage_channels]
                    if danger_roles:
                        await member.remove_roles(*danger_roles, reason="Anti-Nuke: Retiro de emergencia de permisos")
            except Exception:
                pass

        await self.log_security_event(
            guild=guild,
            title="🚨 ALERTA ANTI-NUKE: CANAL ELIMINADO 🚨",
            description=(
                f"**¡Ataque detectado y neutralizado!**\n\n"
                f"📁 **Canal eliminado:** `#{channel.name}` (`{channel.id}`)\n"
                f"👤 **Perpetrador:** {executor.mention} (`{executor.name}` - `{executor.id}`)\n"
                f"🛡️ **Acción de defensa:** {ban_status}"
            ),
            color=discord.Color.red()
        )

    async def on_guild_role_delete(self, role: discord.Role):
        """Anti-Nuke: Si alguien intenta borrar roles, baneo automático."""
        guild = role.guild
        if guild.id != self.guild_id:
            return

        executor = None
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.role_delete, limit=2):
                if entry.target and entry.target.id == role.id:
                    executor = entry.user
                    break
                if abs((discord.utils.utcnow() - entry.created_at).total_seconds()) < 10:
                    executor = entry.user
                    break
        except Exception as e:
            logger.warning(f"Error consultando audit logs de rol borrado: {e}")

        if not executor:
            return

        if executor.id == guild.owner_id or executor.id == self.user.id:
            await self.log_security_event(
                guild=guild,
                title="ℹ️ Rol Eliminado por Autorizado",
                description=f"🎭 **Rol:** `@{role.name}`\n👤 **Autorizado:** {executor.mention} (`{executor.id}`)",
                color=discord.Color.blue()
            )
            return

        logger.warning(f"🚨 ANTI-NUKE: {executor.name} ({executor.id}) borró el rol @{role.name}!")
        ban_status = ""
        try:
            await guild.ban(executor, reason="Anti-Nuke: Eliminación no autorizada de roles", delete_message_days=0)
            ban_status = "🔨 **BANEADO AUTOMÁTICAMENTE** del servidor."
        except Exception as e:
            ban_status = f"⚠️ Falló el baneo automático ({e}). Retirando permisos..."
            try:
                member = guild.get_member(executor.id)
                if member:
                    danger_roles = [r for r in member.roles if r.permissions.administrator or r.permissions.manage_roles]
                    if danger_roles:
                        await member.remove_roles(*danger_roles, reason="Anti-Nuke: Retiro de emergencia de permisos")
            except Exception:
                pass

        await self.log_security_event(
            guild=guild,
            title="🚨 ALERTA ANTI-NUKE: ROL ELIMINADO 🚨",
            description=(
                f"**¡Ataque detectado y neutralizado!**\n\n"
                f"🎭 **Rol eliminado:** `@{role.name}` (`{role.id}`)\n"
                f"👤 **Perpetrador:** {executor.mention} (`{executor.name}` - `{executor.id}`)\n"
                f"🛡️ **Acción de defensa:** {ban_status}"
            ),
            color=discord.Color.red()
        )

    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        """Anti-Nuke: Si alguien no autorizado crea o modifica webhooks, borrado y baneo."""
        guild = channel.guild
        if guild.id != self.guild_id:
            return

        executor = None
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.webhook_create, limit=1):
                if abs((discord.utils.utcnow() - entry.created_at).total_seconds()) < 10:
                    executor = entry.user
                    break
        except Exception as e:
            logger.warning(f"Error consultando audit logs de webhook: {e}")

        if not executor or executor.id == guild.owner_id or executor.id == self.user.id:
            return

        logger.warning(f"🚨 ANTI-NUKE: Webhook creado por {executor.name} ({executor.id}) en #{channel.name}!")

        deleted_count = 0
        try:
            if hasattr(channel, "webhooks"):
                webhooks = await channel.webhooks()
                for wh in webhooks:
                    if wh.user and wh.user.id == executor.id:
                        await wh.delete(reason="Anti-Nuke: Webhook no autorizado")
                        deleted_count += 1
        except Exception as e:
            logger.warning(f"Error eliminando webhooks no autorizados: {e}")

        try:
            await guild.ban(executor, reason="Anti-Nuke: Creación no autorizada de Webhook")
            ban_status = "🔨 **BANEADO AUTOMÁTICAMENTE**."
        except Exception as e:
            ban_status = f"⚠️ Falló baneo ({e})."

        await self.log_security_event(
            guild=guild,
            title="🚨 ALERTA ANTI-NUKE: WEBHOOK DETECTADO 🚨",
            description=(
                f"**¡Creación de Webhook malicioso neutralizada!**\n\n"
                f"📁 **Canal afectado:** `#{channel.name}`\n"
                f"👤 **Creador:** {executor.mention} (`{executor.name}` - `{executor.id}`)\n"
                f"🗑️ **Webhooks purgados:** {deleted_count}\n"
                f"🛡️ **Acción de defensa:** {ban_status}"
            ),
            color=discord.Color.red()
        )

    # ==========================================
    # 🚫 ANTI-MASS BAN Y ANTI-MASS KICK
    # ==========================================

    async def on_member_ban(self, guild: discord.Guild, user: Union[discord.User, discord.Member]):
        """Anti-Mass Ban: Detecta si un usuario o admin deshonesto banea a más de 3 miembros en 15s."""
        if guild.id != self.guild_id:
            return

        executor = None
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=1):
                if entry.target and entry.target.id == user.id:
                    executor = entry.user
                    break
        except Exception:
            pass

        if not executor or executor.id == guild.owner_id or executor.id == self.user.id:
            return

        now = time.time()
        recent = [t for t in self.recent_bans.get(executor.id, []) if now - t < 15.0]
        recent.append(now)
        self.recent_bans[executor.id] = recent

        if len(recent) >= 3:
            logger.critical(f"🚨 ANTI-MASS BAN: {executor.name} ({executor.id}) baneó 3 miembros en 15s!")
            try:
                await guild.ban(executor, reason="Anti-Mass Ban: Intento de baneo masivo detenido")
            except Exception as e:
                logger.error(f"Error baneando atacante de mass-ban: {e}")

            await self.log_security_event(
                guild=guild,
                title="🚨 ALERTA CRÍTICA: ANTI-MASS BAN ACTIVADO 🚨",
                description=(
                    f"**¡Ataque de baneo masivo detenido de inmediato!**\n\n"
                    f"👤 **Atacante:** {executor.mention} (`{executor.name}` - `{executor.id}`)\n"
                    f"📊 **Baneos intentados:** {len(recent)} en menos de 15 segundos.\n"
                    f"🛡️ **Acción de defensa:** 🔨 **BANEADO DE INMEDIATO DEL SERVIDOR**."
                ),
                color=discord.Color.red()
            )

    async def on_member_remove(self, member: discord.Member):
        """Anti-Mass Kick y registro 24/7 de salidas."""
        guild = member.guild
        if guild.id != self.guild_id:
            return

        executor = None
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.kick, limit=1):
                if entry.target and entry.target.id == member.id:
                    if abs((discord.utils.utcnow() - entry.created_at).total_seconds()) < 6:
                        executor = entry.user
                        break
        except Exception:
            pass

        if executor and executor.id != guild.owner_id and executor.id != self.user.id:
            now = time.time()
            recent = [t for t in self.recent_kicks.get(executor.id, []) if now - t < 15.0]
            recent.append(now)
            self.recent_kicks[executor.id] = recent

            if len(recent) >= 3:
                logger.critical(f"🚨 ANTI-MASS KICK: {executor.name} ({executor.id}) expulsó 3 miembros en 15s!")
                try:
                    await member.guild.ban(executor, reason="Anti-Mass Kick: Intento de expulsión masiva detenido")
                except Exception as e:
                    logger.error(f"Error baneando atacante de mass-kick: {e}")

                await self.log_security_event(
                    guild=guild,
                    title="🚨 ALERTA CRÍTICA: ANTI-MASS KICK ACTIVADO 🚨",
                    description=(
                        f"**¡Ataque de expulsión masiva detenido de inmediato!**\n\n"
                        f"👤 **Atacante:** {executor.mention} (`{executor.name}` - `{executor.id}`)\n"
                        f"📊 **Expulsiones intentadas:** {len(recent)} en menos de 15 segundos.\n"
                        f"🛡️ **Acción de defensa:** 🔨 **BANEADO DE INMEDIATO DEL SERVIDOR**."
                    ),
                    color=discord.Color.red()
                )
                return

        # Salida normal de miembro
        await self.log_security_event(
            guild=guild,
            title="📤 Miembro ha Salido del Servidor",
            description=(
                f"👤 {member.mention} (`{member.name}` - `{member.id}`)\n"
                f"👥 Total de miembros restantes: **{guild.member_count}**"
            ),
            color=discord.Color.dark_grey(),
            thumbnail=member.display_avatar.url if member.display_avatar else None
        )

        # Enviar mensaje de despedida en el canal público de despedida con diseño y banner oficial
        try:
            leave_ch = guild.get_channel(self.leave_channel_id)
            if not leave_ch:
                leave_ch = await guild.fetch_channel(self.leave_channel_id)
            if leave_ch:
                embed_leave = discord.Embed(
                    title=f"👋 Hasta luego, {member.name}",
                    description=f"**{member.name}** salió de **𝑫𝒆𝒏𝒛𝒆𝒍 𝑿𝕿 💵**. Ahora somos **{guild.member_count}** miembros.",
                    color=discord.Color.from_rgb(88, 101, 242)
                )
                embed_leave.set_thumbnail(url=member.display_avatar.url)
                embed_leave.set_footer(text="𝑫𝒆𝒏𝒛𝒆𝒍 𝑿𝕿 💵 • Hasta la próxima")

                if os.path.exists(BANNER_IMAGE_PATH):
                    file = discord.File(BANNER_IMAGE_PATH, filename="denzel_banner.jpg")
                    embed_leave.set_image(url="attachment://denzel_banner.jpg")
                    await leave_ch.send(file=file, embed=embed_leave)
                else:
                    await leave_ch.send(embed=embed_leave)
                logger.info(f"📤 Despedida oficial enviada para {member.name} en #{leave_ch.name}")
        except Exception as e:
            logger.warning(f"Aviso enviando despedida a canal público: {e}")

    # ==========================================
    # 🤖 ANTI-RAID / ANTI-BOTS MALICIOSOS (CON PASSWORD DEL OWNER)
    # ==========================================

    async def on_member_join(self, member: discord.Member):
        """Anti-Raid / Bots Maliciosos, canal de bienvenida y registro 24/7."""
        guild = member.guild
        if guild.id != self.guild_id:
            return

        # Si el miembro que entra es un BOT
        if member.bot:
            if member.id == self.user.id:
                return

            logger.warning(f"🤖 Bot detectado ingresando al servidor: {member.name} ({member.id})")

            inviter = None
            try:
                async for entry in guild.audit_logs(action=discord.AuditLogAction.bot_add, limit=2):
                    if entry.target and entry.target.id == member.id:
                        inviter = entry.user
                        break
            except Exception as e:
                logger.warning(f"Aviso buscando inviter del bot: {e}")

            logs_channel = await self.get_or_create_security_logs_channel(guild)
            if logs_channel:
                embed = discord.Embed(
                    title="🚨 ALERTA ANTI-RAID: NUEVO BOT DETECTADO 🚨",
                    description=(
                        f"Se ha detectado el ingreso de un nuevo bot al servidor:\n\n"
                        f"🤖 **Bot:** {member.mention} (`{member.name}` - `{member.id}`)\n"
                        f"👤 **Invitado por:** {inviter.mention if inviter else 'Desconocido'} (`{inviter.id if inviter else 'N/A'}`)\n"
                        f"📅 **Cuenta creada:** <t:{int(member.created_at.timestamp())}:R>\n\n"
                        f"⚠️ **ESTADO:** *Pendiente de Autorización por el Dueño (Owner).*\n\n"
                        f"🔒 **Instrucciones para el Owner:**\n"
                        f"• Si autorizas este bot en el servidor, presiona **Autorizar Bot** e ingresa la contraseña (`rafaxd`).\n"
                        f"• Si **NO** reconoces el bot, presiona **No reconozco el bot** para expulsarlo inmediatamente."
                    ),
                    color=discord.Color.from_rgb(255, 69, 0),
                    timestamp=discord.utils.utcnow()
                )
                embed.set_footer(text="Denzel XT • Sistema Anti-Bots Maliciosos 24/7", icon_url=guild.icon.url if guild and guild.icon else None)

                view = BotVerificationView(bot_id=member.id, bot_name=member.name)
                owner_mention = guild.owner.mention if guild.owner else "@everyone"
                await logs_channel.send(
                    content=f"⚠️ {owner_mention} **¡ATENCIÓN! Bot detectado sin autorización.**",
                    embed=embed,
                    view=view
                )
            return

        # Entrada de usuario normal: registrar en logs 24/7
        await self.log_security_event(
            guild=guild,
            title="📥 Nuevo Miembro Unido",
            description=(
                f"👤 {member.mention} (`{member.name}` - `{member.id}`)\n"
                f"📅 Cuenta creada: <t:{int(member.created_at.timestamp())}:R>\n"
                f"👥 Total de miembros: **{guild.member_count}**"
            ),
            color=discord.Color.green(),
            thumbnail=member.display_avatar.url if member.display_avatar else None
        )

        # Enviar mensaje de bienvenida en el canal público con diseño y banner oficial
        try:
            welcome_ch = guild.get_channel(self.welcome_channel_id)
            if not welcome_ch:
                welcome_ch = await guild.fetch_channel(self.welcome_channel_id)
            if welcome_ch:
                embed_welcome = discord.Embed(
                    title="👋 Bienvenido a 𝑫𝒆𝒏𝒛𝒆𝒍 𝑿𝕿 💵",
                    description=f"¡Bienvenido {member.mention}! Eres el miembro **#{guild.member_count}**. Esperamos que disfrutes la comunidad.",
                    color=discord.Color.from_rgb(88, 101, 242)
                )
                embed_welcome.set_thumbnail(url=member.display_avatar.url)
                embed_welcome.set_footer(text=f"𝑫𝒆𝒏𝒛𝒆𝒍 𝑿𝕿 💵 • Cuenta creada hace {format_account_age(member.created_at)}")

                if os.path.exists(BANNER_IMAGE_PATH):
                    file = discord.File(BANNER_IMAGE_PATH, filename="denzel_banner.jpg")
                    embed_welcome.set_image(url="attachment://denzel_banner.jpg")
                    await welcome_ch.send(content=f"{member.mention}", file=file, embed=embed_welcome)
                else:
                    await welcome_ch.send(content=f"{member.mention}", embed=embed_welcome)
                logger.info(f"📥 Bienvenida oficial enviada para {member.name} en #{welcome_ch.name}")
        except Exception as e:
            logger.warning(f"Aviso enviando bienvenida a canal público: {e}")

    # ==========================================
    # 🔗 ANTI-SPAM (SOLO SCAM/MRBEAST), ANTI-LINKS Y TTS DE CHAT
    # ==========================================

    async def on_message(self, message: discord.Message):
        """Filtro Anti-Links e Invitaciones, Anti-Scam (MrBeast), y TTS de chat para llamadas."""
        if not message.guild or message.author.bot or message.author.id == self.user.id:
            return

        # 1. FILTRO ANTI-LINKS (INVITACIONES A OTROS SERVIDORES DE DISCORD)
        invite_match = INVITE_REGEX.search(message.content)
        if invite_match:
            if not is_user_staff_or_owner(message.author, message.guild):
                code = invite_match.group(1)
                is_internal_invite = False
                try:
                    fetched_inv = await self.fetch_invite(code)
                    if fetched_inv.guild and fetched_inv.guild.id == self.guild_id:
                        is_internal_invite = True
                except Exception:
                    pass

                # Solo bloquear si es un enlace a otro servidor externo
                if not is_internal_invite:
                    try:
                        await message.delete()
                    except Exception:
                        pass

                    timeout_success = False
                    try:
                        await message.author.timeout(
                            datetime.timedelta(minutes=10),
                            reason="Anti-Links: Envío de enlace de invitación a otro servidor"
                        )
                        timeout_success = True
                    except Exception as e:
                        logger.warning(f"No se pudo aplicar timeout por anti-links: {e}")

                    try:
                        await message.channel.send(
                            f"⛔ {message.author.mention} **¡Prohibido enviar invitaciones a otros servidores!**\n"
                            f"Has sido silenciado por **10 minutos** automáticamente por seguridad.",
                            delete_after=7
                        )
                    except Exception:
                        pass

                    await self.log_security_event(
                        guild=message.guild,
                        title="🚨 ALERTA ANTI-LINKS: INVITACIÓN EXTERNA BLOQUEADA 🚨",
                        description=(
                            f"👤 **Usuario:** {message.author.mention} (`{message.author.name}` - `{message.author.id}`)\n"
                            f"💬 **Canal:** {message.channel.mention}\n"
                            f"🔗 **Contenido:** `||{message.content[:200]}||`\n"
                            f"🛡️ **Acción:** Mensaje eliminado + {'Silenciado 10 minutos (Timeout)' if timeout_success else 'Mensaje eliminado'}"
                        ),
                        color=discord.Color.orange()
                    )
                    return

        # 2. FILTRO ANTI-SCAM ESPECÍFICO (IMAGEN FRAUDULENTA DE MRBEAST / CRYPTO CASINO)
        # Los usuarios normales pueden mandar fotos y videos libremente; solo se bloquea esta imagen de estafa.
        if message.attachments and not is_user_staff_or_owner(message.author, message.guild):
            for att in message.attachments:
                is_img = (att.content_type and "image" in att.content_type) or any(
                    att.filename.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp"]
                )
                if is_img:
                    try:
                        img_bytes = await att.read()
                        if is_scam_image(img_bytes):
                            try:
                                await message.delete()
                            except Exception:
                                pass

                            timeout_scam = False
                            try:
                                await message.author.timeout(
                                    datetime.timedelta(hours=24),
                                    reason="Anti-Scam: Imagen fraudulenta de MrBeast / Casino Crypto detectada"
                                )
                                timeout_scam = True
                            except Exception as te:
                                logger.warning(f"No se pudo mutear por scam image: {te}")

                            try:
                                await message.channel.send(
                                    f"🚨 {message.author.mention} **Imagen de estafa/scam detectada y eliminada.** Has sido silenciado.",
                                    delete_after=7
                                )
                            except Exception:
                                pass

                            await self.log_security_event(
                                guild=message.guild,
                                title="🚨 ALERTA ANTI-SCAM: IMAGEN FRAUDULENTA PURGADA 🚨",
                                description=(
                                    f"👤 **Usuario:** {message.author.mention} (`{message.author.name}` - `{message.author.id}`)\n"
                                    f"💬 **Canal:** {message.channel.mention}\n"
                                    f"🖼️ **Archivo:** `{att.filename}`\n"
                                    f"🛡️ **Motivo:** Coincidencia exacta con plantilla de raid/scam MrBeast Crypto Casino.\n"
                                    f"⚡ **Acción:** Mensaje eliminado + {'Silenciado 24 horas (Timeout)' if timeout_scam else 'Mensaje eliminado'}"
                                ),
                                color=discord.Color.red()
                            )
                            return
                    except Exception as e:
                        logger.debug(f"Aviso escaneando imagen: {e}")

        # 3. BLOQUEO DE ESCRITURA EN CANAL DE REGLAS (SOLO ADMINS/STAFF)
        if message.channel.id == self.rules_channel_id and not is_user_staff_or_owner(message.author, message.guild):
            try:
                await message.delete()
            except Exception:
                pass
            return

        # 4. CANALES EXCLUIDOS DE TTS
        tts_excluded_channels = (
            self.ticket_channel_id,
            self.announcement_channel_id,
            self.security_logs_channel_id,
            self.welcome_channel_id,
            self.leave_channel_id,
            self.rules_channel_id,
            self.server_link_channel_id
        )
        if message.channel.id in tts_excluded_channels:
            return
        if hasattr(message.channel, "name") and message.channel.name.startswith("ticket-"):
            return

        # 4. REPRODUCCIÓN TTS PARA LLAMADAS DE VOZ
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
        intents_full.members = True
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
