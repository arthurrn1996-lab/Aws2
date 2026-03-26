import pytchat
import requests
import re
import time
import threading
import sys
import logging
import json
import os
from collections import deque
from urllib.parse import unquote
from http.server import BaseHTTPRequestHandler, HTTPServer

# =============================================================================
# PATCH GLOBAL PARA O PYTCHAT (ANTI-QUEDA YOUTUBE)
# =============================================================================
if not hasattr(requests.Session, '_patch_aplicado'):
    original_session_request = requests.Session.request

    def patched_session_request(self, method, url, *args, **kwargs):
        if "youtube.com" in url or "ytimg.com" in url:
            headers = kwargs.get('headers', {})
            headers = dict(headers)
            cookie_str = headers.get("Cookie", "")
            bypass_cookies = "CONSENT=YES+cb.20210328-17-p0.en+FX+478; SOCS=CAI;"
            headers["Cookie"] = f"{bypass_cookies} {cookie_str}".strip()
            headers["Accept-Language"] = "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"
            kwargs['headers'] = headers
        return original_session_request(self, method, url, *args, **kwargs)

    requests.Session.request = patched_session_request
    requests.Session._patch_aplicado = True 

# =============================================================================
# CONFIGURAÇÕES GLOBAIS
# =============================================================================
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1484333785947439254/GttlWy82JWu6JbsHrE5fp9-h78FW_QDApeGcQYGchKSNwBjBqErDl2XlCjpHBSY0urkf"

# ALVOS DO MOTOR 1 (BETBOOM)
CANAIS_BETBOOM = [
    "@1markola", "@TheNoite", "@danilogentili", "@BetBoom_Global",
    "@fallenINSIDER", "@camyy182", "@ale_apoka", "@jonvlogs",
    "@Jogakaiquejoga", "@danielfortuneoficial", "@CasalSuperBR", "@psouza7"
]

# ALVOS DO MOTOR 2 (LOTTU / GORJETA)
CANAIS_LOTTU = [
    "@RodrigoF", "@JackPotsClips", "@LeonardoSteluto", "@BuxexaOficial", 
    "@BIASLOTSOFICIAL", "@gabzbet", "@LuquEt4", "@OZezii", "@WEEDZERATV", 
    "@cerol", "@SORTENOSLOT-PriSimões", "@tonhmiller", "@Bluyd777",
    "@felipekersch", "@oEduhzao", "@NobruTV", "@caiopericinoto",
    "@nervosawin", "@TocadasOficiall", "@LanaGamerlive", "@SequelaxXx"
]

# =============================================================================
# CONTROLES GLOBAIS E BANCO DE DADOS EM MEMÓRIA
# =============================================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

# Memória BetBoom
sorteios_ja_pegos_betboom = set()
threads_bb = {}
cooldown_bb = {}
lock_bb = threading.Lock()

# Memória Lottu
mensagens_lottu_enviadas = deque(maxlen=5000)
set_lottu_enviadas = set()
threads_lottu = {}
cooldown_lottu = {}
lock_lottu = threading.Lock()

# =============================================================================
# FUNÇÕES COMPARTILHADAS (ÚTEIS PARA OS DOIS MOTORES)
# =============================================================================
class LeitorCodigoFonte:
    def process(self, chat_components):
        return chat_components

def enviar_para_discord(texto: str) -> bool:
    payload = {"content": texto}
    for tentativa in range(1, 4):
        try:
            requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            return True
        except Exception:
            time.sleep(1)
    return False

def buscar_id_da_live(handle: str):
    url = f"https://www.youtube.com/{handle}/live"
    headers = {"User-Agent": "Mozilla/5.0", "Cookie": "CONSENT=YES+cb.20210328-17-p0.en+FX+478"}
    try:
        response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        html = response.text
        if '"isLiveNow":true' in html or 'isLiveNow' in html:
            match_canonical = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})">', html)
            if match_canonical: return match_canonical.group(1)
            if "watch?v=" in response.url: return response.url.split("watch?v=")[1].split("&")[0]
            match_json = re.search(r'"videoId":"([^"]+)"', html)
            if match_json: return match_json.group(1)
        return None
    except:
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
                if badge.get('liveChatAuthorBadgeRenderer', {}).get('icon', {}).get('iconType', '') in ['MODERATOR', 'OWNER']:
                    is_vip = True
            msg = "".join([r.get('text', '') for r in renderer.get('message', {}).get('runs', [])])
    except: pass
    return msg_id, autor, msg, is_vip

