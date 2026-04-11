#!/usr/bin/env python3
# coding: utf-8
"""
Tipster SaaS V150 - COMPLETE SUITE (SOKKERPRO EDITION)
Autor: O Programador do Universo
Status: PRODUCTION READY - SOKKERPRO DIRECT LINK
"""
import sys
import os
import time
import threading
import json
import datetime
import math
import random
import secrets
import string
import uuid
import logging
from concurrent.futures import ThreadPoolExecutor

# --- VERIFICAÇÃO DE DEPENDÊNCIAS ---
print("--- [BOOT] SISTEMA V150 INICIADO ---")
try:
    import urllib3
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    from flask import Flask, render_template_string, request, redirect, url_for, flash, jsonify, session
    from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
    from werkzeug.security import generate_password_hash, check_password_hash
    from pymongo import MongoClient
    from bson.objectid import ObjectId
    print("✅ Bibliotecas carregadas.")
except ImportError as e:
    print(f"❌ ERRO CRÍTICO: Faltam bibliotecas. Erro: {e}")
    sys.exit(1)

# ==============================================================================
# 1. CONFIGURAÇÃO GLOBAL
# ==============================================================================
sys.stdout.reconfigure(encoding='utf-8')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.CRITICAL)
BR_TZ = datetime.timezone(datetime.timedelta(hours=-3))

# --- CHAVES DO SISTEMA ---
ONESIGNAL_APP_ID = "b626af21-a8a9-4ae0-9053-382424302ace"
ONESIGNAL_API_KEY = "os_v2_app_wytk6inivffobecthascimbkz3jqjuny5olea7ex2lbhga5ikqiyevtlrr6nnuf3hctrpc7vb24d3uj6hhucklspaqxjul2uaolthqi"
PORTA_SERVIDOR = int(os.environ.get("PORT", 5000))
REFRESH_RATE = 20 # Segundos para o Daemon varrer a SokkerPRO

# --- CONFIGURAÇÃO RECAPTCHA ---
RECAPTCHA_SITE_KEY = "6LeMAlAsAAAAABBP5Wom0blZwNzAdtYTp2G81hHb" 
RECAPTCHA_SECRET_KEY = "6LeMAlAsAAAAAG3dgk_UjIMGcC9tpL04q1JDCXDc"

def verify_recaptcha(token):
    if not token: return False
    try:
        r = requests.post('https://www.google.com/recaptcha/api/siteverify',
                          data={'secret': RECAPTCHA_SECRET_KEY, 'response': token}, timeout=5)
        return r.json().get('success', False)
    except:
        return False

# ==============================================================================
# 2. BANCO DE DADOS (MONGO DB / FALLBACK)
# ==============================================================================
MONGO_URI = "mongodb+srv://maryllemos126_db_user:elite123@cluster0.6vvln2z.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
DB_ONLINE = False
users_col = None; codes_col = None; matches_col = None

class MockCursor:
    def __init__(self, data): self.data = data
    def sort(self, key, direction=1):
        try: self.data.sort(key=lambda x: str(x.get(key, '')), reverse=(direction == -1))
        except: pass
        return self
    def limit(self, n): self.data = self.data[:n]; return self
    def __iter__(self): return iter(self.data)
    def __list__(self): return self.data

class MockCollection:
    def __init__(self, name): self.name = name; self.data = []
    def find_one(self, q):
        for i in self.data:
            if all(str(i.get(k)) == str(v) for k, v in q.items()): return i
        return None
    def find(self, q={}):
        res = [i for i in self.data if all(str(i.get(k)) == str(v) for k, v in q.items())]
        return MockCursor(res)
    def insert_one(self, d): d['_id'] = str(uuid.uuid4()); self.data.append(d)
    def update_one(self, q, u):
        x = self.find_one(q)
        if x:
            if '$set' in u:
                for k, v in u['$set'].items(): x[k] = v
            if '$addToSet' in u:
                for k, v in u['$addToSet'].items():
                    if k not in x: x[k] = []
                    if v not in x[k]: x[k].append(v)
            if '$pull' in u:
                for k, v in u['$pull'].items():
                    if k in x and v in x[k]: x[k].remove(v)
    def delete_one(self, q):
        x = self.find_one(q); 
        if x: self.data.remove(x)

try:
    print("⏳ Conectando MongoDB...")
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000, tlsAllowInvalidCertificates=True)
    client.admin.command('ping')
    db = client['elite_v150_sokker_db']
    users_col = db['users']; codes_col = db['codes']; matches_col = db['match_cache']
    DB_ONLINE = True
    print("✅ MongoDB CONECTADO.")
