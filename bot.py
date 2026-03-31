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
# CONTROLES GLOBAIS E LOGS
# =============================================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

threads_ativas = {}
cooldown_lives = {}
lock_threads = threading.Lock()

# Cache Inteligente: Lembra das mensagens para não dar spam (mas a 1ª passa na hora)
cache_mensagens = {}
lock_cache = threading.Lock()

def eh_duplicado(chave, ttl_segundos=600):
    agora = time.time()
    with lock_cache:
        if chave in cache_mensagens and (agora - cache_mensagens[chave]) < ttl_segundos:
            return True
        cache_mensagens[chave] = agora
        # Limpeza rápida de memória para o bot não ficar pesado ao longo dos dias
        if len(cache_mensagens) > 2000:
            remover = [k for k, v in list(cache_mensagens.items()) if (agora - v) >= ttl_segundos]
            for k in remover: del cache_mensagens[k]
        return False

# =============================================================================
# FUNÇÕES DE UTILIDADE E INTEGRAÇÃO
# =============================================================================
class LeitorCodigoFonte:
    def process(self, chat_components):
        return chat_components

def enviar_para_discord(texto: str) -> bool:
    payload = {"content": texto}
    for tentativa in range(5): # Até 5 tentativas se der Rate Limit no Discord
        try:
            resposta = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            if resposta.status_code == 429: # Trata o bloqueio do Discord (Flood)
                tempo_espera = resposta.json().get('retry_after', 1)
                time.sleep(tempo_espera + 0.5)
                continue
            resposta.raise_for_status() 
            return True
        except Exception as e:
            time.sleep(2)
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
            match_json = re.search(r'"videoId":"([^"]+)"', html)
            if match_json: return match_json.group(1)
        return None
    except:
        return None

def extrair_dados_visuais(raw_item):
    autor, msg, msg_id, is_vip = "Desconhecido", "", "", False
    try:
        renderer = raw_item.get('addChatItemAction', {}).get('item', {}).get('liveChatTextMessageRenderer', {})
        if not renderer: 
            renderer = raw_item.get('addChatItemAction', {}).get('item', {}).get('liveChatPaidMessageRenderer', {})
        if renderer:
            msg_id = renderer.get('id', "")
            autor = renderer.get('authorName', {}).get('simpleText', "Desconhecido")
            for badge in renderer.get('authorBadges', []):
                icon_type = badge.get('liveChatAuthorBadgeRenderer', {}).get('icon', {}).get('iconType', '')
                if icon_type in ['MODERATOR', 'OWNER']:
                    is_vip = True
            msg = "".join([r.get('text', '') for r in renderer.get('message', {}).get('runs', [])])
    except: pass
    return msg_id, autor, msg, is_vip

# =============================================================================
# 🟡 MOTOR 1: SISTEMA BETBOOM (TELEGRAM + YOUTUBE)
# =============================================================================
def enviar_discord_betboom(dado, canal, tipo="link", desc=""):
    desc_segura = desc.replace('<', '').replace('>', '')
    txt_desc = f"\n💬 **Contexto:** {desc_segura}\n" if desc_segura else ""
    
    if tipo == "cupom":
        msg = f"🟡 **BETBOOM - NOVO CUPOM!**\n📍 **Origem:** `{canal}`{txt_desc}\n✂️ **Clique para copiar:**\n```\n{dado}\n```"
    else:
        msg = f"💰 **BETBOOM - NOVO DROP!**\n📍 **Origem:** `{canal}`{txt_desc}\n🔗 **Link Completo:**\n{dado}"
    
    enviar_para_discord(msg)

