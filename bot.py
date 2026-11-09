import os
import sys
import re
import io
import time
import json
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

# Nuevos Canales y Roles del Sistema Denzel XT
REFERENCES_CHANNEL_ID = int(os.getenv("REFERENCES_CHANNEL_ID", "1527614373588373504"))
LIVES_CHANNEL_ID = int(os.getenv("LIVES_CHANNEL_ID", "1552827664136540211"))
FREE_KEYS_CHANNEL_ID = int(os.getenv("FREE_KEYS_CHANNEL_ID", "1529687325146353674"))
CUSTOMER_ROLE_ID = int(os.getenv("CUSTOMER_ROLE_ID", "1527614241996013678"))
RESELLER_ROLE_ID = int(os.getenv("RESELLER_ROLE_ID", "1530649167796637887"))

# Archivos de datos y persistencia en data/
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)
GIVEAWAYS_FILE = os.path.join(DATA_DIR, "giveaways.json")
INVITES_FILE = os.path.join(DATA_DIR, "invites.json")

# Configuración de Seguridad
BOT_AUTH_PASSWORD = "rafaxd"
INVITE_REGEX = re.compile(r'(?:https?:\/\/)?(?:www\.)?(?:discord\.(?:gg|io|me|li)|discord(?:app)?\.com\/invite)\/([a-zA-Z0-9\-]+)', re.IGNORECASE)

# Banner oficial para bienvenidas, despedidas y eventos
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
    """Garantiza que solo una instancia del bot corra en esta máquina local."""
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_SERVICE_ID") or os.getenv("PORT"):
        return
    global SINGLE_INSTANCE_SOCKET
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', port))
        SINGLE_INSTANCE_SOCKET = s
    except Exception as e:
        logger.warning(f"Aviso single-instance check: {e}")

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


# ==========================================
# 📈 SISTEMA DE CRECIMIENTO E INVITACIONES (/invites)
# ==========================================

class InviteManager:
    """Gestor persistente de invitaciones y crecimiento del servidor."""
    def __init__(self, filepath: str = INVITES_FILE):
        self.filepath = filepath
        self.lock = asyncio.Lock()
        self.data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Error cargando invites.json: {e}")
        return {"inviters": {}, "members": {}}

    def _save(self):
        try:
            temp_file = self.filepath + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(temp_file, self.filepath)
        except Exception as e:
            logger.error(f"Error guardando invites.json: {e}")

    async def record_join(self, inviter_id: int, member_id: int):
        async with self.lock:
            inv_str = str(inviter_id)
            mem_str = str(member_id)
            self.data.setdefault("members", {})[mem_str] = inv_str
            inviters = self.data.setdefault("inviters", {})
            if inv_str not in inviters:
                inviters[inv_str] = {"total": 0, "active": 0, "leaves": 0}
            inviters[inv_str]["total"] += 1
            inviters[inv_str]["active"] += 1
            self._save()

    async def record_leave(self, member_id: int) -> Optional[int]:
        async with self.lock:
            mem_str = str(member_id)
            inv_str = self.data.get("members", {}).get(mem_str)
            if inv_str and inv_str in self.data.get("inviters", {}):
                self.data["inviters"][inv_str]["leaves"] += 1
                self.data["inviters"][inv_str]["active"] = max(
                    0, self.data["inviters"][inv_str]["total"] - self.data["inviters"][inv_str]["leaves"]
                )
                self._save()
                return int(inv_str)
            return None

    def get_stats(self, user_id: int) -> dict:
        inv_str = str(user_id)
        return self.data.get("inviters", {}).get(inv_str, {"total": 0, "active": 0, "leaves": 0})

    def get_top_inviters(self, limit: int = 10) -> list[tuple[int, dict]]:
        items = []
        for uid_str, stats in self.data.get("inviters", {}).items():
            try:
                items.append((int(uid_str), stats))
            except Exception:
                pass
        items.sort(key=lambda x: (x[1].get("active", 0), x[1].get("total", 0)), reverse=True)
        return items[:limit]


# ==========================================
# 🎁 SISTEMA DE SORTEOS PERSISTENTE (/sorteo)
# ==========================================

class GiveawayManager:
    """Gestor persistente de sorteos con participantes y selección automática de ganadores."""
    def __init__(self, filepath: str = GIVEAWAYS_FILE):
        self.filepath = filepath
        self.lock = asyncio.Lock()
        self.data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Error cargando giveaways.json: {e}")
        return {"active": {}, "history": []}

    def _save(self):
        try:
            temp_file = self.filepath + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(temp_file, self.filepath)
        except Exception as e:
            logger.error(f"Error guardando giveaways.json: {e}")

    async def create_giveaway(self, giveaway_id: str, channel_id: int, message_id: int,
                              prize: str, winners_count: int, host_id: int, end_time: float):
        async with self.lock:
            self.data.setdefault("active", {})[giveaway_id] = {
                "id": giveaway_id,
                "channel_id": channel_id,
                "message_id": message_id,
                "prize": prize,
                "winners_count": max(1, winners_count),
                "host_id": host_id,
                "end_time": end_time,
                "participants": []
            }
            self._save()

    async def toggle_participant(self, giveaway_id: str, user_id: int) -> tuple[bool, int, bool]:
        """Agrega o retira participante. Retorna (success, total_count, is_joined)."""
        async with self.lock:
            gw = self.data.get("active", {}).get(giveaway_id)
            if not gw:
                return False, 0, False
            participants = gw.setdefault("participants", [])
            if user_id in participants:
                participants.remove(user_id)
                self._save()
                return True, len(participants), False
            else:
                participants.append(user_id)
                self._save()
                return True, len(participants), True

    def get_giveaway(self, giveaway_id: str) -> Optional[dict]:
        return self.data.get("active", {}).get(giveaway_id)

    def get_due_giveaways(self) -> list[dict]:
        now = time.time()
        due = []
        for gw in list(self.data.get("active", {}).values()):
            if now >= gw.get("end_time", 0):
                due.append(gw)
        return due

    async def finish_giveaway(self, giveaway_id: str, winners: list[int]):
        async with self.lock:
            gw = self.data.get("active", {}).pop(giveaway_id, None)
            if gw:
                gw["winners"] = winners
                gw["finished_at"] = time.time()
                self.data.setdefault("history", []).append(gw)
                self._save()


# ==========================================
# 💳 MÉTODOS DE PAGO Y REFERENCIAS DE CLIENTES
# ==========================================

