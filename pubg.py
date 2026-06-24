import os
import re
import json
import time
import random
import requests
from flask import Flask, request, jsonify, render_template_string, send_file
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import BytesIO

app = Flask(__name__)

# ==================== KONFIGURASYON ====================
CONFIG = {
    "max_workers": 30,
    "timeout": 20,
    "retry_count": 3
}

# ==================== İSTATİSTİKLER ====================
stats = {
    "total_checked": 0,
    "valid_accounts": 0,
    "invalid_accounts": 0,
    "results": [],
    "start_time": None,
    "last_check": None
}

# ==================== EN GÜÇLÜ USER-AGENT LİSTESİ ====================
USER_AGENTS = [
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
    "Mozilla/5.0 (compatible; DuckDuckBot/1.0; +http://duckduckgo.com/duckduckbot.html)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"
]

# ==================== FONKSİYONLAR ====================

def get_random_user_agent():
    return random.choice(USER_AGENTS)

def check_email_exists(email):
    """Email'in var olup olmadığını kontrol eder - SADECE MAIL"""
    try:
        # Google hesap kontrolü
        url = "https://accounts.google.com/_/signin/sl/lookup"
        
        headers = {
            "User-Agent": get_random_user_agent(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Origin": "https://accounts.google.com",
            "Referer": "https://accounts.google.com/",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache"
        }
        
        data = {
            "Email": email,
            "continue": "https://accounts.google.com/",
            "hl": "en"
        }
        
        response = requests.post(
            url,
            data=data,
            headers=headers,
            timeout=CONFIG["timeout"],
            allow_redirects=False
        )
        
        # Hesap var mı kontrol et
        response_text = response.text.lower()
        
        if "password" in response_text or "şifre" in response_text:
            return True, "Hesap mevcut (şifre gerekiyor)"
        elif "couldn't find" in response_text or "bulunamadı" in response_text:
            return False, "Hesap bulunamadı"
        elif "too many" in response_text or "çok fazla" in response_text:
            return True, "Çok fazla deneme (hesap muhtemelen var)"
        elif response.status_code in [200, 302, 303]:
            if "signin" in response_text or "giriş" in response_text:
                return True, "Hesap mevcut"
            else:
                return True, "Hesap mevcut (doğrulama gerekiyor)"
        else:
            return False, f"Bilinmeyen durum: {response.status_code}"
            
    except requests.exceptions.Timeout:
        return False, "Zaman aşımı"
    except requests.exceptions.ConnectionError:
        return False, "Bağlantı hatası"
    except Exception as e:
        return False, f"Hata: {str(e)}"

def check_single_email(email):
    """Tek bir email kontrol eder"""
    global stats
    
    stats["total_checked"] += 1
    
    # Email formatı kontrol
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        stats["invalid_accounts"] += 1
        return {
            "status": "invalid",
            "email": email,
            "reason": "Geçersiz email formatı"
        }
    
    # Sadece Gmail kontrolü
    if not email.endswith('@gmail.com') and not email.endswith('@googlemail.com'):
        stats["invalid_accounts"] += 1
        return {
            "status": "invalid",
            "email": email,
            "reason": "Sadece Gmail hesapları desteklenir"
        }
    
    # Email varlığını kontrol et
    exists, message = check_email_exists(email)
    
    if exists:
        stats["valid_accounts"] += 1
        return {
            "status": "valid",
            "email": email,
            "message": message
        }
    else:
        stats["invalid_accounts"] += 1
        return {
            "status": "invalid",
            "email": email,
            "reason": message
        }

def check_emails_from_list(email_list):
    """Email listesini kontrol eder"""
    results = []
    
    with ThreadPoolExecutor(max_workers=CONFIG["max_workers"]) as executor:
        futures = [executor.submit(check_single_email, email) for email in email_list]
        
        for future in futures:
            try:
                result = future.result(timeout=CONFIG["timeout"] + 5)
                results.append(result)
                stats["results"].append(result)
            except Exception as e:
                results.append({"error": str(e)})
    
    stats["last_check"] = datetime.now().isoformat()
    return results

def check_emails_from_file(file_content):
    """Dosya içeriğinden email listesini kontrol eder"""
    emails = []
    
    lines = file_content.strip().split('\n')
    for line in lines:
        email = line.strip()
        if email and '@' in email:
            emails.append(email)
    
    if not emails:
        return {"error": "Geçerli email bulunamadı"}
    
    results = check_emails_from_list(emails)
    return {"results": results, "total": len(results)}

def generate_html_page():
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📧 Gmail Checker</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0a0a0a;
            color: #fff;
            min-height: 100vh;
            background-image: radial-gradient(circle at 10% 20%, rgba(0, 200, 255, 0.03) 0%, transparent 50%);
        }
        .container { max-width: 1000px; margin: 0 auto; padding: 20px; }
        
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
            background: conic-gradient(from 0deg, transparent, rgba(0, 200, 255, 0.05), transparent);
            animation: rotate 20s linear infinite;
        }
        @keyframes rotate {
            100% { transform: rotate(360deg); }
        }
        .header h1 {
            font-size: 48px;
            background: linear-gradient(135deg, #00d4ff, #0088ff);
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
        .header .subtitle span { color: #00d4ff; }
        
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
            border-color: #00d4ff;
        }
        .stat-box .number {
            font-size: 32px;
            font-weight: bold;
            margin-bottom: 5px;
        }
        .stat-box .label { color: #888; font-size: 13px; }
        .stat-box.gold .number { color: #ffd700; }
        .stat-box.green .number { color: #00ff88; }
        .stat-box.blue .number { color: #00d4ff; }
        .stat-box.red .number { color: #ff0044; }
        
        .section {
            background: #1a1a1a;
            border-radius: 12px;
            padding: 25px;
            margin: 20px 0;
            border: 1px solid #333;
        }
        .section h2 {
            color: #00d4ff;
            margin-bottom: 15px;
            font-size: 22px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .section h2 .badge {
            font-size: 12px;
            background: #00d4ff22;
            color: #00d4ff;
            padding: 2px 12px;
            border-radius: 12px;
            border: 1px solid #00d4ff44;
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
            border-color: #00d4ff;
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
            background: linear-gradient(135deg, #00d4ff, #0088ff);
            color: #fff;
        }
        .btn-primary:hover {
            transform: scale(1.03);
            box-shadow: 0 0 25px rgba(0, 200, 255, 0.3);
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
        .result-item .email { color: #00d4ff; font-weight: bold; }
        .result-item .info { color: #888; font-size: 12px; }
        .status-badge {
            padding: 3px 12px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: bold;
        }
        .status-badge.valid { background: #00ff8822; color: #00ff88; border: 1px solid #00ff88; }
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
            background: #00d4ff;
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
            background: #00d4ff22;
            color: #00d4ff;
            border: 1px solid #00d4ff44;
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
            color: #00d4ff;
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
            <h1>📧 Gmail Checker</h1>
            <p class="subtitle">Gmail hesaplarının <span>varlığını</span> kontrol eder</p>
            <p style="font-size: 12px; color: #444; margin-top: 10px;">
                🤖 Googlebot ile doğrulama • Cloudflare koruması geçişi
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
            <div class="stat-box red">
                <div class="number">{{ stats.invalid_accounts }}</div>
                <div class="label">❌ Geçersiz Hesap</div>
            </div>
            <div class="stat-box blue">
                <div class="number">{{ stats.results|length }}</div>
                <div class="label">📋 Sonuçlar</div>
            </div>
        </div>
        
        <div class="section">
            <h2>🚀 Email Kontrol</h2>
            
            <div class="tabs">
                <button class="tab-btn active" onclick="switchTab('single')">📝 Tek Email</button>
                <button class="tab-btn" onclick="switchTab('bulk')">📂 Toplu Kontrol</button>
                <button class="tab-btn" onclick="switchTab('file')">📄 Dosya Yükle</button>
            </div>
            
            <!-- Single Check -->
            <div id="tab-single" class="tab-content active">
                <div class="form-group">
                    <label>📧 Gmail Adresi</label>
                    <input type="email" id="singleEmail" placeholder="ornek@gmail.com">
                </div>
                <button class="btn btn-primary btn-block" onclick="checkSingle()">
                    🔍 Email Kontrol Et
                </button>
            </div>
            
            <!-- Bulk Check -->
            <div id="tab-bulk" class="tab-content">
                <div class="form-group">
                    <label>📝 Email Listesi (Her satırda bir email)</label>
                    <textarea id="bulkEmails" placeholder="ornek1@gmail.com&#10;ornek2@gmail.com&#10;ornek3@gmail.com"></textarea>
                </div>
                <button class="btn btn-success btn-block" onclick="checkBulk()">
                    🔍 Hepsini Kontrol Et
                </button>
            </div>
            
            <!-- File Upload -->
            <div id="tab-file" class="tab-content">
                <div class="form-group">
                    <label>📄 Email Listesi Dosyası (.txt)</label>
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
                <span class="badge">{{ stats.results|length }} email</span>
                <span class="badge" style="background: #00ff8822; color: #00ff88;">
                    ✅ {{ stats.valid_accounts }} geçerli
                </span>
            </h2>
            <div class="results-container">
                {% for result in stats.results[:50] %}
                <div class="result-item">
                    <span>
                        <span class="email">{{ result.get('email', 'N/A') }}</span>
                        {% if result.get('message') %}
                        <span style="color: #888; font-size: 11px; margin-left: 10px;">{{ result.get('message') }}</span>
                        {% endif %}
                        {% if result.get('reason') %}
                        <span style="color: #888; font-size: 11px; margin-left: 10px;">❌ {{ result.get('reason') }}</span>
                        {% endif %}
                    </span>
                    <div>
                        {% if result.get('status') == 'valid' %}
                            <span class="status-badge valid">✅ Geçerli</span>
                        {% else %}
                            <span class="status-badge invalid">❌ Geçersiz</span>
                        {% endif %}
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endif %}
        
        <div class="footer">
            <p>📞✈️ Telegram: <a href="https://t.me/rinexdestek" target="_blank">@rinexdestek</a></p>
            <p style="font-size: 12px; margin-top: 10px;">Gmail Checker v5.0 • Sadece Email Kontrolü</p>
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
            
            if (!email) {
                alert('Lütfen bir email adresi girin!');
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
                    body: JSON.stringify({ email: email })
                });
                const data = await response.json();
                if (data.success) {
                    const result = data.result;
                    const status = result.status === 'valid' ? '✅ GEÇERLİ' : '❌ GEÇERSİZ';
                    const msg = result.message || result.reason || '';
                    alert('📧 ' + email + '\n' + status + '\n' + msg);
                } else {
                    alert('❌ Hata: ' + (data.error || 'Bilinmeyen hata'));
                }
                location.reload();
            } catch (error) {
                alert('❌ Hata: ' + error);
            } finally {
                btn.textContent = '🔍 Email Kontrol Et';
                btn.disabled = false;
            }
        }
        
        async function checkBulk() {
            const text = document.getElementById('bulkEmails').value.trim();
            if (!text) {
                alert('Lütfen email listesini girin!');
                return;
            }
            
            const emails = text.split('\\n')
                .map(line => line.trim())
                .filter(email => email && (email.includes('@gmail.com') || email.includes('@googlemail.com')));
            
            if (emails.length === 0) {
                alert('Geçerli Gmail adresi bulunamadı!');
                return;
            }
            
            const btn = event.target;
            btn.textContent = '⏳ ' + emails.length + ' email kontrol ediliyor...';
            btn.disabled = true;
            
            try {
                const response = await fetch('/api/check-bulk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ emails: emails })
                });
                const data = await response.json();
                if (data.success) {
                    alert('✅ ' + emails.length + ' email kontrol edildi!\\n' +
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
                              '✅ Geçerli: ' + data.valid_count + '\\n' +
                              '❌ Geçersiz: ' + (data.total - data.valid_count));
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
    return render_template_string(generate_html_page(), stats=stats)

@app.route('/api/status')
def status():
    uptime = None
    if stats["start_time"]:
        uptime = str(datetime.now() - stats["start_time"])
    
    return jsonify({
        "status": "online",
        "uptime": uptime,
        "stats": {
            "total_checked": stats["total_checked"],
            "valid_accounts": stats["valid_accounts"],
            "invalid_accounts": stats["invalid_accounts"],
            "last_check": stats["last_check"]
        }
    })

@app.route('/api/check', methods=['POST'])
def check_single():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400
        
        email = data.get('email', '').strip()
        
        if not email:
            return jsonify({"error": "email required"}), 400
        
        result = check_single_email(email)
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
        
        emails = data.get('emails', [])
        if not emails:
            return jsonify({"error": "emails list required"}), 400
        
        if len(emails) > 100:
            return jsonify({"error": "Maximum 100 emails per request"}), 400
        
        results = check_emails_from_list(emails)
        valid_count = sum(1 for r in results if r.get("status") == "valid")
        
        return jsonify({
            "success": True,
            "total": len(results),
            "valid_count": valid_count,
            "results": results
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/check-file', methods=['POST'])
def check_file():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400
        
        file_content = data.get('file_content', '')
        if not file_content:
            return jsonify({"error": "file_content required"}), 400
        
        result = check_emails_from_file(file_content)
        
        if "error" in result:
            return jsonify({"error": result["error"]}), 400
        
        valid_count = sum(1 for r in result["results"] if r.get("status") == "valid")
        
        return jsonify({
            "success": True,
            "total": result["total"],
            "valid_count": valid_count,
            "results": result["results"]
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/export', methods=['GET'])
def export_results():
    try:
        valid_emails = []
        for result in stats["results"]:
            if result.get("status") == "valid":
                email = result.get("email", "")
                if email:
                    valid_emails.append(email)
        
        if not valid_emails:
            return jsonify({"error": "Geçerli email bulunamadı"}), 404
        
        content = "\n".join(valid_emails)
        return send_file(
            BytesIO(content.encode('utf-8')),
            mimetype='text/plain',
            as_attachment=True,
            download_name=f'valid_emails_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/stats/reset', methods=['POST'])
def reset_stats():
    global stats
    stats = {
        "total_checked": 0,
        "valid_accounts": 0,
        "invalid_accounts": 0,
        "results": [],
        "start_time": datetime.now(),
        "last_check": None
    }
    return jsonify({"success": True})

# ==================== MAIN ====================

if __name__ == "__main__":
    stats["start_time"] = datetime.now()
    port = int(os.environ.get("PORT", 5000))
    
    print("=" * 60)
    print("📧 Gmail Checker API Başlatılıyor...")
    print("=" * 60)
    print(f"📡 Port: {port}")
    print(f"⚡ Max Workers: {CONFIG['max_workers']}")
    print(f"⏱️  Timeout: {CONFIG['timeout']}s")
    print("🤖 Googlebot User-Agent: Aktif")
    print("🛡️ Cloudflare Bypass: Aktif")
    print("📞✈️ Telegram: @rinexdestek")
    print("=" * 60)
    
    app.run(host="0.0.0.0", port=port, debug=False)