def loop_telegram_betboom():
    log.info("📡 Radar do Telegram BetBoom iniciado!")
    while True:
        try:
            url = f"https://t.me/s/betboombra?nocache={time.time()}"
            headers = {'User-Agent': 'Mozilla/5.0', 'Cache-Control': 'no-cache'}
            html = requests.get(url, headers=headers, timeout=5).text
            mensagens = html.split('tgme_widget_message ')[1:]
            
            for msg_html in mensagens:
                match_texto = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', msg_html, re.DOTALL)
                texto_limpo, resumo = "", ""
                if match_texto:
                    texto_limpo = re.sub(r'<[^>]+>', '', re.sub(r'<br\s*/?>', '\n', match_texto.group(1))).strip()
                    resumo = texto_limpo[:100] + "..." if len(texto_limpo) > 100 else texto_limpo
                
                # Coleta de Links e Cupons
                urls = re.findall(r'(https?://[^\s<"]*betboom[^\s<"]*)', msg_html, re.IGNORECASE)
                cupons = re.findall(r'(?i)cupom\s*:?\s*([a-zA-Z0-9]{5,15})', texto_limpo)
                
                for link in urls:
                    lk = link.lower().replace("http://", "https://")
                    if not eh_duplicado(f"tg_link_{lk}", ttl_segundos=1800): # 30 min cooldown no Telegram
                        enviar_discord_betboom(lk, "Telegram @betboombra", "link", resumo)
                
                for cp in cupons:
                    cp = cp.upper()
                    if not eh_duplicado(f"tg_cupom_{cp}", ttl_segundos=1800):
                        enviar_discord_betboom(cp, "Telegram @betboombra", "cupom", resumo)
        except Exception: 
            pass
        time.sleep(5)

def processar_chat_betboom(video_id: str, handle: str):
    log.info(f"🟡 BETBOOM CONECTADO: {handle}")
    try:
        chat = pytchat.create(video_id=video_id, processor=LeitorCodigoFonte(), interruptable=False, topchat_only=False)
        while chat.is_alive():
            dados = chat.get()
            if not dados: continue
            
            for raw_item in dados:
                texto_puro = unquote(json.dumps(raw_item)).replace('\\/', '/').replace('\\n', ' ')
                
                urls = re.findall(r'(https?://[^\s"<>]*betboom[^\s"<>]*)', texto_puro, re.IGNORECASE)
                cupons = re.findall(r'(?i)cupom\s*:?\s*([a-zA-Z0-9]{5,15})', texto_puro)
                
                for link in urls:
                    lk = link.lower().replace("http://", "https://")
                    if not eh_duplicado(f"yt_link_{lk}_{handle}"):
                        enviar_discord_betboom(lk, handle, "link", "")
                
                for cp in cupons:
                    cp = cp.upper()
                    if not eh_duplicado(f"yt_cupom_{cp}_{handle}"):
                        enviar_discord_betboom(cp, handle, "cupom", "")
    except Exception as e:
        log.error(f"Erro BB em {handle}: {e}")
    finally:
        with lock_threads:
            threads_ativas.pop(f"BB_{handle}", None)
            cooldown_lives[f"BB_{handle}"] = time.time() + 30 
        log.info(f"⭕ BETBOOM DESCONECTADO: {handle}")

# =============================================================================
# 🟢 MOTOR 2: SISTEMA LOTTU / GORJETA
# =============================================================================
LINK_REG = re.compile(r"(https?://[^\s\"<>]*(?:lottu|lotuu|lotu|gorjeta\.net|gorjeta\.com)[^\s\"<>]*)", re.IGNORECASE)
PUBLICO_REG = re.compile(r"(https?://[^\s\"<>]+/publico[^\s\"<>]*)", re.IGNORECASE)
CHAVES_REG = re.compile(r"(palavra:|palavra chave:|frase:|chave:)\s*([a-zA-Z0-9_]+)", re.IGNORECASE)

