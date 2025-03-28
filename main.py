import os
import asyncio
import yt_dlp
import aiohttp
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from pyrogram.errors import MessageNotModified, FloodWait
import logging
import time
from functools import wraps
import subprocess
import hashlib
import re

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configurações do bot
class Config:
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    API_ID = int(os.environ.get("API_ID", 0))
    API_HASH = os.environ.get("API_HASH", "")
    DONO_ID = 940793418
    PASTA_DOWNLOAD = "./downloads"
    PASTA_THUMB = "./thumb_cache"
    TAMANHO_MAXIMO = 2000 * 1024 * 1024  # 2GB
    INTERVALO_ATUALIZACAO = 5  # Segundos entre atualizações de progresso

app = Client(
    "bot_upload_video",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN
)

# Variáveis globais
ULTIMO_TEMPO_ATUALIZACAO = 0
TEMPO_INICIO = 0

def eh_comentario_canal(mensagem: Message) -> bool:
    """Verifica se a mensagem é um comentário em um canal"""
    return (mensagem.chat.type == enums.ChatType.CHANNEL and 
            mensagem.reply_to_message is not None)

async def apagar_url_se_permitido(client: Client, mensagem: Message, eh_resposta: bool):
    """
    Tenta apagar a URL conforme as permissões
    - Funciona em grupos, canais e comentários de canais
    - Não apaga em chats privados
    """
    try:
        # Verifica se é um local onde podemos apagar (grupos/canais/comentários)
        if eh_resposta or mensagem.chat.type in [enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL, enums.ChatType.GROUP]:
            await asyncio.sleep(2)  # Espera para garantir que o upload foi finalizado
            await mensagem.delete()
            logger.info(f"URL removida com sucesso (ID: {mensagem.id})")
    except Exception as e:
        logger.error(f"Falha ao remover URL: {str(e)}")

def converter_bytes(tamanho):
    """Converte bytes para formato legível (KB, MB, GB)"""
    unidades = ["B", "KB", "MB", "GB", "TB"]
    tamanho = float(tamanho)
    i = 0
    while tamanho >= 1024 and i < len(unidades)-1:
        tamanho /= 1024
        i += 1
    return f"{tamanho:.2f} {unidades[i]}"

def criar_barra_progresso(percentual):
    """Gera barra de progresso visual"""
    preenchido = int(percentual/10)
    return f"[{'■' * preenchido}{'□' * (10 - preenchido)}]"