except Exception as e:
    print(f"❌ ERRO MONGO: {e}")
    print("⚠️ MODO MOCK ATIVADO (RAM).")
    users_col = MockCollection('users'); codes_col = MockCollection('codes'); matches_col = MockCollection('match_cache')

# ==============================================================================
# 3. ENGINE V150 SOKKERPRO (O CÉREBRO SUPREMO)
# ==============================================================================
class SokkerProMasterEngine:
    def __init__(self):
        self.base_url = "https://m2.sokkerpro.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        adapter = HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1))
        self.session.mount('https://', adapter)
        
        self.carteira_global = {} # Cache em RAM estruturado por Data -> ID
        
    def _safe_float(self, value):
        try:
            if isinstance(value, str) and '#' in value: return float(value.split('#')[0])
            return float(value)
        except: return 0.0

    def _safe_str(self, value):
        return str(value) if value is not None else ""

    def get_jogos_do_dia(self, date_str):
        """1. ROTA FIXTURES: Busca lista diária e Link TV"""
        url = f"{self.base_url}/home/fixtures/{date_str}/utc/mini"
        try:
            r = self.session.get(url, timeout=10).json()
            jogos = {}
            for league in r.get('data', {}).get('sortedCategorizedFixtures', []):
                for m in league.get('fixtures', []):
                    mid = str(m.get('fixtureId'))
                    jogos[mid] = {
                        'mid': mid,
                        'league': league.get('leagueName'),
                        'home': m.get('localTeamName'),
                        'away': m.get('visitorTeamName'),
                        'status': m.get('status'),
                        'time': m.get('startingAtTime'),
                        'score_h': m.get('localTeamScore', 0),
                        'score_a': m.get('visitorTeamScore', 0),
                        'link_tv': m.get('linkTV', ''),
                        'is_live': m.get('status') in ['LIVE', 'HT', '1H', '2H', 'ET', 'PEN']
                    }
            return jogos
        except: return {}

    def get_radar_live(self):
        """2 e 3. ROTA LIVESCORES: Busca DAPM e Pressão Ao Vivo"""
        url = f"{self.base_url}/livescores"
        try:
            r = self.session.get(url, timeout=10).json()
            live_radar = {}
            for league in r.get('data', {}).get('sortedCategorizedFixtures', []):
                for m in league.get('fixtures', []):
                    mid = str(m.get('fixtureId'))
                    live_radar[mid] = {
                        'minuto': str(m.get('minute', '')),
                        'dapm_total_h': self._safe_float(m.get('localDapmTotal')),
                        'dapm_total_a': self._safe_float(m.get('visitorDapmTotal')),
                        'pressao_bar_h': self._safe_float(m.get('localPressureBarMedia')),
                        'pressao_bar_a': self._safe_float(m.get('visitorPressureBarMedia')),
                        'posse_h': m.get('localBallPossession', 50),
                        'ataques_perigosos_h': m.get('localAttacksDangerousAttacks', 0),
                        'ataques_perigosos_a': m.get('visitorAttacksDangerousAttacks', 0)
                    }
            return live_radar
        except: return {}

    def get_dossie_partida(self, fixture_id):
        """4, 6 e 7. ROTA FIXTURE ID: Odds Bet365, Stats Avançadas e IA"""
        url = f"{self.base_url}/fixture/{fixture_id}"
        try:
            r = self.session.get(url, timeout=10).json()
            if not r.get('success'): return None
            d = r.get('data', {})
            return {
                'odds': {
                    'home': self._safe_float(d.get('BET365_VENCEDOR_HOME')),
                    'away': self._safe_float(d.get('BET365_VENCEDOR_AWAY')),
                    'over_25': self._safe_float(d.get('BET365_GOLS_OVER_2_5')),
                    'canto_over_9': self._safe_float(d.get('BET365_CANTO_OVER_9')),
                },
                'stats': {
                    'chutes_alvo_h': self._safe_float(d.get('medias_home_shots_on_target')),
                    'chutes_alvo_a': self._safe_float(d.get('medias_away_shots_on_target'))
                },
                'prognosticos': d.get('prognosticos', {})
            }
        except: return None

    def get_lineups_e_ratings(self, fixture_id):
        """5. ROTA LINEUPS: Puxa destaques em campo"""
        url = f"{self.base_url}/fixture/{fixture_id}/lineups"
        try:
            r = self.session.get(url, timeout=5).json()
            destaques = []
            for team in r:
                if isinstance(team, dict):
                    nota = self._safe_float(team.get('pontos'))
                    if nota >= 7.5: # Pega só quem tá destruindo o jogo
                        destaques.append({'nome': team.get('player_name'), 'nota': nota})
            return destaques
        except: return []

    def gerar_tips_inteligentes(self, radar, dossie):
        """Cérebro que cruza tudo (V150)"""
        tips = []; is_premium = False
        if not radar or not dossie: return tips, is_premium

        pressao_h = radar.get('pressao_bar_h', 0)
        pressao_a = radar.get('pressao_bar_a', 0)
        dapm_h = radar.get('dapm_total_h', 0)
        dapm_a = radar.get('dapm_total_a', 0)
        odd_h = dossie['odds']['home']
        odd_over = dossie['odds']['over_25']
        prog_over = self._safe_float(dossie['prognosticos'].get('over_2_5', 0))

        # Tip 1: Amasso em Casa (Pressão Absoluta)
        if dapm_h >= 1.5 and pressao_h > 60 and odd_h >= 1.50:
            tips.append("Casa Vence Live")
            is_premium = True
        elif dapm_a >= 1.5 and pressao_a > 60:
            tips.append("Fora Vence Live")

        # Tip 2: Jogo Aberto (Over Gols Baseado em IA + Odds)
        if prog_over > 65.0 and odd_over > 1.40 and (dapm_h + dapm_a) > 2.0:
            tips.append("Over 2.5 Gols")
            is_premium = True

        # Tip 3: Mercado de Cantos (Muito ataque dos dois lados)
        if (dapm_h + dapm_a) >= 2.5 and dossie['odds']['canto_over_9'] > 0:
            tips.append("Over 9 Cantos")

        return tips, is_premium

    def send_onesignal(self, msg, title="Sokker Alert", data=None):
        if "SUA_REST" in ONESIGNAL_API_KEY: return
        try:
            payload = {
                "app_id": ONESIGNAL_APP_ID, "included_segments": ["Total Subscriptions"],
                "headings": {"en": title}, "contents": {"en": msg},
                "data": data or {}, "android_group": "tipster_saas",
                "large_icon": "https://cdn-icons-png.flaticon.com/512/2102/2102633.png"
            }
            requests.post("https://onesignal.com/api/v1/notifications", headers={"Content-Type": "application/json", "Authorization": f"Basic {ONESIGNAL_API_KEY}"}, data=json.dumps(payload), timeout=5)
        except Exception as e: print(f"❌ Erro Push: {e}")

    def engine_daemon(self):
        """Loop Principal em Background"""
        print("⚙️ [DAEMON V150] Serviço SokkerPRO Iniciado")
        while True:
            hoje = datetime.datetime.now(BR_TZ).strftime('%Y-%m-%d')
            try:
                # 1. Pega Grade
                jogos_dia = self.get_jogos_do_dia(hoje)
                if hoje not in self.carteira_global: self.carteira_global[hoje] = {}

                # 2. Pega Radar Ao Vivo Global (Uma requisição salva todas as métricas)
                radar_live = self.get_radar_live()

                for mid, info in jogos_dia.items():
                    if mid not in self.carteira_global[hoje]:
                        self.carteira_global[hoje][mid] = {'info': info, 'live': {}, 'dossie': {}, 'destaques': [], 'tips': [], 'is_premium': False}
                    
                    # Atualiza placar/status
                    self.carteira_global[hoje][mid]['info'] = info
                    
                    # Se tiver no radar ao vivo, cruza dados pesados
                    if mid in radar_live:
                        live_data = radar_live[mid]
                        self.carteira_global[hoje][mid]['live'] = live_data
                        
                        # Gatilho: Só puxa Dossie/Odds pesadas se a pressão estiver alta (Economia de Requisição)
                        if (live_data.get('dapm_total_h', 0) > 1.2 or live_data.get('dapm_total_a', 0) > 1.2) and not self.carteira_global[hoje][mid].get('dossie'):
                            dossie = self.get_dossie_partida(mid)
                            destaques = self.get_lineups_e_ratings(mid)
                            
                            if dossie:
                                self.carteira_global[hoje][mid]['dossie'] = dossie
                                self.carteira_global[hoje][mid]['destaques'] = destaques
                                tips, is_prem = self.gerar_tips_inteligentes(live_data, dossie)
                                self.carteira_global[hoje][mid]['tips'] = tips
                                self.carteira_global[hoje][mid]['is_premium'] = is_prem
                                
                                # Alerta Push se gerar tip VIP
                                if tips and is_prem:
                                    msg = f"🔥 ALERTA DE PRESSÃO!\n⚡ DAPM: {live_data['dapm_total_h']}x{live_data['dapm_total_a']}\nTips: {', '.join(tips)}"
                                    self.send_onesignal(msg, title=f"{info['home']} x {info['away']}", data={"mid": mid})

            except Exception as e: print(f"❌ [DAEMON ERRO] {e}")
            time.sleep(REFRESH_RATE)

    def get_json_data(self, target_date, user_role, user_plan, user_watchlist):
        """Formata o JSON pro Frontend consumir (Renderização de Cards HTML)"""
        carteira_dia = self.carteira_global.get(target_date, {})
        response = []
        
        ordem = sorted([(mid, data) for mid, data in carteira_dia.items()], key=lambda x: x[1]['info'].get('time', '00:00'))
        
        for mid, wrap in ordem:
            info = wrap.get('info', {})
            live = wrap.get('live', {})
            dossie = wrap.get('dossie', {})
            
            status_long = info.get('status', '').upper()
            display_time = live.get('minuto') + "'" if live.get('minuto') else info.get('time', '00:00')
            if status_long in ['FT', 'FINISH', 'AET']: display_time = "FIM"
            elif status_long == 'HT': display_time = "INT"
            elif status_long in ['NS', 'POSTPONED', 'CANC']: display_time = info.get('time', '00:00')
            
            sh = int(info.get('score_h', 0))
            sa = int(info.get('score_a', 0))
            
            # --- Tratamento de Greens/Reds (Básico) ---
            tips_display = []
            green_count = red_count = 0
            is_finished = (display_time == "FIM")
            
            for tip in wrap.get('tips', []):
                tip_clean = tip.lower().strip(); res = 0
                if "over" in tip_clean:
                    if (sh+sa) > float(tip.split()[1]): res = 1
                    elif is_finished: res = -1
                elif "casa" in tip_clean:
                    if is_finished: res = 1 if sh > sa else -1
                elif "fora" in tip_clean:
                    if is_finished: res = 1 if sa > sh else -1
                
                if res == 1: green_count += 1
                if res == -1: red_count += 1
                tips_display.append({'text': tip, 'res': res})
            
            card_status = "PENDING"
            if red_count > 0: card_status = "RED"
            elif green_count == len(tips_display) and len(tips_display) > 0: card_status = "GREEN"

            should_blur = (user_role != 'admin' and user_plan != 'vip') and wrap.get('is_premium', False) and not is_finished and card_status != "GREEN"
            
            # Pega odds e destaque para o card
            odd_casa = dossie.get('odds', {}).get('home', 0.0)
            odd_over = dossie.get('odds', {}).get('over_25', 0.0)
            destaques_str = " | ".join([f"{d['nome']} ({d['nota']})" for d in wrap.get('destaques', [])[:1]])
            
            response.append({
                'mid': mid, 'league': info.get('league'), 'time': display_time, 'is_live': info.get('is_live', False),
                'home': info.get('home'), 'away': info.get('away'), 
                'h_logo': "https://cdn-icons-png.flaticon.com/512/2102/2102633.png", # Fallback Sokker
                'a_logo': "https://cdn-icons-png.flaticon.com/512/2102/2102633.png",
                'score': f"{sh} - {sa}" if not should_blur else "? - ?",
                'tips': tips_display if not should_blur else [{'text': 'DESBLOQUEAR VIP', 'res': 0}], 
                'is_premium': wrap.get('is_premium', False), 'blur': should_blur,
                'is_watched': mid in user_watchlist, 'status': card_status,
                # Novos dados SokkerPRO para o JS:
                'link_tv': info.get('link_tv', ''),
                'dapm_h': live.get('dapm_total_h', 0), 'dapm_a': live.get('dapm_total_a', 0),
                'press_h': live.get('pressao_bar_h', 0), 'press_a': live.get('pressao_bar_a', 0),
                'posse_h': live.get('posse_h', 50),
                'odd_casa': odd_casa, 'odd_over': odd_over,
                'destaque': destaques_str
            })
        return response