def processar_chat_lottu(video_id: str, handle: str):
    log.info(f"🟢 LOTTU CONECTADO: {handle}")
    try:
        chat = pytchat.create(video_id=video_id, processor=LeitorCodigoFonte(), interruptable=False, topchat_only=False)
        while chat.is_alive():
            dados = chat.get()
            if not dados: continue

            for raw_item in dados:
                msg_id, autor, msg_visual, is_vip = extrair_dados_visuais(raw_item)
                texto_puro = unquote(json.dumps(raw_item)).replace('\\/', '/').replace('\\n', ' ')

                # Busca links completos nos dois contextos
                links_encontrados = set(LINK_REG.findall(msg_visual) + PUBLICO_REG.findall(msg_visual) +
                                        LINK_REG.findall(texto_puro) + PUBLICO_REG.findall(texto_puro))
                
                tem_chave = CHAVES_REG.search(msg_visual) or CHAVES_REG.search(texto_puro)

                if links_encontrados or (tem_chave and is_vip):
                    id_unico = msg_id or f"{video_id}:{autor}:{time.time()}"
                    
                    if not eh_duplicado(f"lottu_{id_unico}", ttl_segundos=60): # 1 min cooldown para flood exato
                        cargo = "👑 [VIP/MOD]" if is_vip else "👤 [Membro]"
                        
                        secao_links = "\n".join(f"🔗 {lk}" for lk in links_encontrados)
                        txt_links = f"\n\n🌐 **Link(s) Completo(s):**\n{secao_links}" if secao_links else ""
                        
                        txt_senha = ""
                        if tem_chave:
                            senha = tem_chave.group(2) if tem_chave.groups() else "Desconhecida"
                            txt_senha = f"\n\n🔑 **Palavra Identificada (Clica e Copia):**\n```\n{senha}\n```"

                        alerta = (
                            f"🚨 **LOTTU / GORJETA DETECTADA** 🚨\n"
                            f"📺 **Canal:** `{handle}`\n"
                            f"👤 **Autor:** {autor} {cargo}\n"
                            f"💬 **Mensagem Original:**\n> {msg_visual[:200]}"
                            f"{txt_links}"
                            f"{txt_senha}\n\n"
                            f"📡 [Assistir Live Agora](https://www.youtube.com/watch?v={video_id})"
                        )
                        enviar_para_discord(alerta)
                        
    except Exception as e:
        log.error(f"Erro Lottu em {handle}: {e}")
    finally:
        with lock_threads:
            threads_ativas.pop(f"LOTTU_{handle}", None)
            cooldown_lives[f"LOTTU_{handle}"] = time.time() + 30 
        log.info(f"⭕ LOTTU DESCONECTADO: {handle}")

# =============================================================================
# ORQUESTRADOR DE LIVES (RODA OS DOIS MOTORES DE FORMA EFICIENTE)
# =============================================================================
def checar_novas_lives():
    while True:
        agora = time.time()
        
        # Inicia threads BetBoom
        for handle in CANAIS_BETBOOM:
            chave = f"BB_{handle}"
            with lock_threads:
                if chave in threads_ativas or (chave in cooldown_lives and agora < cooldown_lives[chave]): continue
            v_id = buscar_id_da_live(handle)
            if v_id:
                with lock_threads: threads_ativas[chave] = v_id
                threading.Thread(target=processar_chat_betboom, args=(v_id, handle), daemon=True).start()

        # Inicia threads Lottu
        for handle in CANAIS_LOTTU:
            chave = f"LOTTU_{handle}"
            with lock_threads:
                if chave in threads_ativas or (chave in cooldown_lives and agora < cooldown_lives[chave]): continue
            v_id = buscar_id_da_live(handle)
            if v_id:
                with lock_threads: threads_ativas[chave] = v_id
                threading.Thread(target=processar_chat_lottu, args=(v_id, handle), daemon=True).start()

        time.sleep(60) # Checa por novas lives a cada 1 minuto

if __name__ == "__main__":
    enviar_para_discord("🚀 **SUPER ROBÔ HYBRID (V3 Turbo) ONLINE!**\n✅ *Módulo Anti-Queda Ativado*\n✅ *Filtro de Discord Corrigido*")
    
    # Motor Telegram (Independente)
    threading.Thread(target=loop_telegram_betboom, daemon=True).start()
    
    # Orquestrador YouTube (Mantém o programa vivo)
    try:
        checar_novas_lives()
    except KeyboardInterrupt:
        sys.exit(0)