def create_payment_methods_embed(guild: Optional[discord.Guild] = None) -> tuple[discord.Embed, discord.ui.View]:
    """Genera el Embed oficial con métodos de pago listos para copiar."""
    embed = discord.Embed(
        title="💳 MÉTODOS DE PAGO OFICIALES • DENZEL XT 💵",
        description=(
            "¡Adquiere tus **Paneles de iOS**, **Proxies**, **Complex PC** y **BR Mods** con total seguridad!\n"
            "Elige tu método de pago preferido y sigue las indicaciones:\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=discord.Color.from_rgb(0, 255, 170)
    )

    embed.add_field(
        name="🪙 1. Binance Pay / USDT Cripto (0% Comisión)",
        value=(
            "• **Criptomoneda:** USDT (`Red TRC20` o `BEP20 / BSC`)\n"
            "• **Binance Pay ID / Correo:**\n"
            "```\nbinancedenzelxt@gmail.com\n```\n"
            "*(También puedes solicitar el Pay ID numérico directo en este ticket)*"
        ),
        inline=False
    )

    embed.add_field(
        name="🅿️ 2. PayPal Internacional",
        value=(
            "• **Modalidad Obligatoria:** Enviar únicamente como **\"Amigos y Familiares\"** (Friends & Family).\n"
            "• **Correo / Link:** Solicita el enlace activo al vendedor en este ticket para evitar retenciones."
        ),
        inline=False
    )

    embed.add_field(
        name="🇲🇽 3. México (Transferencia SPEI / Depósito OXXO)",
        value=(
            "• Depósito en efectivo en cualquier tienda **OXXO / 7-Eleven**.\n"
            "• Transferencia bancaria directa vía **CLABE interbancaria (SPEI)** con acreditación inmediata."
        ),
        inline=False
    )

    embed.add_field(
        name="🇨🇴 4. Colombia y Otros Países de Latinoamérica",
        value=(
            "• **Colombia:** Nequi, Bancolombia, Daviplata.\n"
            "• **Internacional:** Western Union o transferencias locales.\n"
            "• *(Consulta al vendedor en este ticket para recibir los datos de tu país)*"
        ),
        inline=False
    )

    embed.add_field(
        name="⚠️ PASOS TRAS REALIZAR EL PAGO:",
        value=(
            "1️⃣ Guarda tu comprobante o recibo de pago.\n"
            "2️⃣ Envíalo como imagen aquí en tu ticket.\n"
            "3️⃣ El staff verificará el abono y te entregará tu producto y rol VIP al instante."
        ),
        inline=False
    )

    embed.set_footer(
        text="Denzel XT • Ventas oficiales • Atención Inmediata 24/7",
        icon_url=guild.icon.url if (guild and guild.icon) else None
    )

    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label="⭐ Dejar Referencia tras Recibir",
            style=discord.ButtonStyle.success,
            emoji="💎",
            custom_id="ticket_btn_vouch"
        )
    )
    return embed, view


class ReviewModal(discord.ui.Modal, title="⭐ Calificar Servicio / Referencia"):
    stars_input = discord.ui.TextInput(
        label="Calificación en Estrellas (1 al 5):",
        placeholder="Escribe un número del 1 al 5 (ej: 5)",
        default="5",
        min_length=1,
        max_length=5,
        required=True
    )
    product_input = discord.ui.TextInput(
        label="Producto Adquirido:",
        placeholder="Ej: Panel iOS, Complex PC, Proxy, Key BR Mods...",
        style=discord.TextStyle.short,
        min_length=2,
        max_length=60,
        required=True
    )
    comment_input = discord.ui.TextInput(
        label="Tu Reseña u Opinión:",
        placeholder="Describe la rapidez, atención recibida y funcionamiento del producto...",
        style=discord.TextStyle.paragraph,
        min_length=5,
        max_length=800,
        required=True
    )
    proof_input = discord.ui.TextInput(
        label="Enlace de Captura / Prueba (Opcional):",
        placeholder="https://... enlace de captura de pantalla o comprobante",
        style=discord.TextStyle.short,
        required=False,
        max_length=250
    )

    def __init__(self, default_product: str = ""):
        super().__init__()
        if default_product:
            self.product_input.default = default_product

    async def on_submit(self, interaction: discord.Interaction):
        await handle_review_submission(
            interaction=interaction,
            stars_raw=self.stars_input.value,
            product=self.product_input.value,
            comment=self.comment_input.value,
            proof_url=self.proof_input.value.strip() or None
        )