engine = None
try: engine = SokkerProMasterEngine()
except Exception as e: print(f"❌ Engine Init: {e}")

# ==============================================================================
# 4. FLASK WEB APP & UI
# ==============================================================================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-sokker-v150'
login_manager = LoginManager(app)
login_manager.login_view = 'route_login'

class User(UserMixin):
    def __init__(self, d):
        self.id = str(d['_id']); self.username = d.get('username'); self.password = d.get('password')
        self.role = d.get('role','user'); self.plan = d.get('plan','free')
        self.days = d.get('days_left',0); self.watchlist = d.get('watchlist',[])
        self.expiration = d.get('expiration_date')

@login_manager.user_loader
def load_user(uid):
    u = users_col.find_one({"_id": ObjectId(uid)}) if DB_ONLINE else users_col.find_one({"_id": uid})
    return User(u) if u else None

def render_page(content):
    BETANO_MODAL_HTML = """
    <div id="betano-modal" class="fixed inset-0 bg-black/80 backdrop-blur-sm hidden z-50 flex items-end sm:items-center justify-center transition-opacity duration-300">
        <div class="bg-[#1a2c38] w-full sm:w-96 rounded-t-2xl sm:rounded-2xl shadow-2xl transform transition-transform duration-300 overflow-hidden border border-white/10">
            <div class="bg-[#121f28] p-4 flex justify-between items-center border-b border-white/5">
                <h3 class="text-white font-bold text-lg flex items-center gap-2"><i class="fas fa-bell text-orange-500"></i> Alerta SokkerPRO</h3>
                <button onclick="closeBetanoModal()" class="text-gray-400 hover:text-white"><i class="fas fa-times text-xl"></i></button>
            </div>
            <div class="p-6 space-y-6">
                <div class="flex justify-between items-center">
                    <span class="text-sm font-bold text-white">Notificar Altas Pressões</span>
                    <label class="relative inline-flex items-center cursor-pointer">
                        <input type="checkbox" class="sr-only peer" checked>
                        <div class="w-11 h-6 bg-gray-700 rounded-full peer peer-checked:bg-orange-500 peer-checked:after:translate-x-full after:absolute after:top-0.5 after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all"></div>
                    </label>
                </div>
                <div class="grid grid-cols-2 gap-3">
                    <button class="bg-orange-500/20 text-orange-400 border border-orange-500 py-2 px-3 rounded-lg text-xs font-bold flex items-center justify-center gap-2"><i class="fas fa-fire"></i> DAPM > 1.5</button>
                    <button class="bg-[#2a3c48] text-gray-300 py-2 px-3 rounded-lg text-xs font-bold border border-transparent hover:border-orange-500"><i class="fas fa-futbol"></i> Gols</button>
                </div>
                <button onclick="saveBetanoPreferences()" class="w-full bg-orange-500 hover:bg-orange-400 text-white font-bold py-3 rounded-xl shadow-lg transition transform active:scale-95">SALVAR RADAR</button>
            </div>
        </div>
    </div>
    """

    BASE_HTML = """
    <!DOCTYPE html><html lang="pt-br"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Tipster V150 // SOKKERPRO SUPREME</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Inter:wght@400;700;900&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; background-color: #050505; color: #e2e8f0; min-height: 100vh; overflow-x: hidden; }
        .bg-grid { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; z-index: -1; background: linear-gradient(rgba(0, 20, 30, 0.9), rgba(0, 10, 15, 0.95)), repeating-linear-gradient(0deg, transparent, transparent 1px, rgba(0, 255, 100, 0.03) 1px, rgba(0, 255, 100, 0.03) 20px), repeating-linear-gradient(90deg, transparent, transparent 1px, rgba(0, 255, 100, 0.03) 1px, rgba(0, 255, 100, 0.03) 20px); background-size: 100%% 100%%; }
        .glass { background: rgba(10, 25, 35, 0.6); backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.08); box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.5); }
        input { background: rgba(0, 0, 0, 0.5) !important; border: 1px solid rgba(255, 255, 255, 0.1) !important; color: white !important; font-family: 'Share Tech Mono', monospace; }
        input:focus { border-color: #22c55e !important; box-shadow: 0 0 15px rgba(34, 197, 94, 0.2); outline: none; }
    </style>
    </head>
    <body class="flex flex-col">
        <div class="bg-grid"></div>
        %s 
        <div class="container mx-auto px-4 flex-grow relative z-10">%s</div> 
        <footer class="mt-auto py-4 text-center text-xs text-gray-500 relative z-10 border-t border-white/5">
            <span class="font-mono text-green-500">SOKKERPRO RADAR: ONLINE</span> | &copy; 2026 Elite V75 SaaS V150
        </footer> 
        %s 
    </body></html>
    """
    
    nav = ""
    if current_user.is_authenticated:
        admin_btn = """<a href="/admin" class="mr-3 text-[10px] font-bold text-red-500 border border-red-500/50 px-2 py-1 rounded shadow-[0_0_10px_rgba(239,68,68,0.3)]"><i class="fas fa-user-secret"></i> ADMIN</a>""" if current_user.role == 'admin' else ""
        nav = f"""
        <nav class="glass sticky top-0 z-50 px-4 py-3 mb-4 border-b border-white/10">
            <div class="container mx-auto flex justify-between items-center">
                <div class="font-bold text-xl text-white flex items-center gap-2">
                    <i class="fas fa-satellite-dish text-green-500 animate-pulse"></i> 
                    <span>Tipster <span class="text-[10px] bg-green-500/20 text-green-300 px-1.5 py-0.5 rounded border border-green-500/30">V150 SUPREME</span></span>
                </div>
                <div class="flex items-center">
                    {admin_btn}
                    <span class="hidden md:inline mr-4 text-xs font-bold text-gray-300 font-mono">{current_user.username}</span>
                    <a href="/logout" class="text-red-400 hover:text-red-200 transition"><i class="fas fa-sign-out-alt"></i></a>
                </div>
            </div>
        </nav>
        """

    return render_template_string(BASE_HTML % (nav, content, BETANO_MODAL_HTML))

