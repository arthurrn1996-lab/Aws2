import pytchat
import requests
import httpx
import re
import time
import threading
import sys
import logging
import json
import random
from urllib.parse import unquote

# =============================================================================
# CAMUFLAGEM ROTATIVA (BYPASS DE BLOQUEIO DA AWS)
# =============================================================================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/123.0.0.0"
]

def obter_headers_falsos():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Cookie": "CONSENT=YES+cb.20210328-17-p0.en+FX+478; SOCS=CAI;",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"
    }

# Mantido o Monkey Patching para a Pytchat utilizar a camuflagem
if not hasattr(requests.Session, '_patch_aplicado'):
    original_session_request = requests.Session.request
    def patched_session_request(self, method, url, *args, **kwargs):
        if "youtube.com" in url or "ytimg.com" in url:
            headers = kwargs.get('headers', {})
            headers.update(obter_headers_falsos())
            kwargs['headers'] = headers
        return original_session_request(self, method, url, *args, **kwargs)
    requests.Session.request = patched_session_request
    requests.Session._patch_aplicado = True 

if not hasattr(httpx.Client, '_patch_aplicado'):
    original_httpx_send = httpx.Client.send
    def patched_httpx_send(self, request, *args, **kwargs):
        if "youtube.com" in str(request.url) or "ytimg.com" in str(request.url):
            falso = obter_headers_falsos()
            request.headers["User-Agent"] = falso["User-Agent"]
            request.headers["Cookie"] = falso["Cookie"]
        return original_httpx_send(self, request, *args, **kwargs)
    httpx.Client.send = patched_httpx_send
    httpx.Client._patch_aplicado = True

# =============================================================================
# CONFIGURAÇÕES GLOBAIS
# =============================================================================
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1484333785947439254/GttlWy82JWu6JbsHrE5fp9-h78FW_QDApeGcQYGchKSNwBjBqErDl2XlCjpHBSY0urkf"

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING) 

threads_ativas = {}
cooldown_lives = {}
lock_threads = threading.Lock()
cache_mensagens = {}
lock_cache = threading.Lock()

def eh_duplicado(chave, ttl_segundos=300):
    agora = time.time()
    with lock_cache:
        if chave in cache_mensagens and (agora - cache_mensagens[chave]) < ttl_segundos: return True
        cache_mensagens[chave] = agora
        if len(cache_mensagens) > 3000:
            remover = [k for k, v in list(cache_mensagens.items()) if (agora - v) >= ttl_segundos]
            for k in remover: del cache_mensagens[k]
        return False

class LeitorCodigoFonte:
    def process(self, chat_components): return chat_components
    def finalize(self): pass

def enviar_para_discord(texto: str) -> bool:
    payload = {"content": texto}
    for _ in range(3):
        try:
            requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
            return True
        except Exception as e: 
            log.warning(f"Erro ao enviar webhook: {e}")
            time.sleep(1)
    return False

def buscar_id_da_live(handle: str):
    url = f"https://www.youtube.com/{handle}/live"
    try:
        # Passando headers diretamente para garantir evasão na busca primária
        response = requests.get(url, headers=obter_headers_falsos(), timeout=10, allow_redirects=True)
        html = response.text
        if '"isLiveNow":true' in html or 'isLiveNow' in html:
            match_canonical = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})">', html)
            if match_canonical: return match_canonical.group(1)
            match_json = re.search(r'"videoId":"([^"]+)"', html)
            if match_json: return match_json.group(1)
        return None
    except Exception as e: 
        log.error(f"Falha ao buscar id da live para {handle}: {e}")
        return None

