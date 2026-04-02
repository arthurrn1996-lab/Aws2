import pytchat
import requests
import re
import time
import sys
import logging
import json
from urllib.parse import unquote
from multiprocessing import Process

# =============================================================================
# CONFIG
# =============================================================================

DISCORD_WEBHOOK_URL = "COLE_SEU_WEBHOOK_AQUI"

CANAIS_BETBOOM = [
    "@1markola", "@TheNoite", "@danilogentili", "@BetBoom_Global",
    "@fallenINSIDER", "@camyy182", "@ale_apoka", "@jonvlogs",
    "@Jogakaiquejoga", "@danielfortuneoficial", "@CasalSuperBR", "@psouza7"
]

CANAIS_LOTTU = [
    "@RodrigoF", "@JackPotsClips", "@LeonardoSteluto", "@BuxexaOficial",
    "@BIASLOTSOFICIAL", "@gabzbet", "@LuquEt4", "@OZezii", "@WEEDZERATV",
    "@cerol", "@SORTENOSLOT-PriSimões", "@tonhmiller", "@Bluyd777",
    "@felipekersch", "@oEduhzao", "@NobruTV", "@caiopericinoto",
    "@nervosawin", "@TocadasOficiall", "@LanaGamerlive", "@SequelaxXx",
    "@Rachaxp"
]

# =============================================================================
# LOG
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)

log = logging.getLogger(__name__)

# =============================================================================
# CACHE (ANTI DUPLICAÇÃO)
# =============================================================================

cache = {}

def eh_duplicado(chave, ttl=300):
    agora = time.time()
    if chave in cache and (agora - cache[chave]) < ttl:
        return True
    cache[chave] = agora

    if len(cache) > 5000:
        cache.clear()

    return False

# =============================================================================
# DISCORD
# =============================================================================

def enviar_discord(msg):
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=5)
    except Exception as e:
        log.error(f"Erro Discord: {e}")

# =============================================================================
# YOUTUBE
# =============================================================================

def buscar_live(handle):
    try:
        url = f"https://www.youtube.com/{handle}/live"
        r = requests.get(url, timeout=10)
        html = r.text

        if "isLiveNow" not in html:
            return None

        m = re.search(r'"videoId":"([^"]+)"', html)
        if m:
            return m.group(1)

    except Exception as e:
        log.error(f"Erro buscar live {handle}: {e}")

    return None

# =============================================================================
# EXTRAÇÃO
# =============================================================================

def extrair(raw):
    try:
        renderer = raw.get('addChatItemAction', {}).get('item', {}).get('liveChatTextMessageRenderer', {})
        if not renderer:
            renderer = raw.get('addChatItemAction', {}).get('item', {}).get('liveChatPaidMessageRenderer', {})

        autor = renderer.get('authorName', {}).get('simpleText', "")
        msg = "".join([r.get('text', '') for r in renderer.get('message', {}).get('runs', [])])
        msg_id = renderer.get('id', "")

        vip = False
        for badge in renderer.get('authorBadges', []):
            if badge.get('liveChatAuthorBadgeRenderer', {}).get('icon', {}).get('iconType') in ['MODERATOR', 'OWNER']:
                vip = True

        return msg_id, autor, msg, vip

    except Exception as e:
        log.error(f"Erro extrair: {e}")
        return "", "", "", False

# =============================================================================
# BETBOOM PROCESS
# =============================================================================

def processar_betboom(video_id, handle):
    log.info(f"🟡 BB CONECTADO: {handle}")

    try:
        chat = pytchat.create(video_id=video_id)

        while True:
            if not chat.is_alive():
                break

            try:
                dados = chat.get()
            except Exception as e:
                log.error(f"Erro chat BB: {e}")
                break

            for raw in dados:
                try:
                    msg_id, autor, msg, _ = extrair(raw)

                    texto = json.dumps(raw)

                    urls = re.findall(r'(https?://[^\s]*(betboom|moneyboom)[^\s]*)', texto + msg, re.IGNORECASE)
                    cupons = re.findall(r'cupom[: ]*([a-zA-Z0-9]{5,15})', texto, re.IGNORECASE)

                    for u in urls:
                        link = u[0]
                        if not eh_duplicado(link):
                            enviar_discord(f"💰 BETBOOM\n📺 {handle}\n👤 {autor}\n🔗 {link}")

                    for c in cupons:
                        c = c.upper()
                        if not eh_duplicado(c):
                            enviar_discord(f"🟡 CUPOM\n📺 {handle}\n👤 {autor}\n🎟 {c}")

                except Exception as e:
                    log.error(f"Erro msg BB: {e}")

    except Exception as e:
        log.error(f"Erro geral BB: {e}")

    log.warning(f"⭕ BB FINALIZADO: {handle}")

# =============================================================================
# LOTTU PROCESS
# =============================================================================

def processar_lottu(video_id, handle):
    log.info(f"🟢 LOTTU CONECTADO: {handle}")

    try:
        chat = pytchat.create(video_id=video_id)

        while True:
            if not chat.is_alive():
                break

            try:
                dados = chat.get()
            except Exception as e:
                log.error(f"Erro chat LOTTU: {e}")
                break

            for raw in dados:
                try:
                    msg_id, autor, msg, vip = extrair(raw)

                    if ("http" in msg or vip) and not eh_duplicado(msg_id):
                        enviar_discord(f"🚨 LOTTU\n📺 {handle}\n👤 {autor}\n💬 {msg}")

                except Exception as e:
                    log.error(f"Erro msg LOTTU: {e}")

    except Exception as e:
        log.error(f"Erro geral LOTTU: {e}")

    log.warning(f"⭕ LOTTU FINALIZADO: {handle}")

# =============================================================================
# ORQUESTRADOR (PROCESSOS)
# =============================================================================

processos = {}

def monitor():
    while True:
        try:
            for h in CANAIS_BETBOOM:
                if h not in processos or not processos[h].is_alive():
                    vid = buscar_live(h)
                    if vid:
                        p = Process(target=processar_betboom, args=(vid, h))
                        p.start()
                        processos[h] = p

            for h in CANAIS_LOTTU:
                if h not in processos or not processos[h].is_alive():
                    vid = buscar_live(h)
                    if vid:
                        p = Process(target=processar_lottu, args=(vid, h))
                        p.start()
                        processos[h] = p

        except Exception as e:
            log.error(f"Erro monitor: {e}")

        time.sleep(5)

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    log.info("🚀 BOT INICIADO (VERSÃO FINAL ESTÁVEL)")
    monitor()