@app.route('/')
def route_index(): return redirect(url_for('route_dashboard')) if current_user.is_authenticated else redirect(url_for('route_login'))

@app.route('/login', methods=['GET', 'POST'])
def route_login():
    if request.method == 'POST':
        if not verify_recaptcha(request.form.get('g-recaptcha-response')): flash('Captcha Falhou', 'error')
        else:
            user = users_col.find_one({'username': request.form.get('username')})
            if user and check_password_hash(user['password'], request.form.get('password')):
                login_user(User(user)); return redirect(url_for('route_dashboard'))
    return render_page(f"""
    <script src="https://www.google.com/recaptcha/api.js" async defer></script>
    <div class="min-h-[80vh] flex items-center justify-center">
        <div class="w-full max-w-md glass p-8 rounded-2xl text-center relative">
            <h2 class="text-3xl font-bold mb-8 text-white">LOGIN <span class="text-green-500">V150</span></h2>
            <form method="POST" class="space-y-6">
                <input type="text" name="username" class="w-full px-5 py-4 rounded-xl text-center" placeholder="USUÁRIO" required>
                <input type="password" name="password" class="w-full px-5 py-4 rounded-xl text-center" placeholder="SENHA" required>
                <div class="flex justify-center"><div class="g-recaptcha" data-sitekey="{RECAPTCHA_SITE_KEY}" data-theme="dark"></div></div>
                <button class="w-full bg-green-600 hover:bg-green-500 text-white font-bold py-4 rounded-xl shadow-lg">ACESSAR SOKKERPRO</button>
            </form>
            <p class="mt-8 text-sm"><a href="/register" class="text-green-400 font-bold">Solicitar Conta</a></p>
        </div>
    </div>""")