def extrair_dados_visuais(raw_item):
    autor, msg, msg_id, is_vip = "Desconhecido", "", "", False
    try:
        renderer = raw_item.get('addChatItemAction', {}).get('item', {}).get('liveChatTextMessageRenderer', {})
        if not renderer: renderer = raw_item.get('addChatItemAction', {}).get('item', {}).get('liveChatPaidMessageRenderer', {})
        if renderer:
            msg_id = renderer.get('id', "")
            autor = renderer.get('authorName', {}).get('simpleText', "Desconhecido")
            for badge in renderer.get('authorBadges', []):
                icon_type = badge.get('liveChatAuthorBadgeRenderer', {}).get('icon', {}).get('iconType', '')
                if icon_type in ['MODERATOR', 'OWNER']: is_vip = True
            msg = "".join([r.get('text', '') for r in renderer.get('message', {}).get('runs', [])])
    except Exception as e:
        pass
    return msg_id, autor, msg, is_vip

def limpar_url(url: str) -> str: return url.rstrip('.,!?;:…"\'()<>[]')

# =============================================================================
# MOTORES
# =============================================================================
def enviar_discord_betboom(dado, canal, tipo="link", desc=""):
    desc_segura = desc.replace('<', '').replace('>', '')
    txt_desc = f"\n💬 **Contexto:** {desc_segura}\n" if desc_segura else ""
    if tipo == "cupom": msg = f"🟡 **BETBOOM - NOVO CUPOM!**\n📍 **Origem:** `{canal}`{txt_desc}\n✂️ **Clique para copiar:**\n```\n{dado}\n```"
    else: msg = f"💰 **BETBOOM / MONEYBOOM DETECTADO!**\n📍 **Origem:** `{canal}`{txt_desc}\n🔗 **Link:**\n{dado}"
    enviar_para_discord(msg)

def processar_chat_betboom(video_id: str, handle: str):
    log.info(f"🟡 BB CONECTADO: {handle}")
    try:
        chat = pytchat.create(video_id=video_id, processor=LeitorCodigoFonte(), interruptable=False)
        while chat.is_alive():
            dados = chat.get()
            if not dados: continue
            for raw_item in dados:
                msg_id, autor, msg_visual, is_vip = extrair_dados_visuais(raw_item)
                texto_puro = unquote(json.dumps(raw_item, ensure_ascii=False)).replace('\\/', '/').replace('\\n', ' ')
                
                urls = set(re.findall(r'(https?://[^\s\"\'<>]*(?:betboom|moneyboom)[^\s\"\'<>]*)', texto_puro + " " + msg_visual, re.IGNORECASE))
                cupons = re.findall(r'(?i)cupom\s*:?\s*([a-zA-Z0-9]{5,15})', texto_puro + " " + msg_visual)
                
                for link in urls:
                    lk = link.lower().replace("http://", "https://")
                    if 'youtube.com/redirect' in lk:
                        m = re.search(r'q=(https?://[^&]+)', unquote(lk))
                        if m: lk = m.group(1)
                    lk = limpar_url(lk)
                    if not eh_duplicado(f"yt_bb_link_{lk}_{handle}"): enviar_discord_betboom(lk, handle, "link", f"De: {autor}")
                
                for cp in cupons:
                    cp = cp.upper()
                    if not eh_duplicado(f"yt_bb_cupom_{cp}_{handle}"): enviar_discord_betboom(cp, handle, "cupom", f"De: {autor}")
    except Exception as e:
        log.warning(f"Erro no chat BB de {handle}: {e}")
    finally:
        with lock_threads:
            threads_ativas.pop(f"BB_{handle}", None)
            cooldown_lives[f"BB_{handle}"] = time.time() + 30
        log.warning(f"⭕ BB CAIU (Reconectando em 30s): {handle}")