def extrair_metadados_video(caminho_arquivo):
    """Extrai metadados do vídeo (duração, dimensões, thumbnail)"""
    try:
        if not os.path.exists(caminho_arquivo) or os.path.getsize(caminho_arquivo) == 0:
            raise Exception("Arquivo inválido ou vazio")

        # Comandos para extrair duração e dimensões
        comando_duracao = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            caminho_arquivo
        ]
        comando_dimensoes = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=p=0',
            caminho_arquivo
        ]

        duracao = float(subprocess.check_output(comando_duracao).decode('utf-8').strip())
        dimensoes = subprocess.check_output(comando_dimensoes).decode('utf-8').strip().split(',')

        # Gerar thumbnail em 30 segundos (ou último frame para vídeos curtos)
        caminho_thumbnail = f"{caminho_arquivo}_thumb.jpg"
        if os.path.exists(caminho_thumbnail):
            os.remove(caminho_thumbnail)

        tempo_busca = '30' if float(duracao) >= 30 else str(float(duracao)-1)

        subprocess.run([
            'ffmpeg', '-y', '-ss', tempo_busca, '-i', caminho_arquivo,
            '-vframes', '1', '-q:v', '2', caminho_thumbnail
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        return {
            'duracao': int(duracao),
            'largura': int(dimensoes[0]),
            'altura': int(dimensoes[1]),
            'caminho_thumbnail': caminho_thumbnail if os.path.exists(caminho_thumbnail) else None
        }

    except Exception as e:
        logger.error(f"Erro ao extrair metadados: {str(e)}")
        return None

def tratar_flood_wait(func):
    """Decorator para tratamento de FloodWait"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except FloodWait as e:
            logger.warning(f"FloodWait: Esperando {e.x} segundos")
            await asyncio.sleep(e.x)
            return await func(*args, **kwargs)
    return wrapper

async def baixar_com_ytdlp(url, caminho_arquivo):
    """Download usando yt-dlp com fallback para diferentes formatos"""
    opcoes_ydl = {
        'outtmpl': caminho_arquivo,
        'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
        'quiet': True,
        'geo_bypass': True,
        'noplaylist': True,
        'extractor_args': {
            'youtube': {'skip': ['dash', 'hls']},
            'generic': {'skip': ['dash', 'hls']}
        },
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4'
        }]
    }

    try:
        with yt_dlp.YoutubeDL(opcoes_ydl) as ydl:
            await asyncio.to_thread(ydl.download, [url])
        return True
    except yt_dlp.utils.DownloadError as e:
        logger.warning(f"Tentando fallback: {e}")
        opcoes_ydl['format'] = 'best'
        try:
            with yt_dlp.YoutubeDL(opcoes_ydl) as ydl:
                await asyncio.to_thread(ydl.download, [url])
            return True
        except Exception as e:
            logger.error(f"Fallback falhou: {e}")
            return False

async def download_arquivo_generico(url, caminho_arquivo):
    """Download de qualquer tipo de arquivo genérico"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    with open(caminho_arquivo, 'wb') as f:
                        async for chunk in response.content.iter_chunked(1024):
                            f.write(chunk)
                    return True
    except Exception as e:
        logger.error(f"Erro ao baixar arquivo: {e}")
        return False

@tratar_flood_wait
async def callback_progresso(atual, total, mensagem):
    """Callback de progresso com controle de flood"""
    global ULTIMO_TEMPO_ATUALIZACAO

    agora = time.time()
    if agora - ULTIMO_TEMPO_ATUALIZACAO < Config.INTERVALO_ATUALIZACAO:
        return

    ULTIMO_TEMPO_ATUALIZACAO = agora
    percentual = (atual / total) * 100
    tempo_decorrido = agora - TEMPO_INICIO
    velocidade = atual / tempo_decorrido if tempo_decorrido > 0 else 0
    tempo_restante = (total - atual) / velocidade if velocidade > 0 else 0

    try:
        texto = (
            f"📤 **Progresso do Upload**\n"
            f"{criar_barra_progresso(percentual)} {percentual:.1f}%\n"
            f"⚡ {converter_bytes(velocidade)}/s\n"
            f"⏱️ {tempo_restante:.0f}s restantes"
        )
        await mensagem.edit(texto)
    except MessageNotModified:
        pass
    except Exception as e:
        logger.warning(f"Falha ao atualizar progresso: {e}")

@app.on_message(filters.command(["start", "help"]))
@tratar_flood_wait
async def comando_start(client, mensagem: Message):
    """Handler do comando /start e /help"""
    await mensagem.reply(
        "✅ **Bot de Upload de Arquivos Ativo!**\n\n"
        "📌 **Como usar:**\n"
        "• Envie uma URL de vídeo/imagem\n"
        "• Ou use /up <URL>\n"
        "• Para legenda direta: /leg <texto> <URL>\n"
        "• Para adicionar legenda depois: responda com /leg <texto>\n\n"
        "💡 **Em canais:** Responda a postagens com os comandos para enviar como comentário"
    )

@app.on_message(filters.command(["up", "leg"]))
@tratar_flood_wait
async def comando_upload(client, mensagem: Message):
    """Manipula os comandos /up e /leg"""
    global TEMPO_INICIO
    TEMPO_INICIO = time.time()

    # Verificar se é uma resposta (comentário em canal)
    eh_resposta = mensagem.reply_to_message is not None
    mensagem_original = mensagem.reply_to_message if eh_resposta else None

    if mensagem.command[0] == "leg" and len(mensagem.command) > 1:
        padrao_url = re.compile(r'(https?://\S+)$')
        match = padrao_url.search(mensagem.text)

        if match:
            url = match.group(1)
            legenda = mensagem.text.split(maxsplit=1)[1][:-len(url)].strip()
        elif eh_resposta:
            if len(mensagem.command) < 2:
                await mensagem.reply("❌ Use /leg <texto> respondendo a uma mídia")
                return

            legenda = mensagem.text.split(maxsplit=1)[1]

            try:
                if mensagem_original.caption is not None:
                    await mensagem_original.edit_caption(legenda)
                else:
                    await mensagem_original.edit_caption(caption=legenda)
                await mensagem.delete()
                return
            except Exception as e:
                logger.error(f"Erro ao adicionar legenda: {str(e)}")
                await mensagem.reply(f"⚠️ Erro ao adicionar legenda: {str(e)}")
                return
        else:
            await mensagem.reply("❌ Formato incorreto. Use: /leg sua legenda aqui https://exemplo.com/video.mp4")
            return
    elif mensagem.command[0] == "up" and len(mensagem.command) > 1:
        url = mensagem.text.split(maxsplit=1)[1]
        legenda = None
    else:
        await mensagem.reply("❌ Use /up <URL> ou /leg <texto> <URL>")
        return

    msg_status = await mensagem.reply("🔍 Iniciando processamento...")

    extensao = os.path.splitext(url.split('?')[0])[1].lower() if '.' in url.split('?')[0] else '.mp4'
    caminho_arquivo = os.path.join(Config.PASTA_DOWNLOAD, f"dl_{mensagem.id}{extensao}")

    try:
        await msg_status.edit("⬇️ Baixando arquivo...")

        if extensao in ['.mp4', '.mkv', '.avi', '.mov', '.webm']:
            sucesso = await baixar_com_ytdlp(url, caminho_arquivo)
        else:
            sucesso = await download_arquivo_generico(url, caminho_arquivo)

        if not sucesso:
            await msg_status.edit("❌ Falha no download do arquivo")
            return

        tamanho_arquivo = os.path.getsize(caminho_arquivo)
        if tamanho_arquivo > Config.TAMANHO_MAXIMO:
            os.remove(caminho_arquivo)
            await msg_status.edit(f"❌ Arquivo muito grande ({converter_bytes(tamanho_arquivo)})")
            return

        # Preparar parâmetros de envio
        params = {
            'caption': legenda,
            'progress': callback_progresso,
            'progress_args': (msg_status,)
        }

        if eh_resposta:
            params['reply_to_message_id'] = mensagem_original.id

        await msg_status.edit("⬆️ Enviando arquivo...")

        if extensao in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
            await client.send_photo(
                chat_id=mensagem.chat.id,
                photo=caminho_arquivo,
                **params
            )
        elif extensao in ['.mp4', '.mkv', '.avi', '.mov', '.webm']:
            metadados = extrair_metadados_video(caminho_arquivo)
            if metadados:
                await client.send_video(
                    chat_id=mensagem.chat.id,
                    video=caminho_arquivo,
                    duration=metadados['duracao'],
                    width=metadados['largura'],
                    height=metadados['altura'],
                    thumb=metadados['caminho_thumbnail'],
                    supports_streaming=True,
                    **params
                )
            else:
                await client.send_document(
                    chat_id=mensagem.chat.id,
                    document=caminho_arquivo,
                    **params
                )
        else:
            await client.send_document(
                chat_id=mensagem.chat.id,
                document=caminho_arquivo,
                **params
            )

        await msg_status.delete()

        # Tenta apagar a URL (funciona em grupos e comentários de canal)
        await apagar_url_se_permitido(client, mensagem, eh_resposta)

    except Exception as e:
        logger.error(f"Erro no processamento: {str(e)}")
        await msg_status.edit(f"⚠️ Erro: {str(e)[:200]}")
    finally:
        if os.path.exists(caminho_arquivo):
            os.remove(caminho_arquivo)
        if os.path.exists(f"{caminho_arquivo}_thumb.jpg"):
            os.remove(f"{caminho_arquivo}_thumb.jpg")

@app.on_message(filters.text & ~filters.command(["start", "help", "up", "leg"]))
@tratar_flood_wait
async def lidar_com_links_automaticos(client, mensagem: Message):
    """Handler para links automáticos (sem comando)"""
    global TEMPO_INICIO
    TEMPO_INICIO = time.time()

    # Verificar se é uma resposta (comentário em canal)
    eh_resposta = mensagem.reply_to_message is not None
    mensagem_original = mensagem.reply_to_message if eh_resposta else None

    url = mensagem.text.strip()
    if not url.startswith(('http://', 'https://')):
        return

    msg_status = await mensagem.reply("🔍 Processando link automaticamente...")
    caminho_arquivo = os.path.join(Config.PASTA_DOWNLOAD, f"dl_{mensagem.id}.mp4")

    try:
        await msg_status.edit("⬇️ Baixando vídeo...")
        if not await baixar_com_ytdlp(url, caminho_arquivo):
            await msg_status.edit("❌ Formato de vídeo não suportado")
            return

        if not os.path.exists(caminho_arquivo) or os.path.getsize(caminho_arquivo) == 0:
            await msg_status.edit("❌ Problema com o arquivo baixado")
            return

        tamanho_arquivo = os.path.getsize(caminho_arquivo)
        if tamanho_arquivo > Config.TAMANHO_MAXIMO:
            os.remove(caminho_arquivo)
            await msg_status.edit(f"❌ Arquivo muito grande ({converter_bytes(tamanho_arquivo)})")
            return

        metadados = extrair_metadados_video(caminho_arquivo)
        if not metadados:
            await msg_status.edit("❌ Falha ao extrair metadados do vídeo")
            os.remove(caminho_arquivo)
            return

        await msg_status.edit("⬆️ Enviando vídeo...")

        params = {
            'chat_id': mensagem.chat.id,
            'video': caminho_arquivo,
            'duration': metadados['duracao'],
            'width': metadados['largura'],
            'height': metadados['altura'],
            'thumb': metadados['caminho_thumbnail'],
            'supports_streaming': True,
            'progress': callback_progresso,
            'progress_args': (msg_status,)
        }

        if eh_resposta:
            params['reply_to_message_id'] = mensagem_original.id

        await client.send_video(**params)

        await msg_status.delete()

        # Tenta apagar a URL (funciona em grupos e comentários de canal)
        await apagar_url_se_permitido(client, mensagem, eh_resposta)

    except Exception as e:
        logger.error(f"Erro no processamento automático: {str(e)}")
        await msg_status.edit(f"⚠️ Erro: {str(e)[:200]}")
    finally:
        if os.path.exists(caminho_arquivo):
            os.remove(caminho_arquivo)
        if os.path.exists(f"{caminho_arquivo}_thumb.jpg"):
            os.remove(f"{caminho_arquivo}_thumb.jpg")
        try:
            await msg_status.delete()
        except:
            pass

if __name__ == "__main__":
    # Garante que as pastas existam
    os.makedirs(Config.PASTA_DOWNLOAD, exist_ok=True)
    os.makedirs(Config.PASTA_THUMB, exist_ok=True)

    logger.info("----- Bot Iniciado -----")
    app.run()