@app.route('/register', methods=['GET', 'POST'])
def route_register():
    if request.method == 'POST':
        if users_col.find_one({'username': request.form.get('username')}): flash('Usuário já existe', 'error')
        else:
            users_col.insert_one({'username': request.form.get('username'), 'password': generate_password_hash(request.form.get('password')), 'role': 'user', 'plan': 'free', 'days_left': 0, 'watchlist': []})
            return redirect(url_for('route_login'))
    return render_page("""
    <div class="min-h-[80vh] flex items-center justify-center">
        <div class="w-full max-w-md glass p-8 rounded-2xl text-center">
            <h2 class="text-3xl font-bold mb-8 text-white">REGISTRO</h2>
            <form method="POST" class="space-y-6">
                <input type="text" name="username" class="w-full px-5 py-4 rounded-xl text-center" placeholder="USUÁRIO" required>
                <input type="password" name="password" class="w-full px-5 py-4 rounded-xl text-center" placeholder="SENHA" required>
                <button class="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-4 rounded-xl">REGISTRAR</button>
            </form>
        </div>
    </div>""")

@app.route('/dashboard')
@login_required
def route_dashboard():
    DASHBOARD_HTML = """
    <script>
    let currentDateOffset = 0; let currentMatchId = null;
    function openBetanoModal(mid) { currentMatchId = mid; document.getElementById('betano-modal').classList.remove('hidden'); document.getElementById('betano-modal').classList.add('flex'); }
    function closeBetanoModal() { document.getElementById('betano-modal').classList.add('hidden'); document.getElementById('betano-modal').classList.remove('flex'); }
    async function saveBetanoPreferences() { try { await fetch('/api/toggle_watch/' + currentMatchId); loadData(currentDateOffset); } catch(e){} closeBetanoModal(); }
    
    async function loadData(offset, isAuto=false) {
        if(!isAuto) { currentDateOffset = offset; document.getElementById('grid-pending').innerHTML = '<div class="col-span-full text-center text-gray-400 py-10 animate-pulse font-mono">SCANNING SOKKERPRO DATA...</div>'; }
        const date = new Date(); date.setDate(date.getDate() + currentDateOffset);
        document.getElementById('date-display').innerText = (offset===0)?'HOJE':(offset===-1)?'ONTEM':(offset===1)?'AMANHÃ': String(date.getDate()).padStart(2,'0')+'/'+String(date.getMonth()+1).padStart(2,'0');
        try { 
            const r = await fetch('/api/get_data?offset=' + currentDateOffset); const data = await r.json();
            document.getElementById('grid-pending').innerHTML = buildHTML(data);
        } catch(e) {}
    }

    function buildHTML(games) {
        if (!games || games.length === 0) return '<div class="col-span-full text-center text-gray-500 text-sm py-4 font-mono">NENHUM JOGO NO RADAR.</div>';
        let html = '';
        games.forEach(g => {
            let tipsHtml = '';
            g.tips.forEach(t => { tipsHtml += `<span class="bg-gray-700 px-2 py-1 rounded text-[10px] mr-1 font-mono uppercase">${t.text}</span>`; });
            
            // Lógica UI do Motor SokkerPro
            let dapmBar = ''; let extras = '';
            if(g.is_live && !g.blur) {
                let pressH = Math.min(100, g.press_h); let pressA = Math.min(100, g.press_a);
                dapmBar = `
                <div class="mt-2 pt-2 border-t border-white/5">
                    <div class="flex justify-between text-[9px] text-gray-400 font-mono mb-1">
                        <span class="text-blue-400">🔥 P:${g.press_h} | DAPM:${g.dapm_h}</span>
                        <span>POSSE: ${g.posse_h}%</span>
                        <span class="text-red-400">🔥 P:${g.press_a} | DAPM:${g.dapm_a}</span>
                    </div>
                    <div class="w-full bg-gray-800 rounded-full h-1.5 flex">
                        <div class="bg-blue-500 h-1.5 rounded-l-full" style="width: ${pressH}%"></div>
                        <div class="bg-red-500 h-1.5 rounded-r-full" style="width: ${pressA}%"></div>
                    </div>
                </div>`;
            }
            if(!g.blur && (g.odd_casa > 0 || g.destaque)) {
                extras = `<div class="mt-2 flex justify-between items-center text-[9px] bg-black/30 p-1.5 rounded">
                    <span class="text-yellow-400 font-mono"><i class="fas fa-coins"></i> Bet365 Casa: ${g.odd_casa} | O2.5: ${g.odd_over}</span>
                    ${g.destaque ? `<span class="text-green-400 font-bold truncate max-w-[120px]"><i class="fas fa-star"></i> ${g.destaque}</span>` : ''}
                </div>`;
            }

            let tvBtn = g.link_tv ? `<a href="${g.link_tv}" target="_blank" class="text-blue-400 hover:text-white mx-2"><i class="fas fa-tv"></i></a>` : '';

            if(g.blur){ html += `<div class="glass rounded-xl p-4 mb-4 relative overflow-hidden border border-yellow-500/30"><div class="absolute inset-0 bg-black/60 backdrop-blur-md z-10 flex flex-col items-center justify-center text-center p-4"><i class="fas fa-lock text-3xl text-yellow-400 mb-2 animate-bounce"></i><h3 class="text-yellow-400 font-bold text-sm tracking-widest uppercase font-mono">DIAMOND VIP</h3></div><div class="opacity-30 filter blur-sm"><div class="text-center font-bold text-2xl my-2">? - ?</div></div></div>`; } 
            else { 
                html += `<div class="glass rounded-xl p-4 transition duration-300 hover:scale-[1.02] mb-4 relative border border-white/5 hover:border-green-500/30">
                    ${g.is_premium ? '<div class="absolute top-0 right-0 bg-yellow-500 text-black text-[9px] font-bold px-2 py-0.5 rounded-bl-lg shadow-lg font-mono">💎 VIP</div>' : ''}
                    <div class="flex justify-between items-center mb-2 pb-1">
                        <span class="text-[10px] font-bold text-gray-400 truncate w-2/3 uppercase tracking-wider font-mono">${g.league}</span>
                        <div class="flex items-center">
                            ${tvBtn}
                            <button onclick="openBetanoModal('${g.mid}')" class="text-lg ${g.is_watched ? 'text-orange-500' : 'text-gray-500'} hover:scale-110 transition mr-2"><i class="fas fa-bell"></i></button>
                            <span class="text-[10px] font-bold px-2 py-0.5 rounded font-mono ${g.is_live ? 'bg-red-600 animate-pulse text-white' : 'bg-white/20 text-white'}">${g.time}</span>
                        </div>
                    </div>
                    <div class="flex justify-between items-center mb-2">
                        <span class="text-[11px] font-bold text-center text-white truncate w-1/3">${g.home}</span>
                        <div class="text-2xl font-black text-white px-3 py-1 bg-white/5 rounded-lg border border-white/10 font-mono shadow-[0_0_15px_rgba(34,197,94,0.1)]">${g.score}</div>
                        <span class="text-[11px] font-bold text-center text-white truncate w-1/3">${g.away}</span>
                    </div>
                    <div class="flex flex-wrap justify-center mb-1 gap-1">${tipsHtml}</div>
                    ${dapmBar}
                    ${extras}
                </div>`; 
            }
        });
        return html;
    }
    setInterval(() => loadData(currentDateOffset, true), 30000); // Auto-refresh a cada 30s
    window.onload = () => { loadData(0); };
    </script>
    
    <div class="flex items-center gap-2 bg-black/20 p-2 rounded-lg border border-white/5 w-fit mb-6 mx-auto">
        <button onclick="loadData(currentDateOffset - 1)" class="px-3 py-1 rounded hover:bg-white/10 text-gray-400 font-bold transition"><i class="fas fa-chevron-left"></i></button>
        <span id="date-display" class="px-4 py-1 bg-green-500/20 text-green-300 rounded text-xs font-bold border border-green-500/30 w-24 text-center font-mono">HOJE</span>
        <button onclick="loadData(currentDateOffset + 1)" class="px-3 py-1 rounded hover:bg-white/10 text-gray-400 font-bold transition"><i class="fas fa-chevron-right"></i></button>
    </div>

    <div class="mb-8">
        <div class="section-title text-green-400 mb-4 font-bold font-mono tracking-wider text-xl border-b border-white/10 pb-2"><i class="fas fa-satellite"></i> RADAR SOKKERPRO IN-PLAY</div>
        <div id="grid-pending" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6"></div>
    </div>
    """
    return render_page(DASHBOARD_HTML)