# =============================================================================
# 🟡 MOTOR 1: SISTEMA BETBOOM (TELEGRAM + YOUTUBE)
# =============================================================================
def enviar_discord_betboom(dado, canal, tipo="link", desc=""):
    desc_segura = desc.replace('<', '').replace('>', '')
    txt_desc = f"\n💬 **Sobre:** *{desc_segura}*\n" if desc_segura else ""
    if tipo == "cupom":
        msg = f"🟡 **BETBOOM - NOVO CUPOM!**\n📍 Origem: {canal}{txt_desc}\n✂️ Copie o código:\n`{dado}`"
    else:
        msg = f"💰 **BETBOOM - NOVO DROP!**\n📍 Origem: {canal}{txt_desc}\n🔗 Clique rápido:\n{dado}"
    enviar_para_discord(msg)

def loop_telegram_betboom():
    log.info("📡 Radar do Telegram BetBoom iniciado!")
    while True:
        try:
            url = "https://t.me/s/betboombra"
            html = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10).text
            mensagens = html.split('tgme_widget_message ')[1:]
            
            for msg_html in mensagens:
                match_texto = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', msg_html, re.DOTALL)
                texto_limpo, resumo = "", ""
                if match_texto:
                    texto_limpo = re.sub(r'<[^>]+>', '', re.sub(r'<br\s*/?>', '\n', match_texto.group(1))).strip()
                    resumo = texto_limpo[:150] + "..." if len(texto_limpo) > 150 else texto_limpo
                
                urls = re.findall(r'(https?://(?:l\.)?betboom\.bet(?:\.br)?/[a-zA-Z0-9_/?=-]+)', msg_html, re.IGNORECASE)
                cupons = re.findall(r'(?i)cupom\s*:?\s*([a-zA-Z0-9]{5,15})', texto_limpo) if texto_limpo else []
                
                for link in urls:
                    lk = link.lower().replace("http://", "https://")
                    if lk not in sorteios_ja_pegos_betboom:
                        sorteios_ja_pegos_betboom.add(lk)
                        enviar_discord_betboom(lk, "Telegram @betboombra", "link", resumo)
                
                for cupom in cupons:
                    cp = cupom.upper()
                    if cp not in sorteios_ja_pegos_betboom:
                        sorteios_ja_pegos_betboom.add(cp)
                        enviar_discord_betboom(cp, "Telegram @betboombra", "cupom", resumo)
        except: pass
        time.sleep(15) # Checa o telegram a cada 15 segundos

def processar_chat_betboom(video_id: str, handle: str):
    log.info(f"🟡 BETBOOM CONECTADO: {handle}")
    try:
        chat = pytchat.create(video_id=video_id, processor=LeitorCodigoFonte(), interruptable=False)
        while chat.is_alive():
            dados = chat.get()
            if not dados: continue
            
            for raw_item in dados:
                texto_puro = unquote(json.dumps(raw_item)).replace('\\/', '/').replace('"', ' ').replace('\\n', ' ')
                urls = re.findall(r'(https?://(?:l\.)?betboom\.bet(?:\.br)?/[a-zA-Z0-9_/?=-]+)', texto_puro, re.IGNORECASE)
                cupons = re.findall(r'(?i)cupom\s*:?\s*([a-zA-Z0-9]{5,15})', texto_puro)
                
                for link in urls:
                    lk = link.lower().replace("http://", "https://")
                    if lk not in sorteios_ja_pegos_betboom:
                        sorteios_ja_pegos_betboom.add(lk)
                        enviar_discord_betboom(lk, handle, "link", "")
                
                for cp in cupons:
                    cp = cp.upper()
                    if cp not in sorteios_ja_pegos_betboom:
                        sorteios_ja_pegos_betboom.add(cp)
                        enviar_discord_betboom(cp, handle, "cupom", "")
            time.sleep(1)
    except: pass
    finally:
        with lock_bb:
            threads_bb.pop(handle, None)
            cooldown_bb[handle] = time.time() + 30 
        log.info(f"⭕ BETBOOM DESCONECTADO: {handle}")

def loop_youtube_betboom():
    while True:
        agora = time.time()
        for handle in CANAIS_BETBOOM:
            with lock_bb:
                if handle in threads_bb or (handle in cooldown_bb and agora < cooldown_bb[handle]): continue
            v_id = buscar_id_da_live(handle)
            if v_id:
                with lock_bb: threads_bb[handle] = v_id
                threading.Thread(target=processar_chat_betboom, args=(v_id, handle), daemon=True).start()
        time.sleep(60)