async def handle_review_submission(
    interaction: discord.Interaction,
    stars_raw: str,
    product: str,
    comment: str,
    proof_url: Optional[str] = None,
    attachment: Optional[discord.Attachment] = None
):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ Esta función solo puede ejecutarse en el servidor.", ephemeral=True)
        return

    num_stars = 5
    m = re.search(r'([1-5])', stars_raw)
    if m:
        num_stars = int(m.group(1))
    elif "⭐" in stars_raw:
        num_stars = max(1, min(5, stars_raw.count("⭐")))

    stars_display = "⭐" * num_stars + f" ({num_stars}/5 Estrellas)"
    rating_texts = {
        5: "Excelente • Servicio Recomendado 🚀",
        4: "Muy Bueno • Conforme 👍",
        3: "Bueno • Aceptable 👌",
        2: "Regular ⚠️",
        1: "Insatisfecho ❌"
    }
    rating_desc = rating_texts.get(num_stars, "Verificado ✅")

    embed = discord.Embed(
        title="💎 NUEVA REFERENCIA DE CLIENTE VERIFICADA ⭐",
        description=(
            f"👤 **Cliente:** {interaction.user.mention} (`{interaction.user.name}`)\n"
            f"⭐ **Calificación:** {stars_display}\n"
            f"✨ **Experiencia:** *{rating_desc}*\n\n"
            f"🛒 **Producto Adquirido:** **{product}**\n\n"
            f"💬 **Reseña del Cliente:**\n"
            f"*{comment}*"
        ),
        color=discord.Color.from_rgb(0, 230, 118),
        timestamp=discord.utils.utcnow()
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.set_footer(
        text="Denzel XT • Referencias Oficiales • Compra 100% Segura y Verificada",
        icon_url=guild.icon.url if guild.icon else None
    )

    if attachment:
        embed.set_image(url=attachment.url)
    elif proof_url and (proof_url.startswith("http://") or proof_url.startswith("https://")):
        embed.set_image(url=proof_url)

    target_channel = guild.get_channel(REFERENCES_CHANNEL_ID)
    if not target_channel:
        target_channel = (
            discord.utils.get(guild.text_channels, name="💎𝐑𝐄𝐅𝐄𝐑𝐄𝐍𝐂𝐈𝐀𝐒")
            or discord.utils.get(guild.text_channels, name="referencias")
        )

    if target_channel:
        try:
            await target_channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Error enviando reseña a canal de referencias: {e}")

    if not interaction.response.is_done():
        await interaction.response.send_message(
            f"✅ **¡Muchas gracias por tu reseña, {interaction.user.mention}!**\n"
            f"Tu calificación ha sido publicada en el canal oficial de referencias: <#{REFERENCES_CHANNEL_ID}> 💎",
            ephemeral=True
        )
    else:
        await interaction.followup.send(
            f"✅ **¡Muchas gracias por tu reseña!** Publicada en <#{REFERENCES_CHANNEL_ID}> 💎",
            ephemeral=True
        )

    try:
        bot_client = interaction.client
        await bot_client.log_security_event(
            guild=guild,
            title="💎 Nueva Referencia de Cliente Registrada",
            description=(
                f"👤 **Cliente:** {interaction.user.mention} (`{interaction.user.name}`)\n"
                f"⭐ **Calificación:** {stars_display}\n"
                f"📦 **Producto:** `{product}`\n"
                f"📝 **Comentario:** {comment[:120]}..."
            ),
            color=discord.Color.gold(),
            thumbnail=interaction.user.display_avatar.url
        )
    except Exception as e:
        logger.warning(f"Aviso registrando vouch en logs: {e}")


# ==========================================
# 🎁 VISTA INTERACTIVA DE SORTEOS CON BOTONES
# ==========================================

class GiveawayView(discord.ui.View):
    """Vista interactiva con botón de participar y contador para sorteos."""
    def __init__(self, giveaway_id: str, participant_count: int = 0):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

        self.join_btn = discord.ui.Button(
            label=f"🎉 Participar ({participant_count})",
            style=discord.ButtonStyle.success,
            custom_id=f"giveaway_join:{giveaway_id}"
        )
        self.join_btn.callback = self.join_callback
        self.add_item(self.join_btn)

        self.list_btn = discord.ui.Button(
            label="👥 Participantes",
            style=discord.ButtonStyle.secondary,
            custom_id=f"giveaway_list:{giveaway_id}"
        )
        self.list_btn.callback = self.list_callback
        self.add_item(self.list_btn)

    async def join_callback(self, interaction: discord.Interaction):
        await handle_giveaway_join(interaction, self.giveaway_id)

    async def list_callback(self, interaction: discord.Interaction):
        await handle_giveaway_list(interaction, self.giveaway_id)


async def handle_giveaway_join(interaction: discord.Interaction, giveaway_id: str):
    bot_client = interaction.client
    success, total_count, is_joined = await bot_client.giveaway_manager.toggle_participant(giveaway_id, interaction.user.id)
    if not success:
        await interaction.response.send_message("❌ Este sorteo ya no se encuentra activo o ha finalizado.", ephemeral=True)
        return

    gw = bot_client.giveaway_manager.get_giveaway(giveaway_id)
    prize = gw.get("prize", "Premio") if gw else "Premio"

    try:
        msg = interaction.message
        if msg:
            new_view = GiveawayView(giveaway_id, total_count)
            if msg.embeds:
                old_embed = msg.embeds[0]
                new_embed = discord.Embed.from_dict(old_embed.to_dict())
                for i, field in enumerate(new_embed.fields):
                    if "Participantes" in field.name:
                        new_embed.set_field_at(i, name=field.name, value=f"**{total_count} miembros**", inline=field.inline)
                        break
                await msg.edit(embed=new_embed, view=new_view)
            else:
                await msg.edit(view=new_view)
    except Exception as e:
        logger.warning(f"Aviso actualizando botón de sorteo: {e}")

    if is_joined:
        await interaction.response.send_message(
            f"🎉 **¡Estás participando oficialmente en el sorteo!**\n"
            f"🎁 **Premio:** **{prize}**\n"
            f"👥 **Total de participantes:** **{total_count}**\n\n"
            f"¡Mucha suerte! Te avisaremos si resultas ganador. 🍀",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"👋 Has cancelado tu participación en el sorteo de **{prize}**.",
            ephemeral=True
        )


async def handle_giveaway_list(interaction: discord.Interaction, giveaway_id: str):
    bot_client = interaction.client
    gw = bot_client.giveaway_manager.get_giveaway(giveaway_id)
    if not gw:
        await interaction.response.send_message("❌ Este sorteo ya no se encuentra activo o ha finalizado.", ephemeral=True)
        return

    participants = gw.get("participants", [])
    prize = gw.get("prize", "Premio")

    if not participants:
        await interaction.response.send_message(
            f"ℹ️ **Sorteo:** {prize}\nActualmente no hay ningún miembro participando. ¡Sé el primero en hacer clic en **🎉 Participar**!",
            ephemeral=True
        )
        return

    member_mentions = [f"<@{uid}>" for uid in participants[:30]]
    more = ""
    if len(participants) > 30:
        more = f"\n*... y {len(participants) - 30} participantes más.*"

    embed = discord.Embed(
        title=f"👥 Lista de Participantes ({len(participants)})",
        description=(
            f"🎁 **Premio:** **{prize}**\n\n"
            f"**Participantes registrados:**\n"
            + ", ".join(member_mentions)
            + more
        ),
        color=discord.Color.from_rgb(0, 230, 118)
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


class TicketCloseView(discord.ui.View):
    """Botones persistentes en el ticket para cerrar, consultar pagos y calificar."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Cerrar Ticket",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="ticket_btn_close",
        row=0
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

    @discord.ui.button(
        label="Métodos de Pago",
        style=discord.ButtonStyle.primary,
        emoji="💳",
        custom_id="ticket_btn_payments",
        row=0
    )
    async def view_payments(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed, view = create_payment_methods_embed(interaction.guild)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="Dejar Referencia",
        style=discord.ButtonStyle.success,
        emoji="⭐",
        custom_id="ticket_btn_vouch",
        row=0
    )
    async def leave_review(self, interaction: discord.Interaction, button: discord.ui.Button):
        default_prod = ""
        if interaction.channel and getattr(interaction.channel, "topic", None):
            topic = interaction.channel.topic
            if "Producto:" in topic:
                default_prod = topic.split("Producto:")[-1].strip()
        modal = ReviewModal(default_product=default_prod)
        await interaction.response.send_modal(modal)


# ==========================================
# 🎁 PANEL OFICIAL DE KEYS GRATIS Y RECOMPENSAS
# ==========================================

class FreeKeysPanelView(discord.ui.View):
    """Botones interactivos en el canal de Keys Gratis para consultar invitaciones y reclamar."""
    def __init__(self, ticket_channel_id: int = TICKET_CHANNEL_ID, guild_id: int = GUILD_ID):
        super().__init__(timeout=None)
        self.ticket_channel_id = ticket_channel_id
        self.guild_id = guild_id

        # Botón para consultar las invitaciones propias
        self.btn_my_invites = discord.ui.Button(
            label="🎟️ Mis Invitaciones",
            style=discord.ButtonStyle.success,
            custom_id="keys_panel_my_invites",
            row=0
        )
        self.btn_my_invites.callback = self.my_invites_callback
        self.add_item(self.btn_my_invites)

        # Botón para ver el Top 10 del servidor
        self.btn_top = discord.ui.Button(
            label="🏆 Top Invitadores",
            style=discord.ButtonStyle.secondary,
            custom_id="keys_panel_top_invites",
            row=0
        )
        self.btn_top.callback = self.top_callback
        self.add_item(self.btn_top)

        # Botón directo para reclamar abriendo ticket
        channel_url = f"https://discord.com/channels/{guild_id}/{ticket_channel_id}"
        self.btn_ticket = discord.ui.Button(
            label="🎫 Reclamar Key en Ticket",
            url=channel_url,
            style=discord.ButtonStyle.link,
            emoji="🎁",
            row=0
        )
        self.add_item(self.btn_ticket)

    async def my_invites_callback(self, interaction: discord.Interaction):
        bot_client = interaction.client
        stats = bot_client.invite_manager.get_stats(interaction.user.id)
        total = stats.get("total", 0)
        active = stats.get("active", 0)
        leaves = stats.get("leaves", 0)

        falta = max(0, 5 - active)
        if falta == 0:
            progreso_txt = f"🎉 **¡Felicidades! Ya tienes {active} invitaciones activas.** Abre un ticket en <#{self.ticket_channel_id}> para reclamar tu Key de 1 Día de BR Mods."
        else:
            progreso_txt = f"⏳ Llevas **{active}/5 invitaciones activas**. Te faltan **{falta}** para tu **Key de 1 Día de BR Mods**."

        embed = discord.Embed(
            title="🎟️ Tus Estadísticas de Invitación",
            description=(
                f"👤 **Usuario:** {interaction.user.mention}\n\n"
                f"📈 **Total Invitados:** **{total} personas**\n"
                f"✅ **Miembros Activos:** **{active} personas**\n"
                f"🚪 **Han salido:** **{leaves} personas**\n\n"
                f"{progreso_txt}\n\n"
                f"🔗 **Comparte tu enlace de invitación:**\n"
                f"Invita amigos a {PERMANENT_INVITE_URL} para seguir acumulando recompensas."
            ),
            color=discord.Color.from_rgb(0, 230, 118)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def top_callback(self, interaction: discord.Interaction):
        bot_client = interaction.client
        top_list = bot_client.invite_manager.get_top_inviters(limit=10)
        guild = interaction.guild

        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        lines = []
        for i, (uid, stats) in enumerate(top_list):
            medal = medals[i] if i < len(medals) else f"`#{i+1}`"
            user = guild.get_member(uid) if guild else None
            name_str = user.mention if user else f"`ID {uid}`"
            act = stats.get("active", 0)
            tot = stats.get("total", 0)
            lines.append(f"{medal} {name_str} — **{act} activos** *(Total: {tot})*")

        if not lines:
            lines.append("Aún no hay invitaciones registradas en el nuevo sistema.")

        embed = discord.Embed(
            title="🏆 TOP 10 INVITADORES DEL SERVIDOR 🏆",
            description=(
                "¡Los miembros con más personas invitadas a **Denzel XT**!\n\n"
                + "\n".join(lines) + "\n\n"
                f"👉 ¡Invita a tus amigos y gana keys gratuitas semanales!"
            ),
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


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

        # Canales y Roles Nuevos
        self.references_channel_id = REFERENCES_CHANNEL_ID
        self.lives_channel_id = LIVES_CHANNEL_ID
        self.free_keys_channel_id = FREE_KEYS_CHANNEL_ID
        self.customer_role_id = CUSTOMER_ROLE_ID
        self.reseller_role_id = RESELLER_ROLE_ID

        # Gestores de Crecimiento y Sorteos
        self.invite_manager = InviteManager()
        self.giveaway_manager = GiveawayManager()
        self.invites_cache = {}

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
        self.add_view(FreeKeysPanelView())
        logger.info("🧩 Vistas persistentes del Sistema de Tickets y Keys registradas correctamente.")

        # Iniciar servidor de salud HTTP de inmediato para Railway
        await self.start_cloud_health_server()

    async def on_interaction(self, interaction: discord.Interaction):
        """Monitoreo de interacciones en tiempo real y fallback de botones persistentes."""
        logger.info(f"📥 Interacción recibida | Usuario: {interaction.user.name} | Tipo: {interaction.type.name}")

        if interaction.type == discord.InteractionType.component and interaction.data:
            custom_id = interaction.data.get("custom_id", "")

            # 1. BOTONES DE SORTEOS (PARTICIPAR / VER PARTICIPANTES)
            if custom_id.startswith("giveaway_join:"):
                gw_id = custom_id.split(":", 1)[1]
                await handle_giveaway_join(interaction, gw_id)
                return
            elif custom_id.startswith("giveaway_list:"):
                gw_id = custom_id.split(":", 1)[1]
                await handle_giveaway_list(interaction, gw_id)
                return

            # 2. BOTONES EN TICKETS (PAGOS / REFERENCIA)
            elif custom_id == "ticket_btn_payments":
                embed, view = create_payment_methods_embed(interaction.guild)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            elif custom_id == "ticket_btn_vouch":
                default_prod = ""
                if interaction.channel and getattr(interaction.channel, "topic", None):
                    topic = interaction.channel.topic
                    if "Producto:" in topic:
                        default_prod = topic.split("Producto:")[-1].strip()
                modal = ReviewModal(default_product=default_prod)
                await interaction.response.send_modal(modal)
                return

            # 3. BOTONES DEL PANEL DE KEYS GRATIS Y RECOMPENSAS
            elif custom_id == "keys_panel_my_invites":
                stats = self.invite_manager.get_stats(interaction.user.id)
                total = stats.get("total", 0)
                active = stats.get("active", 0)
                leaves = stats.get("leaves", 0)
                falta = max(0, 5 - active)
                if falta == 0:
                    progreso_txt = f"🎉 **¡Felicidades! Ya tienes {active} invitaciones activas.** Abre un ticket en <#{self.ticket_channel_id}> para reclamar tu Key de 1 Día de BR Mods."
                else:
                    progreso_txt = f"⏳ Llevas **{active}/5 invitaciones activas**. Te faltan **{falta}** para tu **Key de 1 Día de BR Mods**."

                embed = discord.Embed(
                    title="🎟️ Tus Estadísticas de Invitación",
                    description=(
                        f"👤 **Usuario:** {interaction.user.mention}\n\n"
                        f"📈 **Total Invitados:** **{total} personas**\n"
                        f"✅ **Miembros Activos:** **{active} personas**\n"
                        f"🚪 **Han salido:** **{leaves} personas**\n\n"
                        f"{progreso_txt}\n\n"
                        f"🔗 **Comparte tu enlace de invitación:**\n"
                        f"Invita amigos a {self.permanent_invite_url} para seguir acumulando recompensas."
                    ),
                    color=discord.Color.from_rgb(0, 230, 118)
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            elif custom_id == "keys_panel_top_invites":
                top_list = self.invite_manager.get_top_inviters(limit=10)
                guild = interaction.guild
                medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
                lines = []
                for i, (uid, stats) in enumerate(top_list):
                    medal = medals[i] if i < len(medals) else f"`#{i+1}`"
                    user = guild.get_member(uid) if guild else None
                    name_str = user.mention if user else f"`ID {uid}`"
                    act = stats.get("active", 0)
                    tot = stats.get("total", 0)
                    lines.append(f"{medal} {name_str} — **{act} activos** *(Total: {tot})*")

                if not lines:
                    lines.append("Aún no hay invitaciones registradas en el nuevo sistema.")

                embed = discord.Embed(
                    title="🏆 TOP 10 INVITADORES DEL SERVIDOR 🏆",
                    description=(
                        "¡Los miembros con más personas invitadas a **Denzel XT**!\n\n"
                        + "\n".join(lines) + "\n\n"
                        f"👉 ¡Invita a tus amigos y gana keys gratuitas semanales!"
                    ),
                    color=discord.Color.gold()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # 3. VERIFICACIÓN Y AUTORIZACIÓN DE BOTS
            elif custom_id.startswith("bot_auth_verify:"):
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

    def create_free_keys_panel_content(self, guild: Optional[discord.Guild] = None) -> tuple[discord.Embed, discord.ui.View]:
        """Crea el Embed y Botones para el canal de Keys Gratis y Recompensas por Invites."""
        embed = discord.Embed(
            title="🎁 KEYS GRATIS & RECOMPENSAS POR INVITACIONES • DENZEL XT 💸",
            description=(
                "¡En **Denzel XT** premiamos a nuestra comunidad con **Keys 100% Gratis de BR Mods**, paneles y descuentos exclusivos! 🔥\n\n"
                "Hay dos formas automáticas y 100% seguras de conseguir keys sin pagar nada:\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🎉 **1. SORTEOS AUTOMÁTICOS DE KEYS:**\n"
                "• El Staff y el bot publican periódicamente sorteos en este mismo canal.\n"
                "• Cada vez que veas un sorteo activo, presiona el botón verde **🎉 Participar**.\n"
                "• El bot seleccionará a los ganadores al azar de forma 100% transparente.\n\n"
                "🎟️ **2. PROGRAMA DE RECOMPENSAS POR INVITAR:**\n"
                "¡Invita a tus amigos al servidor con tu link y gana premios inmediatos!\n"
                "• 🎁 **5 Invitaciones activas:** Key de **1 Día de BR Mods** GRATIS.\n"
                "• 💎 **10 Invitaciones activas:** Descuento del **20%** en cualquier Panel VIP.\n"
                "• 🚀 **20 Invitaciones activas:** Key **Semanal Completa** de Complex PC o BR Mods.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📌 **¿CÓMO RECLAMAR TU KEY?**\n"
                f"1️⃣ Comparte tu enlace de invitación o el permanente: {self.permanent_invite_url}\n"
                "2️⃣ Presiona el botón **🎟️ Mis Invitaciones** abajo para verificar cuántos amigos llevas.\n"
                f"3️⃣ Cuando llegues a 5 o más, abre un ticket en <#{self.ticket_channel_id}> y el staff te entregará tu key."
            ),
            color=discord.Color.from_rgb(0, 255, 170)
        )
        embed.set_footer(
            text="Denzel XT • Keys y Sorteos Oficiales • 100% Transparentes",
            icon_url=guild.icon.url if (guild and guild.icon) else None
        )

        view = FreeKeysPanelView(ticket_channel_id=self.ticket_channel_id, guild_id=self.guild_id)
        return embed, view

    async def ensure_free_keys_panel(self):
        """Verifica si el panel de keys gratis e invites está publicado en el canal asignado; si no, lo envía o actualiza."""
        try:
            target_id = self.free_keys_channel_id
            channel = self.get_channel(target_id)
            if not channel:
                try:
                    channel = await self.fetch_channel(target_id)
                except Exception as e:
                    logger.warning(f"⚠️ No se pudo acceder al canal de keys (ID: {target_id}): {e}")
                    return

            panel_found = False
            async for msg in channel.history(limit=25):
                if msg.author.id == self.user.id and msg.embeds:
                    for emb in msg.embeds:
                        if emb.title and "KEYS GRATIS & RECOMPENSAS" in emb.title:
                            panel_found = True
                            try:
                                embed, view = self.create_free_keys_panel_content(channel.guild)
                                if os.path.exists(BANNER_IMAGE_PATH):
                                    embed.set_image(url="attachment://denzel_banner.jpg")
                                await msg.edit(embed=embed, view=view)
                                logger.info(f"🎁 Panel de Keys Gratis en #{channel.name} (ID: {msg.id}) actualizado correctamente.")
                            except Exception as e:
                                logger.warning(f"Aviso actualizando panel de keys: {e}")
                            break
                if panel_found:
                    break

            if not panel_found:
                embed, view = self.create_free_keys_panel_content(channel.guild)
                if os.path.exists(BANNER_IMAGE_PATH):
                    file = discord.File(BANNER_IMAGE_PATH, filename="denzel_banner.jpg")
                    embed.set_image(url="attachment://denzel_banner.jpg")
                    await channel.send(file=file, embed=embed, view=view)
                else:
                    await channel.send(embed=embed, view=view)
                logger.info(f"📨 Panel oficial de Keys Gratis publicado exitosamente en #{channel.name} ({channel.id}).")
        except Exception as e:
            logger.error(f"❌ Error al revisar/publicar panel de keys: {e}")

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

        @self.tree.command(name="panel_keys", description="Publica el panel oficial de keys gratis y recompensas por invites")
        @app_commands.describe(canal="Canal donde publicar el panel (opcional, por defecto el canal de Keys Gratis)")
        @app_commands.default_permissions(administrator=True)
        async def panel_keys_cmd(interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None):
            target = canal or self.get_channel(self.free_keys_channel_id) or interaction.channel
            embed, view = self.create_free_keys_panel_content(interaction.guild)
            if os.path.exists(BANNER_IMAGE_PATH):
                file = discord.File(BANNER_IMAGE_PATH, filename="denzel_banner.jpg")
                embed.set_image(url="attachment://denzel_banner.jpg")
                await target.send(file=file, embed=embed, view=view)
            else:
                await target.send(embed=embed, view=view)
            await interaction.response.send_message(f"✅ Panel de Keys Gratis publicado en {target.mention}.", ephemeral=True)

        @self.tree.command(name="enviar_anuncio", description="Publica el anuncio de venta de paneles y mods en el canal de anuncios")
        @app_commands.describe(canal="Canal donde publicar el anuncio (opcional, por defecto el canal de anuncios)")
        @app_commands.default_permissions(administrator=True)
        async def announcement_cmd(interaction: discord.Interaction, canal: Optional[discord.TextChannel] = None):
            target = canal or self.get_channel(self.announcement_channel_id) or interaction.channel
            embed, view = self.create_announcement_content(interaction.guild)
            await target.send(embed=embed, view=view)
            await interaction.response.send_message(f"✅ Anuncio de compra publicado con éxito en {target.mention}.", ephemeral=True)

        # 1. COMANDO /pagos
        @self.tree.command(name="pagos", description="Muestra los métodos de pago oficiales de Denzel XT con datos para copiar")
        async def pagos_cmd(interaction: discord.Interaction):
            embed, view = create_payment_methods_embed(interaction.guild)
            await interaction.response.send_message(embed=embed, view=view)

        # 2. COMANDO /referencia
        @self.tree.command(name="referencia", description="Deja tu reseña y calificación del servicio y productos de Denzel XT")
        @app_commands.describe(
            estrellas="Calificación de 1 a 5 estrellas",
            producto="Producto adquirido (ej: Panel iOS, Complex PC, BR Mods, Proxy)",
            comentario="Tu opinión sobre la atención y el producto recibido",
            captura="Captura de pantalla o comprobante opcional de tu entrega/juego"
        )
        @app_commands.choices(estrellas=[
            app_commands.Choice(name="⭐⭐⭐⭐⭐ 5 Estrellas (Excelente)", value="5"),
            app_commands.Choice(name="⭐⭐⭐⭐ 4 Estrellas (Muy Bueno)", value="4"),
            app_commands.Choice(name="⭐⭐⭐ 3 Estrellas (Bueno)", value="3"),
            app_commands.Choice(name="⭐⭐ 2 Estrellas (Regular)", value="2"),
            app_commands.Choice(name="⭐ 1 Estrella (Malo)", value="1"),
        ])
        async def referencia_cmd(
            interaction: discord.Interaction,
            estrellas: app_commands.Choice[str],
            producto: str,
            comentario: str,
            captura: Optional[discord.Attachment] = None
        ):
            await handle_review_submission(
                interaction=interaction,
                stars_raw=estrellas.value,
                product=producto,
                comment=comentario,
                proof_url=None,
                attachment=captura
            )

        # 3. COMANDO /entregar
        @self.tree.command(name="entregar", description="Entrega un producto al cliente, le asigna rol VIP y envía botón de reseña")
        @app_commands.describe(
            cliente="Miembro al que se le entregó el producto",
            producto="Nombre del producto entregado (ej: Panel iOS Mes, Complex PC Perma, Key BR Mods)",
            nota="Mensaje o instrucción adicional para el cliente (opcional)"
        )
        async def entregar_cmd(
            interaction: discord.Interaction,
            cliente: discord.Member,
            producto: str,
            nota: Optional[str] = None
        ):
            if not is_user_staff_or_owner(interaction.user, interaction.guild):
                await interaction.response.send_message(
                    "⛔ **Acceso Denegado:** Solo los miembros del **Staff / Vendedores** pueden utilizar el comando de entrega.",
                    ephemeral=True
                )
                return

            guild = interaction.guild
            customer_role = guild.get_role(self.customer_role_id) if guild else None
            role_assigned_text = "Rol no configurado"

            if customer_role and cliente:
                try:
                    if customer_role not in cliente.roles:
                        await cliente.add_roles(customer_role, reason=f"Entrega de producto por {interaction.user.name}")
                    role_assigned_text = f"{customer_role.mention} ✅"
                except Exception as e:
                    role_assigned_text = f"Error asignando rol ({e})"

            if "br" in producto.lower() or "reseller" in producto.lower():
                reseller_role = guild.get_role(self.reseller_role_id) if guild else None
                if reseller_role and cliente and reseller_role not in cliente.roles:
                    try:
                        await cliente.add_roles(reseller_role, reason=f"Rol Reseller por {interaction.user.name}")
                    except Exception:
                        pass

            embed = discord.Embed(
                title="🎉 ¡ENTREGA COMPLETADA CON ÉXITO! 💸",
                description=(
                    f"👋 ¡Muchas gracias por tu compra en **Denzel XT**!\n\n"
                    f"👤 **Cliente:** {cliente.mention} (`{cliente.name}`)\n"
                    f"📦 **Producto Entregado:** **{producto}**\n"
                    f"👑 **Vendedor:** {interaction.user.mention}\n"
                    f"🎖️ **Rango Otorgado:** {role_assigned_text}\n"
                    + (f"💬 **Nota del Vendedor:** *{nota}*\n\n" if nota else "\n") +
                    f"⭐ **¿Qué tal fue tu experiencia?**\n"
                    f"Por favor ayuda a la comunidad dejando tu calificación y reseña con el botón verde de abajo:"
                ),
                color=discord.Color.from_rgb(0, 255, 170),
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=cliente.display_avatar.url)
            embed.set_footer(
                text="Denzel XT • Garantía y Soporte 24/7",
                icon_url=guild.icon.url if (guild and guild.icon) else None
            )

            view = discord.ui.View(timeout=None)
            view.add_item(
                discord.ui.Button(
                    label="⭐ Dejar Referencia / Calificar",
                    style=discord.ButtonStyle.success,
                    emoji="💎",
                    custom_id="ticket_btn_vouch"
                )
            )

            if os.path.exists(BANNER_IMAGE_PATH):
                file = discord.File(BANNER_IMAGE_PATH, filename="denzel_banner.jpg")
                embed.set_image(url="attachment://denzel_banner.jpg")
                await interaction.channel.send(content=f"🎉 {cliente.mention}", file=file, embed=embed, view=view)
            else:
                await interaction.channel.send(content=f"🎉 {cliente.mention}", embed=embed, view=view)

            await interaction.response.send_message(
                f"✅ Entrega de **{producto}** registrada correctamente para {cliente.mention}.",
                ephemeral=True
            )

            try:
                await self.log_security_event(
                    guild=guild,
                    title="💰 Venta Registrada & Producto Entregado",
                    description=(
                        f"👤 **Cliente:** {cliente.mention} (`{cliente.name}` - `{cliente.id}`)\n"
                        f"📦 **Producto:** `{producto}`\n"
                        f"👑 **Vendedor:** {interaction.user.mention}\n"
                        f"📁 **Canal:** {interaction.channel.mention}"
                    ),
                    color=discord.Color.green(),
                    thumbnail=cliente.display_avatar.url
                )
            except Exception as e:
                logger.warning(f"Aviso registrando entrega en logs: {e}")

        # 4. COMANDO /invites
        @self.tree.command(name="invites", description="Consulta cuántas personas ha invitado un usuario al servidor")
        @app_commands.describe(usuario="Usuario a consultar (opcional, por defecto tú mismo)")
        async def invites_cmd(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
            target = usuario or interaction.user
            stats = self.invite_manager.get_stats(target.id)
            total = stats.get("total", 0)
            active = stats.get("active", 0)
            leaves = stats.get("leaves", 0)

            embed = discord.Embed(
                title=f"🎟️ Contador de Invitaciones | Denzel XT",
                description=(
                    f"Estadísticas de invitaciones oficiales de {target.mention}:\n\n"
                    f"📈 **Total Invitados:** **{total} miembros**\n"
                    f"✅ **Miembros Activos:** **{active} miembros**\n"
                    f"🚪 **Miembros que Salieron:** **{leaves}**\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎁 **RECOMPENSAS POR INVITAR:**\n"
                    f"• 🎟️ **5 Invitaciones:** Key de 1 Día de **BR Mods** en <#{self.free_keys_channel_id}>\n"
                    f"• 💎 **10 Invitaciones:** Descuento del **20%** en cualquier Panel VIP\n"
                    f"• 🚀 **20 Invitaciones:** Key **Semanal Completa** de Complex PC o BR Mods"
                ),
                color=discord.Color.from_rgb(0, 230, 118)
            )
            embed.set_thumbnail(url=target.display_avatar.url)
            embed.set_footer(
                text="Denzel XT • Invita amigos y gana recompensas semanales",
                icon_url=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None
            )
            await interaction.response.send_message(embed=embed)

        # 5. COMANDO /top_invites
        @self.tree.command(name="top_invites", description="Muestra el Ranking Top 10 de miembros con más invitaciones en el servidor")
        async def top_invites_cmd(interaction: discord.Interaction):
            top_list = self.invite_manager.get_top_inviters(limit=10)
            guild = interaction.guild

            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            lines = []
            for i, (uid, stats) in enumerate(top_list):
                medal = medals[i] if i < len(medals) else f"`#{i+1}`"
                user = guild.get_member(uid) if guild else None
                name_str = user.mention if user else f"`ID {uid}`"
                act = stats.get("active", 0)
                tot = stats.get("total", 0)
                lines.append(f"{medal} {name_str} — **{act} activos** *(Total: {tot})*")

            if not lines:
                lines.append("Aún no hay invitaciones registradas en el nuevo sistema.")

            embed = discord.Embed(
                title="🏆 TOP 10 INVITADORES DEL SERVIDOR 🏆",
                description=(
                    "¡Los miembros que más están haciendo crecer a la comunidad de **Denzel XT**!\n\n"
                    + "\n".join(lines) + "\n\n"
                    f"👉 ¡Usa `/invites` para ver tus invitaciones y ganar keys gratis!"
                ),
                color=discord.Color.gold(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(
                text="Denzel XT • Ranking Oficial de Crecimiento",
                icon_url=guild.icon.url if guild and guild.icon else None
            )
            await interaction.response.send_message(embed=embed)

        # 6. COMANDO /sorteo
        @self.tree.command(name="sorteo", description="Crea un sorteo interactivo con botón de participar y contador para keys")
        @app_commands.describe(
            premio="Premio a sortear (ej: Key Semanal BR Mods, Key 1 Día Complex PC)",
            minutos="Duración del sorteo en minutos (ej: 60 para 1 hora, 1440 para 24 horas)",
            ganadores="Cantidad de ganadores a elegir al azar (por defecto 1)",
            canal="Canal donde publicar el sorteo (por defecto el canal de Keys Gratis)"
        )
        async def sorteo_cmd(
            interaction: discord.Interaction,
            premio: str,
            minutos: int,
            ganadores: Optional[int] = 1,
            canal: Optional[discord.TextChannel] = None
        ):
            if not is_user_staff_or_owner(interaction.user, interaction.guild):
                await interaction.response.send_message(
                    "⛔ **Acceso Denegado:** Solo los miembros del **Staff u Owner** pueden iniciar sorteos.",
                    ephemeral=True
                )
                return

            target_ch = (
                canal
                or interaction.guild.get_channel(self.free_keys_channel_id)
                or discord.utils.get(interaction.guild.text_channels, name="𝙆𝙀𝙔-𝙂𝙍𝘼𝙏𝙄𝙎-𝘽𝙍-𝙈𝙊𝘿𝙎")
                or discord.utils.get(interaction.guild.text_channels, name="𝙆𝙀𝙔𝙎-𝙂𝙍𝘼𝙏𝙄𝙎")
                or interaction.channel
            )
            now = time.time()
            duration_sec = max(60, minutos * 60)
            end_time = now + duration_sec
            end_timestamp = int(end_time)
            gw_id = f"gw_{int(now)}_{random.randint(100, 999)}"
            winners_count = max(1, ganadores or 1)

            embed = discord.Embed(
                title="🎉 ¡SORTEO OFICIAL DE KEY / MEMBRESÍA! 🎉",
                description=(
                    f"¡Participa por una **{premio}** totalmente gratis!\n\n"
                    f"🎁 **Premio:** **{premio}**\n"
                    f"🏆 **Ganadores:** **{winners_count}**\n"
                    f"👑 **Organizado por:** {interaction.user.mention}\n"
                    f"⏰ **Finaliza en:** <t:{end_timestamp}:R> (<t:{end_timestamp}:F>)\n"
                    f"👥 **Participantes:** **0 miembros**\n\n"
                    f"👉 **¿Cómo participar?**\n"
                    f"Solo presiona el botón verde **🎉 Participar** de abajo. ¡El bot elegirá a los ganadores de forma 100% transparente y automática!"
                ),
                color=discord.Color.from_rgb(0, 255, 136),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(
                text="Denzel XT • Sorteos Oficiales • 100% Transparente",
                icon_url=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None
            )

            view = GiveawayView(giveaway_id=gw_id, participant_count=0)

            if os.path.exists(BANNER_IMAGE_PATH):
                file = discord.File(BANNER_IMAGE_PATH, filename="denzel_banner.jpg")
                embed.set_image(url="attachment://denzel_banner.jpg")
                gw_msg = await target_ch.send(content="🎉 @everyone ¡HAY UN NUEVO SORTEO ACTIVO! 🎉", file=file, embed=embed, view=view)
            else:
                gw_msg = await target_ch.send(content="🎉 @everyone ¡HAY UN NUEVO SORTEO ACTIVO! 🎉", embed=embed, view=view)

            await self.giveaway_manager.create_giveaway(
                giveaway_id=gw_id,
                channel_id=target_ch.id,
                message_id=gw_msg.id,
                prize=premio,
                winners_count=winners_count,
                host_id=interaction.user.id,
                end_time=end_time
            )

            await interaction.response.send_message(
                f"✅ Sorteo de **{premio}** publicado exitosamente en {target_ch.mention}.\n"
                f"Duración: **{minutos} minutos** | Ganadores: **{winners_count}**",
                ephemeral=True
            )

            try:
                await self.log_security_event(
                    guild=interaction.guild,
                    title="🎉 Nuevo Sorteo Iniciado",
                    description=(
                        f"🎁 **Premio:** `{premio}`\n"
                        f"👑 **Organizador:** {interaction.user.mention}\n"
                        f"📁 **Canal:** {target_ch.mention}\n"
                        f"⏰ **Duración:** {minutos} minutos ({winners_count} ganadores)"
                    ),
                    color=discord.Color.green()
                )
            except Exception as e:
                logger.warning(f"Aviso registrando sorteo en logs: {e}")

        # 7. COMANDO /alerta_live
        @self.tree.command(name="alerta_live", description="Publica una alerta en tiempo real de directo en TikTok, YouTube, Twitch o Kick")
        @app_commands.describe(
            plataforma="Plataforma donde se transmite el directo",
            titulo="Título o temática de la transmisión en vivo",
            enlace="Enlace directo a la transmisión (TikTok, YouTube, Twitch, etc.)",
            mencion="Mención para alertar a los miembros"
        )
        @app_commands.choices(
            plataforma=[
                app_commands.Choice(name="📱 TikTok Live", value="TikTok Live"),
                app_commands.Choice(name="🔴 YouTube Live", value="YouTube Live"),
                app_commands.Choice(name="🟣 Twitch", value="Twitch"),
                app_commands.Choice(name="🟢 Kick", value="Kick")
            ],
            mencion=[
                app_commands.Choice(name="📢 @everyone (Toda la comunidad)", value="@everyone"),
                app_commands.Choice(name="🔔 @here (Solo miembros conectados)", value="@here"),
                app_commands.Choice(name="🎙️ Rol STREMER X", value="<@&1552827044012888095>"),
                app_commands.Choice(name="🔇 Sin mención", value="none")
            ]
        )
        async def alerta_live_cmd(
            interaction: discord.Interaction,
            plataforma: app_commands.Choice[str],
            titulo: str,
            enlace: str,
            mencion: Optional[app_commands.Choice[str]] = None
        ):
            if not is_user_staff_or_owner(interaction.user, interaction.guild):
                await interaction.response.send_message(
                    "⛔ **Acceso Denegado:** Solo los miembros del **Staff / Streamers** pueden enviar alertas de directo.",
                    ephemeral=True
                )
                return

            guild = interaction.guild
            target_ch = (
                guild.get_channel(self.lives_channel_id)
                or discord.utils.get(guild.text_channels, name="𝐋𝐈𝐕𝐄𝐒")
                or interaction.channel
            )

            platform_colors = {
                "TikTok Live": discord.Color.from_rgb(254, 44, 85),
                "YouTube Live": discord.Color.from_rgb(255, 0, 0),
                "Twitch": discord.Color.from_rgb(145, 70, 255),
                "Kick": discord.Color.from_rgb(83, 252, 24)
            }
            chosen_color = platform_colors.get(plataforma.value, discord.Color.red())

            embed = discord.Embed(
                title="🔴 ¡ESTAMOS EN DIRECTO AHORA MISMO! 🔴",
                description=(
                    f"🔥 **{interaction.user.name}** ha comenzado transmisión en vivo.\n\n"
                    f"📱 **Plataforma:** **{plataforma.value}**\n"
                    f"🎮 **Transmisión:** **{titulo}**\n\n"
                    f"🚀 **¡Entra ya para apoyar, jugar salas y ganar keys en vivo!**\n"
                    f"👉 Presiona el botón de abajo para unirte al directo inmediatamente."
                ),
                color=chosen_color,
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            embed.set_footer(
                text=f"Denzel XT • Alertas Oficiales de Directo • {plataforma.value}",
                icon_url=guild.icon.url if guild and guild.icon else None
            )

            view = discord.ui.View()
            view.add_item(
                discord.ui.Button(
                    label="🔴 ENTRAR AL DIRECTO AHORA",
                    url=enlace.strip(),
                    style=discord.ButtonStyle.link,
                    emoji="🔥"
                )
            )

            ping_content = ""
            if mencion and mencion.value != "none":
                ping_content = f"{mencion.value} 🔴 **¡ESTAMOS EN VIVO!**"
            else:
                ping_content = "@everyone 🔴 **¡ESTAMOS EN VIVO!**"

            if os.path.exists(BANNER_IMAGE_PATH):
                file = discord.File(BANNER_IMAGE_PATH, filename="denzel_banner.jpg")
                embed.set_image(url="attachment://denzel_banner.jpg")
                await target_ch.send(content=ping_content, file=file, embed=embed, view=view)
            else:
                await target_ch.send(content=ping_content, embed=embed, view=view)

            await interaction.response.send_message(
                f"✅ Alerta de directo publicada exitosamente en {target_ch.mention}.",
                ephemeral=True
            )

            try:
                await self.log_security_event(
                    guild=guild,
                    title="📱 Alerta de Directo Publicada",
                    description=(
                        f"📱 **Plataforma:** `{plataforma.value}`\n"
                        f"🎮 **Título:** `{titulo}`\n"
                        f"🔗 **Enlace:** {enlace}\n"
                        f"👤 **Streamer:** {interaction.user.mention}"
                    ),
                    color=chosen_color
                )
            except Exception as e:
                logger.warning(f"Aviso registrando live en logs: {e}")

    async def start_cloud_health_server(self):
        """Servidor HTTP liviano para Railway/Render."""
        if getattr(self, "_health_server_started", False):
            return
        self._health_server_started = True
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
        logger.info(f"💎 Canal de Referencias: {self.references_channel_id}")
        logger.info(f"📱 Canal de Lives: {self.lives_channel_id}")
        logger.info(f"🎁 Canal de Keys Gratis / Sorteos: {self.free_keys_channel_id}")
        logger.info("🛒 Sistema de Tickets de Compra con Precios: Activo")
        logger.info("🔒 Restricción de Cierre de Tickets (Solo Staff/Owner): Activo")
        logger.info("🛡️ Suite de Protección (Anti-Nuke, Anti-Raid, Anti-Scam): Activa")
        logger.info("=" * 65)

        # Iniciar servidor web de salud para Railway si aplica
        await self.start_cloud_health_server()

        # Cachear invitaciones de servidores para tracking
        for g in self.guilds:
            try:
                invs = await g.invites()
                self.invites_cache[g.id] = {inv.code: inv.uses for inv in invs}
                logger.info(f"🎟️ {len(invs)} invitaciones cacheadas en {g.name}.")
            except Exception as e:
                logger.warning(f"Aviso al cachear invitaciones: {e}")

        # Asegurar canal de seguridad y logs 24/7 (situado arriba de anuncios)
        target_guild = self.get_guild(self.guild_id)
        if target_guild:
            await self.get_or_create_security_logs_channel(target_guild)

        # Asegurar que el panel de tickets esté publicado y actualizado con los precios
        await self.ensure_ticket_panel()

        # Asegurar que el anuncio de venta esté publicado en el canal de anuncios
        await self.ensure_announcement()

        # Asegurar que el panel de keys gratis e invites esté publicado en el canal de keys
        await self.ensure_free_keys_panel()

        # Sincronizar comandos Slash en el servidor
        try:
            guild_obj = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild_obj)
            await self.tree.sync(guild=guild_obj)
            logger.info("⚡ Comandos Slash sincronizados (/tts, /panel_tickets, /panel_keys, /enviar_anuncio, /pagos, /referencia, /entregar, /invites, /top_invites, /sorteo, /alerta_live).")
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
        if not self.giveaway_checker.is_running():
            self.giveaway_checker.start()

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
        try:
            inviter_id = await self.invite_manager.record_leave(member.id)
            if inviter_id:
                logger.info(f"🚪 Miembro {member.name} salió. Descontado de inviter ID {inviter_id}")
        except Exception as e:
            logger.warning(f"Aviso actualizando invitaciones en salida: {e}")

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

        # Rastrear invitación del nuevo miembro
        inviter = None
        try:
            current_invs = await guild.invites()
            cached = self.invites_cache.get(guild.id, {})
            for inv in current_invs:
                if inv.uses > cached.get(inv.code, 0):
                    inviter = inv.inviter
                    break
            self.invites_cache[guild.id] = {inv.code: inv.uses for inv in current_invs}
        except Exception as e:
            logger.debug(f"Aviso revisando invitación de nuevo miembro: {e}")

        if inviter and not inviter.bot and inviter.id != member.id:
            try:
                await self.invite_manager.record_join(inviter.id, member.id)
                logger.info(f"🎟️ {member.name} ingresó mediante invitación de {inviter.name} ({inviter.id})")
            except Exception as e:
                logger.warning(f"Aviso registrando invitador: {e}")

        # Entrada de usuario normal: registrar en logs 24/7
        inviter_line = f"👤 Invitado por: {inviter.mention}\n" if inviter else ""
        await self.log_security_event(
            guild=guild,
            title="📥 Nuevo Miembro Unido",
            description=(
                f"👤 {member.mention} (`{member.name}` - `{member.id}`)\n"
                + inviter_line +
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
                welcome_desc = (
                    f"¡Bienvenido {member.mention}! Eres el miembro **#{guild.member_count}**.\n"
                    + (f"👤 **Invitado por:** {inviter.mention}\n" if inviter else "") +
                    "Esperamos que disfrutes la comunidad y nuestros productos."
                )
                embed_welcome = discord.Embed(
                    title="👋 Bienvenido a 𝑫𝒆𝒏𝒛𝒆𝒍 𝑿𝕿 💵",
                    description=welcome_desc,
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

    @tasks.loop(seconds=15)
    async def giveaway_checker(self):
        """Verifica sorteos activos y sortea automáticamente ganadores al vencer el tiempo."""
        try:
            due_list = self.giveaway_manager.get_due_giveaways()
            for gw in due_list:
                await self.resolve_giveaway(gw)
        except Exception as e:
            logger.error(f"Error en giveaway_checker loop: {e}", exc_info=True)

    async def resolve_giveaway(self, gw: dict):
        """Elige ganadores al azar, actualiza el mensaje y publica el anuncio oficial."""
        giveaway_id = gw["id"]
        channel_id = gw["channel_id"]
        message_id = gw["message_id"]
        prize = gw["prize"]
        winners_count = gw.get("winners_count", 1)
        participants = gw.get("participants", [])

        guild = self.get_guild(self.guild_id)
        if not guild:
            return

        channel = guild.get_channel(channel_id)
        if not channel:
            try:
                channel = await guild.fetch_channel(channel_id)
            except Exception:
                channel = None

        winners = []
        if participants:
            k = min(winners_count, len(participants))
            winners = random.sample(participants, k)

        await self.giveaway_manager.finish_giveaway(giveaway_id, winners)

        if channel:
            try:
                msg = await channel.fetch_message(message_id)
                if msg and msg.embeds:
                    old_embed = msg.embeds[0]
                    new_embed = discord.Embed.from_dict(old_embed.to_dict())
                    new_embed.title = "🎉 ¡SORTEO FINALIZADO! 🎉"
                    new_embed.color = discord.Color.gold()

                    if winners:
                        winners_mentions = ", ".join([f"<@{w}>" for w in winners])
                        new_embed.description = (
                            f"🎁 **Premio Sorteado:** **{prize}**\n\n"
                            f"🏆 **¡Ganadores Oficiales!**\n"
                            f"{winners_mentions}\n\n"
                            f"👥 **Total de participantes:** **{len(participants)}**\n"
                            f"✨ ¡Felicitaciones a los ganadores! Abran ticket en <#{self.ticket_channel_id}> para reclamar su key."
                        )
                    else:
                        new_embed.description = (
                            f"🎁 **Premio Sorteado:** **{prize}**\n\n"
                            f"⚠️ **Sorteo finalizado sin participantes.**\n"
                            f"No hubo miembros inscritos para este sorteo."
                        )

                    disabled_view = discord.ui.View()
                    disabled_view.add_item(
                        discord.ui.Button(
                            label=f"Sorteo Terminado ({len(participants)} Participantes)",
                            style=discord.ButtonStyle.secondary,
                            disabled=True
                        )
                    )
                    await msg.edit(embed=new_embed, view=disabled_view)
            except Exception as e:
                logger.warning(f"Aviso actualizando mensaje de sorteo: {e}")

            if winners:
                winners_pings = " ".join([f"<@{w}>" for w in winners])
                try:
                    announce_embed = discord.Embed(
                        title="🎊 ¡TENEMOS GANADORES DEL SORTEO! 🎊",
                        description=(
                            f"🎉 ¡Felicitaciones a los afortunados ganadores de **{prize}**!\n\n"
                            f"🏆 **Ganadores:**\n"
                            + "\n".join([f"• <@{w}>" for w in winners]) + "\n\n"
                            f"🎫 **¿Cómo reclamar tu key?**\n"
                            f"Por favor abre un ticket inmediatamente en <#{self.ticket_channel_id}> para entregarte tu key oficial."
                        ),
                        color=discord.Color.from_rgb(0, 255, 170),
                        timestamp=discord.utils.utcnow()
                    )
                    if os.path.exists(BANNER_IMAGE_PATH):
                        file = discord.File(BANNER_IMAGE_PATH, filename="denzel_banner.jpg")
                        announce_embed.set_image(url="attachment://denzel_banner.jpg")
                        await channel.send(content=f"🎉 {winners_pings}", file=file, embed=announce_embed)
                    else:
                        await channel.send(content=f"🎉 {winners_pings}", embed=announce_embed)
                except Exception as e:
                    logger.warning(f"Aviso enviando anuncio de ganadores: {e}")

        try:
            await self.log_security_event(
                guild=guild,
                title="🎉 Sorteo Finalizado & Ganadores Elegidos",
                description=(
                    f"🎁 **Premio:** `{prize}`\n"
                    f"🏆 **Ganadores ({len(winners)}):** " + (", ".join([f"<@{w}>" for w in winners]) if winners else "Ninguno") + "\n"
                    f"👥 **Participantes:** {len(participants)}"
                ),
                color=discord.Color.gold()
            )
        except Exception as e:
            logger.warning(f"Aviso registrando sorteo en logs: {e}")

    @voice_watchdog.before_loop
    @voice_keepalive.before_loop
    @audio_worker.before_loop
    @status_rotator.before_loop
    @giveaway_checker.before_loop
    async def before_tasks(self):
        await self.wait_until_ready()

def run_bot():
    ensure_single_local_instance()

    if not TOKEN:
        logger.error("❌ ERROR: DISCORD_TOKEN no configurado.")
        logger.error("👉 En Railway: Ve a la pestaña 'Variables' y agrega todas las variables de tu archivo .env.")
        time.sleep(15)
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