@app.route('/api/get_data')
@login_required
def api_get_data():
    offset = int(request.args.get('offset', 0))
    target_date = (datetime.datetime.now(BR_TZ) + datetime.timedelta(days=offset)).strftime('%Y-%m-%d')
    u = users_col.find_one({"_id": ObjectId(current_user.id)}) if DB_ONLINE else users_col.find_one({"_id": current_user.id})
    watchlist = u.get('watchlist', []) if u else []
    return jsonify(engine.get_json_data(target_date, current_user.role, current_user.plan, watchlist) if engine else [])

@app.route('/api/toggle_watch/<mid>')
@login_required
def api_toggle_watch(mid):
    uid = ObjectId(current_user.id) if DB_ONLINE else current_user.id
    if users_col.find_one({"_id": uid, "watchlist": mid}):
        users_col.update_one({"_id": uid}, {'$pull': {'watchlist': mid}}); return jsonify({'status': 'removed'})
    users_col.update_one({"_id": uid}, {'$addToSet': {'watchlist': mid}}); return jsonify({'status': 'added'})

# --- ADMIN PANEL ---
@app.route('/admin')
@login_required
def route_admin():
    if current_user.role != 'admin': return redirect('/')
    codes = list(codes_col.find().sort('_id', -1).limit(10))
    rows = ''.join([f"<tr class='border-b border-white/5'><td class='p-3 text-yellow-300 font-mono'>{c.get('code')}</td><td class='p-3 text-center'>{'USADO' if c.get('is_used') else 'LIVRE'}</td></tr>" for c in codes])
    return render_page(f"""
    <div class="mb-8"><h1 class="text-3xl font-bold text-white mb-6">PAINEL SOKKERPRO ADMIN</h1>
    <form action="/admin/gencode" method="POST" class="glass p-6 mb-8 rounded border border-green-500/30 flex gap-4">
        <input type="number" name="days" value="30" class="p-3 rounded bg-black/40 text-white w-full">
        <button class="bg-green-600 px-6 font-bold rounded text-white shadow-lg">GERAR CHAVE</button>
    </form>
    <div class="glass p-6 rounded"><table class="w-full text-sm text-gray-300"><tbody>{rows}</tbody></table></div></div>""")

@app.route('/admin/gencode', methods=['POST'])
@login_required
def route_admin_gencode():
    if current_user.role != 'admin': return redirect('/')
    code = f"{''.join(secrets.choice(string.ascii_uppercase) for _ in range(4))}-{''.join(secrets.choice(string.digits) for _ in range(4))}"
    codes_col.insert_one({'code': code, 'days': int(request.form.get('days')), 'is_used': False})
    return redirect(url_for('route_admin'))

@app.route('/logout')
def route_logout(): logout_user(); return redirect(url_for('route_login'))

if __name__ == '__main__':
    print("🚀 SERVIDOR SOKKERPRO INICIADO NA PORTA", PORTA_SERVIDOR)
    if engine: threading.Thread(target=engine.engine_daemon, daemon=True).start()
    app.run(host='0.0.0.0', port=PORTA_SERVIDOR, debug=True, use_reloader=False)