def processar_chat_lottu(video_id: str, handle: str):
    log.info(f"🟢 LOTTU CONECTADO: {handle}")
    try:
        chat = pytchat.create(video_id=video_id, processor=LeitorCodigoFonte(), interruptable=False)
        LINK_REG = re.compile(r"(https?://[^\s\"<>]*(?:lottu|lotuu|lotu|gorjeta\.net|gorjeta\.com)[^\s\"<>]*)", re.IGNORECASE)
        PUBLICO_REG = re.compile(r"(https?://[^\s\"<>]+/publico[^\s\"<>]*)", re.IGNORECASE)
        CHAVES_REG = re.compile(r"(palavra:|palavra chave:|frase:|chave:)\s*([a-zA-Z0-9_]+)", re.IGNORECASE)
        
        while chat.is_alive():
            dados = chat.get()
            if not dados: continue
            for raw_item in dados:
                msg_id, autor, msg_visual, is_vip = extrair_dados_visuais(raw_item)
                texto_puro = unquote(json.dumps(raw_item, ensure_ascii=False)).replace('\\/', '/').replace('\\n', ' ')
                
                links = set(LINK_REG.findall(msg_visual) + PUBLICO_REG.findall(msg_visual) + LINK_REG.findall(texto_puro) + PUBLICO_REG.findall(texto_puro))
                tem_chave = CHAVES_REG.search(msg_visual) or CHAVES_REG.search(texto_puro)
                
                if links or (tem_chave and is_vip):
                    id_unico = msg_id or f"{video_id}:{autor}:{time.time()}"
                    if not eh_duplicado(f"lottu_{id_unico}", ttl_segundos=60):
                        cargo = "👑 [VIP/MOD]" if is_vip else "👤"
                        links_limpos = [limpar_url(re.search(r'q=(https?://[^&]+)', unquote(lk)).group(1) if 'redirect' in lk else lk) for lk in links]
                        sl = "\n".join(f"🔗 {lk}" for lk in set(links_limpos))
                        txt_links = f"\n\n🌐 **Link:**\n{sl}" if sl else ""
                        txt_senha = f"\n\n🔑 **Palavra:**\n```\n{tem_chave.group(2)}\n```" if tem_chave else ""
                        
                        alerta = f"🚨 **GORJETA DETECTADA** 🚨\n📺 **Canal:** `{handle}`\n👤 **Autor:** {autor} {cargo}{txt_links}{txt_senha}"
                        enviar_para_discord(alerta)
    except Exception as e: 
        log.warning(f"Erro no chat LOTTU de {handle}: {e}")
    finally:
        with lock_threads:
            threads_ativas.pop(f"LOTTU_{handle}", None)
            cooldown_lives[f"LOTTU_{handle}"] = time.time() + 30 
        log.warning(f"⭕ LOTTU CAIU (Reconectando em 30s): {handle}")

# =============================================================================
# ORQUESTRADOR BLINDADO
# =============================================================================
def checar_novas_lives():
    while True:
        try:
            agora = time.time()
            
            # Loop BETBOOM com atraso de segurança
            for handle in CANAIS_BETBOOM:
                chave = f"BB_{handle}"
                with lock_threads:
                    if chave in threads_ativas or (chave in cooldown_lives and agora < cooldown_lives[chave]): 
                        continue
                v_id = buscar_id_da_live(handle)
                if v_id:
                    with lock_threads: threads_ativas[chave] = v_id
                    threading.Thread(target=processar_chat_betboom, args=(v_id, handle), daemon=True).start()
                time.sleep(2) # Evita rajada de requisições que geram bloqueio na AWS

            # Loop LOTTU com atraso de segurança
            for handle in CANAIS_LOTTU:
                chave = f"LOTTU_{handle}"
                with lock_threads:
                    if chave in threads_ativas or (chave in cooldown_lives and agora < cooldown_lives[chave]): 
                        continue
                v_id = buscar_id_da_live(handle)
                if v_id:
                    with lock_threads: threads_ativas[chave] = v_id
                    threading.Thread(target=processar_chat_lottu, args=(v_id, handle), daemon=True).start()
                time.sleep(2) # Evita rajada de requisições

        except Exception as e: 
            log.error(f"Erro na varredura principal: {e}")
        
        # Dorme por 60 segundos antes de recomeçar a varrer tudo. 
        # Isso salva o seu IP de ser banido pela proteção de DDoS do YouTube.
        time.sleep(60)

if __name__ == "__main__":
    enviar_para_discord("🚀 **BOT CAMUFLADO ONLINE!**\n🎭 Sistema de Rotação de Identidade e Prevenção de Rate Limit Ativo")
    try: 
        checar_novas_lives()
    except KeyboardInterrupt: 
        sys.exit(0)
