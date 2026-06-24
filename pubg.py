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
    "timeout": 15,
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
    "tencentgames.com",
    "levelinfinite.com",
    "krafton.com"
]

# ==================== USER-AGENT ====================
USER_AGENTS = [
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36"
]

def get_user_agent():
    return random.choice(USER_AGENTS)

def check_email(email):
    """Email kontrol et - HIZLI"""
    try:
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
            "hl": "en"
        }
        
        response = requests.post(url, data=data, headers=headers, timeout=10, allow_redirects=False)
        text = response.text.lower()
        
        if "password" in text or "şifre" in text:
            return True, "Hesap mevcut"
        elif "couldn't find" in text or "bulunamadı" in text:
            return False, "Hesap yok"
        else:
            return True, "Hesap mevcut"
            
    except:
        return False, "Hata"

def check_single(email):
    """Tek email kontrol et"""
    global stats
    
    stats["total_checked"] += 1
    
    # Format kontrol
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        stats["invalid_accounts"] += 1
        return {"status": "invalid", "email": email, "reason": "Geçersiz format"}
    
    # Email kontrol
    valid, msg = check_email(email)
    
    if valid:
        stats["valid_accounts"] += 1
        # Geçerli mailleri listeye ekle
        stats["valid_emails"].append({"email": email, "password": "BULUNAMADI"})
        return {"status": "valid", "email": email, "message": msg}
    else:
        stats["invalid_accounts"] += 1
        return {"status": "invalid", "email": email, "reason": msg}

def check_bulk(emails):
    """Toplu kontrol - HIZLI"""
    results = []
    
    with ThreadPoolExecutor(max_workers=CONFIG["max_workers"]) as executor:
        futures = [executor.submit(check_single, email) for email in emails]
        for future in futures:
            try:
                result = future.result(timeout=15)
                results.append(result)
                stats["results"].append(result)
            except:
                results.append({"status": "error", "email": "unknown"})
    
    stats["last_check"] = datetime.now().isoformat()
    return results

def check_file(content):
    """Dosya kontrol et"""
    emails = []
    for line in content.strip().split('\n'):
        email = line.strip()
        if email and '@' in email:
            emails.append(email)
    
    if not emails:
        return {"error": "Email bulunamadı"}
    
    results = check_bulk(emails)
    return {"results": results, "total": len(results)}

# ==================== HTML ====================

HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎯 PUBG Email Checker</title>
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
            flex-wrap: wrap;
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
        .btn-secondary:hover { background: #444; }
        
        .btn-group {
            display: flex;
            gap: 10px;
            margin-top: 15px;
            flex-wrap: wrap;
        }
        .btn-group .btn { flex: 1; min-width: 120px; }
        
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
        .result .pass { color: #ffd700; font-family: monospace; font-size: 12px; }
        .result .msg { color: #888; font-size: 12px; }
        
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
        
        .copy-btn {
            background: #333;
            color: #fff;
            border: none;
            padding: 5px 15px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            transition: 0.3s;
        }
        .copy-btn:hover { background: #ffd700; color: #000; }
        
        @media (max-width: 600px) {
            .header h1 { font-size: 32px; }
            .stats { grid-template-columns: 1fr 1fr; }
            .btn-group .btn { flex: 1 1 100%; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 PUBG Email Checker</h1>
            <p>Sadece email girerek kontrol et • <span>PUBG Mobile</span> tespiti</p>
            <small>🤖 Google API • Hızlı • Güvenilir • Şifre gerekmez</small>
        </div>
        
        <div class="stats">
            <div class="stat gold"><div class="num">{{ stats.total_checked }}</div><div class="label">📊 Toplam</div></div>
            <div class="stat green"><div class="num">{{ stats.valid_accounts }}</div><div class="label">✅ Geçerli</div></div>
            <div class="stat red"><div class="num">{{ stats.invalid_accounts }}</div><div class="label">❌ Geçersiz</div></div>
            <div class="stat blue"><div class="num">{{ stats.valid_emails|length }}</div><div class="label">📋 Geçerli Mail</div></div>
        </div>
        
        <div class="section">
            <h2>🚀 Email Kontrol</h2>
            
            <div class="tabs">
                <button class="tab active" onclick="switchTab('single')">📝 Tek Email</button>
                <button class="tab" onclick="switchTab('bulk')">📂 Toplu Kontrol</button>
                <button class="tab" onclick="switchTab('file')">📄 Dosya Yükle</button>
            </div>
            
            <div id="single" class="content active">
                <div class="form-group">
                    <label>📧 Gmail Adresi</label>
                    <input type="email" id="email" placeholder="ornek@gmail.com">
                </div>
                <button class="btn btn-primary" onclick="checkSingle()">🔍 Kontrol Et</button>
            </div>
            
            <div id="bulk" class="content">
                <div class="form-group">
                    <label>📝 Email Listesi (Her satırda bir email)</label>
                    <textarea id="emails" placeholder="ornek1@gmail.com&#10;ornek2@gmail.com&#10;ornek3@gmail.com"></textarea>
                </div>
                <button class="btn btn-success" onclick="checkBulk()">🔍 Hepsini Kontrol Et</button>
            </div>
            
            <div id="file" class="content">
                <div class="form-group">
                    <label>📄 Email Listesi Dosyası (.txt)</label>
                    <input type="file" id="fileInput" accept=".txt" style="padding:10px;background:#0a0a0a;border:1px solid #333;border-radius:8px;width:100%;">
                </div>
                <button class="btn btn-primary" onclick="checkFile()">📤 Yükle ve Kontrol Et</button>
            </div>
        </div>
        
        <!-- GEÇERLİ MAİLLER -->
        {% if stats.valid_emails %}
        <div class="section">
            <h2>
                📋 Geçerli Mailler
                <span class="badge">{{ stats.valid_emails|length }} email</span>
            </h2>
            
            <div class="btn-group">
                <button class="btn btn-success" onclick="toggleEmails()">📧 Mailleri Göster/Gizle</button>
                <button class="btn btn-primary" onclick="exportEmails()">📥 Mailleri İndir</button>
                <button class="btn btn-secondary" onclick="copyEmails()">📋 Kopyala</button>
                <button class="btn btn-danger" onclick="clearResults()">🗑️ Temizle</button>
            </div>
            
            <div id="emailList" style="display:none; margin-top:15px;">
                <div class="results-box">
                    {% for item in stats.valid_emails %}
                    <div class="result">
                        <span>
                            <span class="email">{{ item.email }}</span>
                            <span style="color:#555; margin:0 8px;">|</span>
                            <span class="pass">{{ item.password }}</span>
                        </span>
                        <span>
                            <span class="badge valid">✅ Geçerli</span>
                            <button class="copy-btn" onclick="copyEmail('{{ item.email }}')">📋</button>
                        </span>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
        {% endif %}
        
        <!-- TÜM SONUÇLAR -->
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
                        <span class="msg">{{ r.get('message', '') }}{{ r.get('reason', '') }}</span>
                    </span>
                    <span>
                        {% if r.get('status') == 'valid' %}
                            <span class="badge valid">✅ Geçerli</span>
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
            <p style="font-size:12px;color:#444;">v10.0 • Sadece Email Checker • Şifre Gerekmez</p>
        </div>
    </div>
    
    <script>
        let emailsVisible = false;
        
        function switchTab(tab) {
            document.querySelectorAll('.content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
            document.getElementById(tab).classList.add('active');
            event.target.classList.add('active');
        }
        
        function toggleEmails() {
            const list = document.getElementById('emailList');
            emailsVisible = !emailsVisible;
            list.style.display = emailsVisible ? 'block' : 'none';
        }
        
        function copyEmail(email) {
            navigator.clipboard.writeText(email).then(() => {
                alert('📧 ' + email + ' kopyalandı!');
            }).catch(() => {
                // Fallback
                const input = document.createElement('input');
                input.value = email;
                document.body.appendChild(input);
                input.select();
                document.execCommand('copy');
                document.body.removeChild(input);
                alert('📧 ' + email + ' kopyalandı!');
            });
        }
        
        async function copyEmails() {
            const emails = [];
            document.querySelectorAll('#emailList .email').forEach(el => {
                emails.push(el.textContent);
            });
            if (!emails.length) {
                alert('Kopyalanacak email yok!');
                return;
            }
            const text = emails.join('\\n');
            try {
                await navigator.clipboard.writeText(text);
                alert('📋 ' + emails.length + ' email kopyalandı!');
            } catch {
                const input = document.createElement('textarea');
                input.value = text;
                document.body.appendChild(input);
                input.select();
                document.execCommand('copy');
                document.body.removeChild(input);
                alert('📋 ' + emails.length + ' email kopyalandı!');
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
            if (!email) {
                alert('Email girin!');
                return;
            }
            
            const btn = event.target;
            btn.textContent = '⏳ Kontrol ediliyor...';
            btn.disabled = true;
            
            try {
                const res = await fetch('/api/check', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email })
                });
                const data = await res.json();
                if (data.success) {
                    const result = data.result;
                    let msg = '📧 ' + email + '\\n';
                    msg += result.status === 'valid' ? '✅ GEÇERLİ' : '❌ GEÇERSİZ';
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
            const text = document.getElementById('emails').value.trim();
            if (!text) {
                alert('Email listesi girin!');
                return;
            }
            
            const emails = text.split('\\n').map(l => l.trim()).filter(l => l && '@' in l);
            if (!emails.length) {
                alert('Email bulunamadı!');
                return;
            }
            
            const btn = event.target;
            btn.textContent = '⏳ ' + emails.length + ' email kontrol ediliyor...';
            btn.disabled = true;
            
            try {
                const res = await fetch('/api/check-bulk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ emails })
                });
                const data = await res.json();
                if (data.success) {
                    alert('✅ ' + emails.length + ' email kontrol edildi!\\n' +
                          '✅ Geçerli: ' + data.valid_count + '\\n' +
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
                              '✅ Geçerli: ' + data.valid_count);
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
            "valid_emails": len(stats["valid_emails"])
        }
    })

@app.route('/api/check', methods=['POST'])
def api_check():
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        
        if not email:
            return jsonify({"error": "email required"}), 400
        
        result = check_single(email)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/check-bulk', methods=['POST'])
def api_bulk():
    try:
        data = request.get_json()
        emails = data.get('emails', [])
        
        if not emails:
            return jsonify({"error": "emails required"}), 400
        
        if len(emails) > 100:
            return jsonify({"error": "Max 100 emails"}), 400
        
        results = check_bulk(emails)
        valid = sum(1 for r in results if r.get('status') == 'valid')
        
        return jsonify({
            "success": True,
            "total": len(results),
            "valid_count": valid,
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
        
        result = check_file(content)
        if "error" in result:
            return jsonify({"error": result["error"]}), 400
        
        valid = sum(1 for r in result["results"] if r.get('status') == 'valid')
        
        return jsonify({
            "success": True,
            "total": result["total"],
            "valid_count": valid,
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
    print("🎯 PUBG Email Checker API Başlatıldı")
    print("=" * 60)
    print(f"📡 Port: {port}")
    print(f"⚡ Max Workers: {CONFIG['max_workers']}")
    print("📧 Sadece Email Kontrolü: Aktif")
    print("📞✈️ Telegram: @rinexdestek")
    print("=" * 60)
    
    app.run(host="0.0.0.0", port=port, debug=False)
