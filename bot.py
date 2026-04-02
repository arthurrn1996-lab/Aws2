import pytchat
import requests
import re
import time
import threading
import sys
import logging
import json
from urllib.parse import unquote

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
# ESTADO GLOBAL
# =============================================================================

threads_ativas = {}
cooldown_lives = {}
cache_mensagens = {}

lock_threads = threading.Lock()
lock_cache = threading.Lock()

# =============================================================================
# UTIL
# =============================================================================

def eh_duplicado(chave, ttl=300):
    agora = time.time()
    with lock_cache:
        if chave in cache_mensagens and (agora - cache_mensagens[chave]) < ttl:
            return True

        cache_mensagens[chave] = agora

        if len(cache_mensagens) > 3000:
            cache_mensagens.clear()

        return False

def enviar_para_discord(msg):
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=5)
    except Exception as e:
        log.error(f"Erro Discord: {e}")

def limpar_url(url):
    return url.rstrip('.,!?;:…"\'()<>[]')

# =============================================================================
# YOUTUBE LIVE DETECTOR
# =============================================================================

def buscar_id_da_live(handle):
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
        log.error(f"Erro ao buscar live {handle}: {e}")

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
# BETBOOM
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
                        link = limpar_url(u[0])

                        if not eh_duplicado(link):
                            enviar_para_discord(f"💰 BETBOOM\n📺 {handle}\n👤 {autor}\n🔗 {link}")

                    for c in cupons:
                        c = c.upper()
                        if not eh_duplicado(c):
                            enviar_para_discord(f"🟡 CUPOM\n📺 {handle}\n👤 {autor}\n🎟 {c}")

                except Exception as e:
                    log.error(f"Erro msg BB: {e}")

    except Exception as e:
        log.error(f"Erro geral BB: {e}")

    finally:
        with lock_threads:
            threads_ativas.pop(f"BB_{handle}", None)
            cooldown_lives[f"BB_{handle}"] = time.time() + 10

        log.warning(f"⭕ BB CAIU: {handle}")

# =============================================================================
# LOTTU
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

                    if "http" in msg or vip:
                        if not eh_duplicado(msg_id):
                            enviar_para_discord(f"🚨 LOTTU\n📺 {handle}\n👤 {autor}\n💬 {msg}")

                except Exception as e:
                    log.error(f"Erro msg LOTTU: {e}")

    except Exception as e:
        log.error(f"Erro geral LOTTU: {e}")

    finally:
        with lock_threads:
            threads_ativas.pop(f"LOTTU_{handle}", None)
            cooldown_lives[f"LOTTU_{handle}"] = time.time() + 10

        log.warning(f"⭕ LOTTU CAIU: {handle}")

# =============================================================================
# ORQUESTRADOR
# =============================================================================

def monitor():
    while True:
        try:
            agora = time.time()

            for h in CANAIS_BETBOOM:
                chave = f"BB_{h}"

                with lock_threads:
                    if chave in threads_ativas or (chave in cooldown_lives and agora < cooldown_lives[chave]):
                        continue

                vid = buscar_id_da_live(h)

                if vid:
                    with lock_threads:
                        threads_ativas[chave] = True

                    threading.Thread(target=processar_betboom, args=(vid, h), daemon=True).start()

            for h in CANAIS_LOTTU:
                chave = f"LOTTU_{h}"

                with lock_threads:
                    if chave in threads_ativas or (chave in cooldown_lives and agora < cooldown_lives[chave]):
                        continue

                vid = buscar_id_da_live(h)

                if vid:
                    with lock_threads:
                        threads_ativas[chave] = True

                    threading.Thread(target=processar_lottu, args=(vid, h), daemon=True).start()

        except Exception as e:
            log.error(f"Erro monitor: {e}")

        time.sleep(5)

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    log.info("🚀 BOT INICIADO (VERSÃO ESTÁVEL)")
    monitor()
