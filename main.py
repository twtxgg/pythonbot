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

# Configurações do bot (pode ser movido para config.py)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH")
DONO_ID = int(os.environ.get("DONO_ID", 0))

# Configurações de diretórios
PASTA_DOWNLOAD = "/tmp/downloads"
PASTA_THUMB = "/tmp/thumb_cache"
TAMANHO_MAXIMO = 2000 * 1024 * 1024  # 2GB
INTERVALO_ATUALIZACAO = 5  # Segundos

app = Client(
    "bot_upload_video",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ... (mantenha todas as outras funções como no código anterior) ...

def verificar_ambiente():
    """Verifica e cria os diretórios necessários"""
    os.makedirs(PASTA_DOWNLOAD, exist_ok=True)
    os.makedirs(PASTA_THUMB, exist_ok=True)
    
    # Verifica dependências do sistema
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["ffprobe", "-version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        logger.error("Dependências não encontradas: ffmpeg e ffprobe")
        raise

if __name__ == "__main__":
    try:
        verificar_ambiente()
        logger.info("----- Iniciando Bot na AWS -----")
        logger.info(f"Diretório de downloads: {PASTA_DOWNLOAD}")
        logger.info(f"Diretório de thumbnails: {PASTA_THUMB}")
        
        app.run()
    except Exception as e:
        logger.error(f"Falha ao iniciar bot: {str(e)}")
        raise