# =============================================================================
# 🟢 MOTOR 2: SISTEMA LOTTU / GORJETA (COM TRAVA VIP)
# =============================================================================
CHAVES_REG = re.compile(r"(palavra:|palavra chave:|frase:|chave:)", re.IGNORECASE)
LINK_REG = re.compile(r"https?://(?:lottu|lotuu|lotu)[^\s]*(?:gorjeta\.net|\.com)(?:/[^\s]*)?", re.IGNORECASE)
PUBLICO_REG = re.compile(r"https?://[^\s]+/publico(?:/[^\s]*)?", re.IGNORECASE)
GORJETA_REG = re.compile(r"(?:https?://)?[^\s]*gorjeta\.net[^\s]*", re.IGNORECASE)

def checar_mensagem_lottu(texto: str, is_vip: bool):
    encontrados = set()
    for pattern in [LINK_REG, PUBLICO_REG, GORJETA_REG]:
        for match in pattern.finditer(texto): encontrados.add(match.group(0).strip())
    links = list(encontrados)
    tem_chave = bool(CHAVES_REG.search(texto))
    return (len(links) > 0 or (tem_chave and is_vip)), links

def processar_chat_lottu(video_id: str, handle: str):
    log.info(f"🟢 LOTTU CONECTADO: {handle}")
    try:
        chat = pytchat.create(video_id=video_id, processor=LeitorCodigoFonte(), interruptable=False)
        while chat.is_alive():
            dados = chat.get()
            if not dados: continue

            for raw_item in dados:
                msg_id, autor, msg_visual, is_vip = extrair_dados_visuais(raw_item)
                texto_puro = unquote(json.dumps(raw_item)).replace('\\/', '/').replace('"', ' ').replace('\\n', ' ')

                susp_vis, links_vis = checar_mensagem_lottu(msg_visual, is_vip)
                susp_bruta, links_brutos = checar_mensagem_lottu(texto_puro, is_vip)

                if susp_vis or susp_bruta:
                    msg_id = msg_id or f"{video_id}:{autor}:{time.time()}"
                    with lock_lottu:
                        if msg_id in set_lottu_enviadas: continue
                        mensagens_lottu_enviadas.append(msg_id)
                        set_lottu_enviadas.add(msg_id)

                    cargo = "👑 [VIP]" if is_vip else "👤 [Membro]"
                    secao_links = "\n".join(f"   🔗 {lk}" for lk in set(links_vis + links_brutos))
                    txt_links = f"\n\n🌐 **Link(s) Completo(s):**\n{secao_links}" if secao_links else ""

                    alerta = (
                        f"🚨 **LOTTU / GORJETA DETECTADA** 🚨\n\n"
                        f"📺 **Canal:** `{handle}`\n"
                        f"👤 **Autor:** {autor} {cargo}\n"
                        f"💬 **MSG:** `{msg_visual[:150]}`"
                        f"{txt_links}\n\n"
                        f"📡 [Abrir Live](https://www.youtube.com/watch?v={video_id})"
                    )
                    enviar_para_discord(alerta)
            time.sleep(1)
    except: pass
    finally:
        with lock_lottu:
            threads_lottu.pop(handle, None)
            cooldown_lottu[handle] = time.time() + 30 
        log.info(f"⭕ LOTTU DESCONECTADO: {handle}")

def loop_youtube_lottu():
    while True:
        agora = time.time()
        for handle in CANAIS_LOTTU:
            with lock_lottu:
                if handle in threads_lottu or (handle in cooldown_lottu and agora < cooldown_lottu[handle]): continue
            v_id = buscar_id_da_live(handle)
            if v_id:
                with lock_lottu: threads_lottu[handle] = v_id
                threading.Thread(target=processar_chat_lottu, args=(v_id, handle), daemon=True).start()
        time.sleep(60)

# =============================================================================
# INICIALIZAÇÃO DO SUPER ROBÔ (3 MOTORES SIMULTÂNEOS)
# =============================================================================
if __name__ == "__main__":
    enviar_para_discord("🚀 **SUPER ROBÔ HYBRID (BetBoom + Lottu) ONLINE NA AWS!**")
    
    # Inicia o motor do Telegram (Roda paralelo sem bloquear)
    threading.Thread(target=loop_telegram_betboom, daemon=True).start()
    
    # Inicia o motor do YouTube Lottu
    threading.Thread(target=loop_youtube_lottu, daemon=True).start()
    
    # Inicia o motor do YouTube BetBoom no fluxo principal para manter o script vivo
    try:
        loop_youtube_betboom()
    except KeyboardInterrupt:
        sys.exit(0)
