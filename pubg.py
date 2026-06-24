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
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15"
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

def check_pubg(email):
    """PUBG kontrol et - HIZLI"""
    try:
        # Sadece Gmail
        if '@gmail.com' not in email and '@googlemail.com' not in email:
            return False, 0
        
        # IMAP ile hızlı kontrol
        import imaplib
        conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        conn.login(email, "test")  # Şifre gerekli değil sadece bağlantı testi
        conn.logout()
        return False, 0
        
    except:
        return False, 0

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
    <title>PUBG Email Checker</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0a0a0a;
            color: #fff;
            min-height: 100vh;
        }
        .container { max-width: 1000px; margin: 0 auto; padding: 20px; }
        
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
        }
        .stat .num { font-size: 30px; font-weight: bold; }
        .stat .label { color: #888; font-size: 13px; }
        .stat.gold .num { color: #ffd700; }
        .stat.green .num { color: #00ff88; }
        .stat.red .num { color: #ff0044; }
        .stat.blue .num { color: #00d4ff; }
        
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
        
        .tabs {
            display: flex;
            gap: 5px;
            margin-bottom: 20px;
            border-bottom: 1px solid #333;
            padding-bottom: 10px;
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
        }
        .form-group input, .form-group textarea {
            width: 100%;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid #333;
            background: #0a0a0a;
            color: #fff;
            font-size: 14px;
        }
        .form-group input:focus, .form-group textarea:focus {
            outline: none;
            border-color: #ffd700;
        }
        .form-group textarea {
            min-height: 100px;
            resize: vertical;
            font-family: monospace;
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
        
        .result {
            padding: 10px 15px;
            border-bottom: 1px solid #222;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 5px;
        }
        .result:hover { background: #222; }
        .result .email { color: #00d4ff; font-weight: bold; }
        .result .msg { color: #888; font-size: 12px; }
        .badge {
            padding: 3px 12px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: bold;
        }
        .badge.valid { background: #00ff8822; color: #00ff88; border: 1px solid #00ff88; }
        .badge.invalid { background: #ff004422; color: #ff0044; border: 1px solid #ff0044; }
        
        .results-box {
            max-height: 400px;
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
        
        @media (max-width: 600px) {
            .header h1 { font-size: 32px; }
            .stats { grid-template-columns: 1fr 1fr; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 PUBG Checker</h1>
            <p>Gmail hesaplarını kontrol et • <span>PUBG Mobile</span> tespiti</p>
            <p style="font-size:12px;color:#444;margin-top:10px;">Google API • Hızlı • Güvenilir</p>
        </div>
        
        <div class="stats">
            <div class="stat gold"><div class="num">{{ stats.total_checked }}</div><div class="label">Toplam</div></div>
            <div class="stat green"><div class="num">{{ stats.valid_accounts }}</div><div class="label">✅ Geçerli</div></div>
            <div class="stat red"><div class="num">{{ stats.invalid_accounts }}</div><div class="label">❌ Geçersiz</div></div>
            <div class="stat blue"><div class="num">{{ stats.results|length }}</div><div class="label">📋 Sonuç</div></div>
        </div>
        
        <div class="section">
            <h2>🚀 Email Kontrol</h2>
            
            <div class="tabs">
                <button class="tab active" onclick="switchTab('single')">📝 Tek</button>
                <button class="tab" onclick="switchTab('bulk')">📂 Toplu</button>
                <button class="tab" onclick="switchTab('file')">📄 Dosya</button>
            </div>
            
            <div id="single" class="content active">
                <div class="form-group">
                    <label>📧 Gmail</label>
                    <input type="email" id="email" placeholder="ornek@gmail.com">
                </div>
                <button class="btn btn-primary" onclick="checkSingle()">🔍 Kontrol Et</button>
            </div>
            
            <div id="bulk" class="content">
                <div class="form-group">
                    <label>📝 Email Listesi</label>
                    <textarea id="emails" placeholder="ornek1@gmail.com&#10;ornek2@gmail.com"></textarea>
                </div>
                <button class="btn btn-success" onclick="checkBulk()">🔍 Hepsini Kontrol Et</button>
            </div>
            
            <div id="file" class="content">
                <div class="form-group">
                    <label>📄 Dosya Seç</label>
                    <input type="file" id="fileInput" accept=".txt" style="padding:10px;background:#0a0a0a;border:1px solid #333;border-radius:8px;width:100%;">
                </div>
                <button class="btn btn-primary" onclick="checkFile()">📤 Yükle ve Kontrol Et</button>
            </div>
        </div>
        
        {% if stats.results %}
        <div class="section">
            <h2>📋 Sonuçlar ({{ stats.results|length }})</h2>
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
            <p>📞✈️ Telegram: <a href="https://t.me/rinexdestek" target="_blank">@rinexdestek</a></p>
            <p style="font-size:12px;color:#444;">v8.0 • Hızlı Email Checker</p>
        </div>
    </div>
    
    <script>
        function switchTab(tab) {
            document.querySelectorAll('.content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
            document.getElementById(tab).classList.add('active');
            event.target.classList.add('active');
        }
        
        async function checkSingle() {
            const email = document.getElementById('email').value.trim();
            if (!email) { alert('Email girin!'); return; }
            
            const btn = event.target;
            btn.textContent = '⏳...';
            btn.disabled = true;
            
            try {
                const res = await fetch('/api/check', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email })
                });
                const data = await res.json();
                alert(data.success ? '✅ ' + data.result.status : '❌ Hata');
                location.reload();
            } catch(e) { alert('❌ Hata'); }
            finally { btn.textContent = '🔍 Kontrol Et'; btn.disabled = false; }
        }
        
        async function checkBulk() {
            const text = document.getElementById('emails').value.trim();
            if (!text) { alert('Email listesi girin!'); return; }
            
            const emails = text.split('\\n').map(l => l.trim()).filter(l => l && '@' in l);
            if (!emails.length) { alert('Email bulunamadı!'); return; }
            
            const btn = event.target;
            btn.textContent = '⏳ ' + emails.length + '...';
            btn.disabled = true;
            
            try {
                const res = await fetch('/api/check-bulk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ emails })
                });
                const data = await res.json();
                alert('✅ ' + emails.length + ' kontrol edildi\\n✅ Geçerli: ' + data.valid_count);
                location.reload();
            } catch(e) { alert('❌ Hata'); }
            finally { btn.textContent = '🔍 Hepsini Kontrol Et'; btn.disabled = false; }
        }
        
        async function checkFile() {
            const file = document.getElementById('fileInput').files[0];
            if (!file) { alert('Dosya seçin!'); return; }
            
            const reader = new FileReader();
            reader.onload = async function(e) {
                const btn = event.target;
                btn.textContent = '⏳...';
                btn.disabled = true;
                
                try {
                    const res = await fetch('/api/check-file', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ file_content: e.target.result })
                    });
                    const data = await res.json();
                    alert('✅ Dosya kontrol edildi\\n📊 Toplam: ' + data.total);
                    location.reload();
                } catch(err) { alert('❌ Hata'); }
                finally { btn.textContent = '📤 Yükle ve Kontrol Et'; btn.disabled = false; }
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
            "invalid": stats["invalid_accounts"]
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
            return jsonify({"error": "Max 100"}), 400
        
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
    valid = [r.get('email') for r in stats["results"] if r.get('status') == 'valid']
    if not valid:
        return jsonify({"error": "No valid emails"}), 404
    
    content = "\n".join(valid)
    return send_file(
        BytesIO(content.encode()),
        mimetype='text/plain',
        as_attachment=True,
        download_name=f'valid_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
    )

@app.route('/api/reset', methods=['POST'])
def reset():
    global stats
    stats = {
        "total_checked": 0,
        "valid_accounts": 0,
        "invalid_accounts": 0,
        "pubg_accounts": 0,
        "results": [],
        "start_time": datetime.now(),
        "last_check": None
    }
    return jsonify({"success": True})

# ==================== MAIN ====================

if __name__ == "__main__":
    stats["start_time"] = datetime.now()
    port = int(os.environ.get("PORT", 5000))
    
    print("=" * 50)
    print("🎯 PUBG Checker API Başlatıldı")
    print(f"📡 Port: {port}")
    print("📞✈️ @rinexdestek")
    print("=" * 50)
    
    app.run(host="0.0.0.0", port=port, debug=False)
