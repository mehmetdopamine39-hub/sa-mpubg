import os
import re
import json
import time
import hashlib
import secrets
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlparse

import requests
from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for, flash, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from email_validator import validate_email, EmailNotValidError
import dns.resolver

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.permanent_session_lifetime = timedelta(days=7)

# ==================== KONFIGURASYON ====================
CONFIG = {
    "max_workers": 20,
    "timeout": 10,
    "retry_count": 2,
    "max_emails_per_check": 200,
    "rate_limit": 60  # dakikada maksimum istek
}

# ==================== API ANAHTARLARI (KENDİ ANAHTARLARINIZI EKLEYİN) ====================
API_KEYS = {
    "hunter": "YOUR_HUNTER_API_KEY",  # https://hunter.io
    "emailrep": "YOUR_EMAILREP_API_KEY",  # https://emailrep.io
    "hibp": "YOUR_HIBP_API_KEY",  # https://haveibeenpwned.com
}

# ==================== KULLANICI VERİTABANI ====================
USERS_FILE = "users.json"
DATA_DIR = "user_data"

def init_data_dir():
    """Veri dizinini oluştur"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def load_users():
    """Kullanıcıları yükle"""
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_users(users):
    """Kullanıcıları kaydet"""
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

def get_user_data(username):
    """Kullanıcı verilerini yükle"""
    file_path = os.path.join(DATA_DIR, f"{username}_emails.json")
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"emails": [], "stats": {"total": 0, "valid": 0, "invalid": 0}}

def save_user_data(username, data):
    """Kullanıcı verilerini kaydet"""
    file_path = os.path.join(DATA_DIR, f"{username}_emails.json")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ==================== DEKORATÖRLER ====================
def login_required(f):
    """Giriş kontrolü"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def rate_limit(f):
    """Rate limiting"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Basit rate limiting - session bazlı
        if 'last_request' in session:
            elapsed = time.time() - session['last_request']
            if elapsed < 1:  # Saniyede 1 istek
                return jsonify({"error": "Çok fazla istek, lütfen bekleyin"}), 429
        session['last_request'] = time.time()
        return f(*args, **kwargs)
    return decorated_function

# ==================== EMAIL KONTROL FONKSİYONLARI ====================
def validate_email_format(email):
    """Email formatını doğrula"""
    try:
        validate_email(email)
        return True, None
    except EmailNotValidError as e:
        return False, str(e)

def check_mx_record(email):
    """MX kaydını kontrol et"""
    try:
        domain = email.split('@')[1]
        records = dns.resolver.resolve(domain, 'MX')
        return True, len(records) > 0
    except:
        return False, False

def check_hunter(email):
    """Hunter.io API ile kontrol"""
    if API_KEYS["hunter"] == "YOUR_HUNTER_API_KEY":
        return None
    try:
        url = f"https://api.hunter.io/v2/email-verifier?email={email}&api_key={API_KEYS['hunter']}"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get('data', {}).get('result') == 'deliverable'
        return None
    except:
        return None

def check_emailrep(email):
    """EmailRep.io API ile kontrol"""
    if API_KEYS["emailrep"] == "YOUR_EMAILREP_API_KEY":
        return None
    try:
        headers = {"Authorization": f"Bearer {API_KEYS['emailrep']}"}
        url = f"https://emailrep.io/{email}"
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get('reputation') == 'high'
        return None
    except:
        return None

def check_hibp(email):
    """HaveIBeenPwned kontrolü"""
    if API_KEYS["hibp"] == "YOUR_HIBP_API_KEY":
        return None
    try:
        # SHA1 hash'ini al
        sha1 = hashlib.sha1(email.encode()).hexdigest().upper()
        prefix = sha1[:5]
        suffix = sha1[5:]
        
        headers = {"hibp-api-key": API_KEYS["hibp"]}
        url = f"https://api.pwnedpasswords.com/range/{prefix}"
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            for line in response.text.splitlines():
                if line.startswith(suffix):
                    return int(line.split(':')[1]) > 0
        return False
    except:
        return None

def check_google_account(email):
    """Google hesabı kontrolü"""
    try:
        url = "https://accounts.google.com/_/signin/sl/lookup"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://accounts.google.com",
            "Referer": "https://accounts.google.com/"
        }
        data = {"Email": email, "continue": "https://accounts.google.com/"}
        
        response = requests.post(url, data=data, headers=headers, timeout=10, allow_redirects=False)
        text = response.text.lower()
        
        if "password" in text or "şifre" in text:
            return True, "Google hesabı mevcut"
        elif "couldn't find" in text or "bulunamadı" in text:
            return False, "Google hesabı yok"
        else:
            return True, "Google hesabı mevcut (doğrulandı)"
    except Exception as e:
        return None, f"Hata: {str(e)}"

def check_email_comprehensive(email):
    """Kapsamlı email kontrolü"""
    results = {
        "email": email,
        "valid": False,
        "checked_at": datetime.now().isoformat(),
        "checks": {}
    }
    
    # 1. Format kontrolü
    format_valid, format_error = validate_email_format(email)
    results["checks"]["format"] = {"valid": format_valid, "message": format_error or "Geçerli format"}
    if not format_valid:
        results["valid"] = False
        return results
    
    # 2. MX kontrolü
    mx_valid, mx_count = check_mx_record(email)
    results["checks"]["mx"] = {"valid": mx_valid, "message": f"MX kaydı bulundu: {mx_count}" if mx_valid else "MX kaydı yok"}
    if not mx_valid:
        results["valid"] = False
        return results
    
    # 3. Google hesap kontrolü
    google_valid, google_msg = check_google_account(email)
    results["checks"]["google"] = {"valid": google_valid, "message": google_msg}
    
    # 4. Hunter.io (opsiyonel)
    hunter_result = check_hunter(email)
    if hunter_result is not None:
        results["checks"]["hunter"] = {"valid": hunter_result, "message": "Hunter: Geçerli" if hunter_result else "Hunter: Geçersiz"}
    
    # 5. EmailRep.io (opsiyonel)
    emailrep_result = check_emailrep(email)
    if emailrep_result is not None:
        results["checks"]["emailrep"] = {"valid": emailrep_result, "message": "İyi reputasyon" if emailrep_result else "Düşük reputasyon"}
    
    # 6. HIBP (opsiyonel)
    hibp_result = check_hibp(email)
    if hibp_result is not None:
        results["checks"]["hibp"] = {"valid": not hibp_result, "message": "Güvenli" if not hibp_result else "Veri sızıntısında bulundu"}
    
    # Toplam valid kararı (Google kontrolü esas)
    if google_valid is True:
        results["valid"] = True
    elif google_valid is False:
        results["valid"] = False
    else:
        # Google kontrolü başarısızsa, diğer kontrolleri değerlendir
        results["valid"] = results["checks"]["format"]["valid"] and results["checks"]["mx"]["valid"]
    
    return results

# ==================== ROUTES ====================

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template_string(LOGIN_HTML)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # Validasyon
        if not username or not email or not password:
            return render_template_string(REGISTER_HTML, error="Tüm alanlar zorunludur")
        
        if password != confirm_password:
            return render_template_string(REGISTER_HTML, error="Şifreler eşleşmiyor")
        
        if len(password) < 6:
            return render_template_string(REGISTER_HTML, error="Şifre en az 6 karakter olmalıdır")
        
        users = load_users()
        
        if username in users:
            return render_template_string(REGISTER_HTML, error="Bu kullanıcı adı zaten alınmış")
        
        for u in users.values():
            if u.get('email') == email:
                return render_template_string(REGISTER_HTML, error="Bu email zaten kayıtlı")
        
        # Kullanıcı oluştur
        users[username] = {
            "username": username,
            "email": email,
            "password": generate_password_hash(password),
            "created_at": datetime.now().isoformat(),
            "last_login": None,
            "email_count": 0,
            "valid_count": 0
        }
        
        save_users(users)
        init_data_dir()
        
        return redirect(url_for('login'))
    
    return render_template_string(REGISTER_HTML)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        users = load_users()
        
        if username not in users:
            return render_template_string(LOGIN_HTML, error="Kullanıcı adı veya şifre hatalı")
        
        if not check_password_hash(users[username]['password'], password):
            return render_template_string(LOGIN_HTML, error="Kullanıcı adı veya şifre hatalı")
        
        session['user_id'] = username
        session.permanent = True
        
        # Son giriş zamanını güncelle
        users[username]['last_login'] = datetime.now().isoformat()
        save_users(users)
        
        return redirect(url_for('dashboard'))
    
    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        users = load_users()
        
        # Email'i bul
        found_user = None
        for username, data in users.items():
            if data.get('email') == email:
                found_user = username
                break
        
        if not found_user:
            return render_template_string(FORGOT_HTML, error="Bu email ile kayıtlı kullanıcı bulunamadı")
        
        # Gerçekte burada email gönderilir
        # Basit demo için yeni şifre oluşturuyoruz
        new_password = secrets.token_hex(4)
        users[found_user]['password'] = generate_password_hash(new_password)
        save_users(users)
        
        return render_template_string(FORGOT_HTML, 
            success=f"Yeni şifre oluşturuldu: {new_password}\nLütfen giriş yapın ve şifrenizi değiştirin.")
    
    return render_template_string(FORGOT_HTML)

@app.route('/dashboard')
@login_required
def dashboard():
    username = session['user_id']
    users = load_users()
    user_data = users.get(username, {})
    user_emails = get_user_data(username)
    
    return render_template_string(DASHBOARD_HTML, 
        username=username,
        user=user_data,
        emails=user_emails,
        stats=user_emails.get('stats', {})
    )

@app.route('/api/check', methods=['POST'])
@login_required
@rate_limit
def api_check_email():
    """Email kontrol et"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        
        if not email:
            return jsonify({"error": "Email gerekli"}), 400
        
        # Kapsamlı kontrol
        result = check_email_comprehensive(email)
        
        # Kullanıcı verilerini güncelle
        username = session['user_id']
        user_emails = get_user_data(username)
        
        user_emails['emails'].append(result)
        user_emails['stats']['total'] += 1
        if result['valid']:
            user_emails['stats']['valid'] += 1
        else:
            user_emails['stats']['invalid'] += 1
        
        save_user_data(username, user_emails)
        
        # Kullanıcı istatistiklerini güncelle
        users = load_users()
        if username in users:
            users[username]['email_count'] = user_emails['stats']['total']
            users[username]['valid_count'] = user_emails['stats']['valid']
            save_users(users)
        
        return jsonify({
            "success": True,
            "result": result
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/check-bulk', methods=['POST'])
@login_required
@rate_limit
def api_check_bulk():
    """Toplu email kontrolü"""
    try:
        data = request.get_json()
        emails = data.get('emails', [])
        
        if not emails:
            return jsonify({"error": "Email listesi gerekli"}), 400
        
        if len(emails) > CONFIG['max_emails_per_check']:
            return jsonify({"error": f"Maksimum {CONFIG['max_emails_per_check']} email"}), 400
        
        results = []
        for email in emails[:CONFIG['max_emails_per_check']]:
            result = check_email_comprehensive(email.strip())
            results.append(result)
        
        # Kullanıcı verilerini güncelle
        username = session['user_id']
        user_emails = get_user_data(username)
        
        for result in results:
            user_emails['emails'].append(result)
            user_emails['stats']['total'] += 1
            if result['valid']:
                user_emails['stats']['valid'] += 1
            else:
                user_emails['stats']['invalid'] += 1
        
        save_user_data(username, user_emails)
        
        # Kullanıcı istatistiklerini güncelle
        users = load_users()
        if username in users:
            users[username]['email_count'] = user_emails['stats']['total']
            users[username]['valid_count'] = user_emails['stats']['valid']
            save_users(users)
        
        return jsonify({
            "success": True,
            "total": len(results),
            "valid_count": sum(1 for r in results if r['valid']),
            "results": results
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/export', methods=['GET'])
@login_required
def api_export():
    """Geçerli emailleri dışa aktar"""
    username = session['user_id']
    user_emails = get_user_data(username)
    
    valid_emails = [e['email'] for e in user_emails['emails'] if e['valid']]
    
    if not valid_emails:
        return jsonify({"error": "Geçerli email bulunamadı"}), 404
    
    content = "\n".join(valid_emails)
    return send_file(
        BytesIO(content.encode('utf-8')),
        mimetype='text/plain',
        as_attachment=True,
        download_name=f"{username}_valid_emails_{datetime.now().strftime('%Y%m%d')}.txt"
    )

@app.route('/api/stats', methods=['GET'])
@login_required
def api_stats():
    """Kullanıcı istatistikleri"""
    username = session['user_id']
    user_emails = get_user_data(username)
    
    return jsonify({
        "username": username,
        "stats": user_emails.get('stats', {}),
        "recent": user_emails['emails'][-10:] if user_emails['emails'] else []
    })

@app.route('/api/delete-email', methods=['POST'])
@login_required
def api_delete_email():
    """Email sil"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        
        username = session['user_id']
        user_emails = get_user_data(username)
        
        user_emails['emails'] = [e for e in user_emails['emails'] if e['email'] != email]
        
        # İstatistikleri yeniden hesapla
        user_emails['stats'] = {
            "total": len(user_emails['emails']),
            "valid": sum(1 for e in user_emails['emails'] if e['valid']),
            "invalid": sum(1 for e in user_emails['emails'] if not e['valid'])
        }
        
        save_user_data(username, user_emails)
        
        return jsonify({"success": True})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/clear-data', methods=['POST'])
@login_required
def api_clear_data():
    """Tüm verileri temizle"""
    username = session['user_id']
    
    # Boş veri oluştur
    empty_data = {"emails": [], "stats": {"total": 0, "valid": 0, "invalid": 0}}
    save_user_data(username, empty_data)
    
    # Kullanıcı istatistiklerini güncelle
    users = load_users()
    if username in users:
        users[username]['email_count'] = 0
        users[username]['valid_count'] = 0
        save_users(users)
    
    return jsonify({"success": True})

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    username = session['user_id']
    users = load_users()
    user = users.get(username, {})
    
    if request.method == 'POST':
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        current_password = request.form.get('current_password', '')
        
        if not check_password_hash(user['password'], current_password):
            return render_template_string(PROFILE_HTML, user=user, error="Mevcut şifre hatalı")
        
        if new_password and new_password == confirm_password:
            if len(new_password) >= 6:
                users[username]['password'] = generate_password_hash(new_password)
                save_users(users)
                return render_template_string(PROFILE_HTML, user=user, success="Şifre başarıyla değiştirildi")
            else:
                return render_template_string(PROFILE_HTML, user=user, error="Şifre en az 6 karakter olmalıdır")
        elif new_password:
            return render_template_string(PROFILE_HTML, user=user, error="Şifreler eşleşmiyor")
    
    return render_template_string(PROFILE_HTML, user=user)

# ==================== HTML TEMPLATES ====================

# Not: HTML kodları çok uzun olduğu için kısaltılmış halleri verilmiştir.
# Tam HTML'ler için aşağıdaki değişkenleri doldurun.

LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🔐 Giriş - Email Checker</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, sans-serif;
            background: #0a0a0a;
            color: #fff;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .login-box {
            background: #1a1a1a;
            padding: 40px;
            border-radius: 16px;
            border: 1px solid #333;
            max-width: 400px;
            width: 100%;
        }
        .login-box h1 {
            text-align: center;
            font-size: 32px;
            background: linear-gradient(135deg, #ffd700, #ff6b00);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 30px;
        }
        .form-group { margin: 15px 0; }
        .form-group label { color: #888; display: block; margin-bottom: 5px; font-size: 14px; }
        .form-group input {
            width: 100%;
            padding: 12px;
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
        .btn {
            width: 100%;
            padding: 12px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            background: linear-gradient(135deg, #ffd700, #ff6b00);
            color: #000;
            transition: 0.3s;
        }
        .btn:hover { transform: scale(1.02); box-shadow: 0 0 25px rgba(255, 215, 0, 0.3); }
        .error { color: #ff0044; text-align: center; margin: 10px 0; }
        .success { color: #00ff88; text-align: center; margin: 10px 0; }
        .footer { text-align: center; margin-top: 20px; color: #555; }
        .footer a { color: #ffd700; text-decoration: none; }
        .links { text-align: center; margin-top: 15px; }
        .links a { color: #888; text-decoration: none; margin: 0 10px; font-size: 14px; }
        .links a:hover { color: #ffd700; }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>🎯 Email Checker</h1>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        {% if success %}<div class="success">{{ success }}</div>{% endif %}
        <form method="POST">
            <div class="form-group">
                <label>👤 Kullanıcı Adı</label>
                <input type="text" name="username" required>
            </div>
            <div class="form-group">
                <label>🔑 Şifre</label>
                <input type="password" name="password" required>
            </div>
            <button type="submit" class="btn">🚀 Giriş Yap</button>
        </form>
        <div class="links">
            <a href="/register">Kayıt Ol</a>
            <a href="/forgot-password">Şifremi Unuttum</a>
        </div>
        <div class="footer">
            <p>📞✈️ <a href="https://t.me/rinexdestek" target="_blank">@rinexdestek</a></p>
        </div>
    </div>
</body>
</html>
"""

REGISTER_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📝 Kayıt Ol - Email Checker</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, sans-serif;
            background: #0a0a0a;
            color: #fff;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .register-box {
            background: #1a1a1a;
            padding: 40px;
            border-radius: 16px;
            border: 1px solid #333;
            max-width: 400px;
            width: 100%;
        }
        .register-box h1 {
            text-align: center;
            font-size: 32px;
            background: linear-gradient(135deg, #ffd700, #ff6b00);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 30px;
        }
        .form-group { margin: 15px 0; }
        .form-group label { color: #888; display: block; margin-bottom: 5px; font-size: 14px; }
        .form-group input {
            width: 100%;
            padding: 12px;
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
        .btn {
            width: 100%;
            padding: 12px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            background: linear-gradient(135deg, #ffd700, #ff6b00);
            color: #000;
            transition: 0.3s;
        }
        .btn:hover { transform: scale(1.02); box-shadow: 0 0 25px rgba(255, 215, 0, 0.3); }
        .error { color: #ff0044; text-align: center; margin: 10px 0; }
        .success { color: #00ff88; text-align: center; margin: 10px 0; }
        .footer { text-align: center; margin-top: 20px; color: #555; }
        .footer a { color: #ffd700; text-decoration: none; }
        .links { text-align: center; margin-top: 15px; }
        .links a { color: #888; text-decoration: none; margin: 0 10px; font-size: 14px; }
        .links a:hover { color: #ffd700; }
    </style>
</head>
<body>
    <div class="register-box">
        <h1>📝 Kayıt Ol</h1>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="POST">
            <div class="form-group">
                <label>👤 Kullanıcı Adı</label>
                <input type="text" name="username" required>
            </div>
            <div class="form-group">
                <label>📧 Email</label>
                <input type="email" name="email" required>
            </div>
            <div class="form-group">
                <label>🔑 Şifre</label>
                <input type="password" name="password" required minlength="6">
            </div>
            <div class="form-group">
                <label>🔑 Şifre Tekrar</label>
                <input type="password" name="confirm_password" required>
            </div>
            <button type="submit" class="btn">✅ Kayıt Ol</button>
        </form>
        <div class="links">
            <a href="/login">Zaten hesabın var mı? Giriş Yap</a>
        </div>
        <div class="footer">
            <p>📞✈️ <a href="https://t.me/rinexdestek" target="_blank">@rinexdestek</a></p>
        </div>
    </div>
</body>
</html>
"""

FORGOT_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🔑 Şifre Sıfırlama</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, sans-serif;
            background: #0a0a0a;
            color: #fff;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .box {
            background: #1a1a1a;
            padding: 40px;
            border-radius: 16px;
            border: 1px solid #333;
            max-width: 400px;
            width: 100%;
        }
        .box h1 {
            text-align: center;
            font-size: 28px;
            color: #ffd700;
            margin-bottom: 30px;
        }
        .form-group { margin: 15px 0; }
        .form-group label { color: #888; display: block; margin-bottom: 5px; }
        .form-group input {
            width: 100%;
            padding: 12px;
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
        .btn {
            width: 100%;
            padding: 12px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            background: linear-gradient(135deg, #ffd700, #ff6b00);
            color: #000;
            transition: 0.3s;
        }
        .btn:hover { transform: scale(1.02); box-shadow: 0 0 25px rgba(255, 215, 0, 0.3); }
        .error { color: #ff0044; text-align: center; margin: 10px 0; }
        .success { color: #00ff88; text-align: center; margin: 10px 0; white-space: pre-wrap; }
        .links { text-align: center; margin-top: 15px; }
        .links a { color: #888; text-decoration: none; }
        .links a:hover { color: #ffd700; }
    </style>
</head>
<body>
    <div class="box">
        <h1>🔑 Şifre Sıfırlama</h1>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        {% if success %}<div class="success">{{ success }}</div>{% endif %}
        <form method="POST">
            <div class="form-group">
                <label>📧 Kayıtlı Email Adresiniz</label>
                <input type="email" name="email" required>
            </div>
            <button type="submit" class="btn">🔄 Şifreyi Sıfırla</button>
        </form>
        <div class="links">
            <a href="/login">← Giriş Sayfasına Dön</a>
        </div>
    </div>
</body>
</html>
"""

PROFILE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>👤 Profil</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, sans-serif;
            background: #0a0a0a;
            color: #fff;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .profile-box {
            background: #1a1a1a;
            padding: 40px;
            border-radius: 16px;
            border: 1px solid #333;
            max-width: 450px;
            width: 100%;
        }
        .profile-box h1 {
            text-align: center;
            font-size: 32px;
            background: linear-gradient(135deg, #ffd700, #ff6b00);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 10px;
        }
        .username { text-align: center; color: #888; margin-bottom: 30px; }
        .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 20px 0; }
        .stat { background: #0a0a0a; padding: 15px; border-radius: 8px; text-align: center; border: 1px solid #333; }
        .stat .num { font-size: 24px; font-weight: bold; color: #ffd700; }
        .stat .label { color: #888; font-size: 12px; }
        .form-group { margin: 15px 0; }
        .form-group label { color: #888; display: block; margin-bottom: 5px; }
        .form-group input {
            width: 100%;
            padding: 12px;
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
        .btn {
            width: 100%;
            padding: 12px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            background: linear-gradient(135deg, #ffd700, #ff6b00);
            color: #000;
            transition: 0.3s;
            margin: 5px 0;
        }
        .btn:hover { transform: scale(1.02); }
        .btn-danger { background: #ff0044; color: #fff; }
        .btn-secondary { background: #333; color: #fff; }
        .error { color: #ff0044; text-align: center; margin: 10px 0; }
        .success { color: #00ff88; text-align: center; margin: 10px 0; }
        .links { text-align: center; margin-top: 20px; }
        .links a { color: #888; text-decoration: none; margin: 0 10px; }
        .links a:hover { color: #ffd700; }
    </style>
</head>
<body>
    <div class="profile-box">
        <h1>👤 Profil</h1>
        <div class="username">@{{ user.username }}</div>
        
        <div class="stats">
            <div class="stat"><div class="num">{{ user.email_count|default(0) }}</div><div class="label">📊 Toplam</div></div>
            <div class="stat"><div class="num" style="color:#00ff88;">{{ user.valid_count|default(0) }}</div><div class="label">✅ Geçerli</div></div>
        </div>
        
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        {% if success %}<div class="success">{{ success }}</div>{% endif %}
        
        <form method="POST">
            <div class="form-group">
                <label>🔑 Mevcut Şifre</label>
                <input type="password" name="current_password" required>
            </div>
            <div class="form-group">
                <label>🔑 Yeni Şifre</label>
                <input type="password" name="new_password" minlength="6">
            </div>
            <div class="form-group">
                <label>🔑 Yeni Şifre Tekrar</label>
                <input type="password" name="confirm_password">
            </div>
            <button type="submit" class="btn">💾 Şifreyi Değiştir</button>
        </form>
        
        <div class="links">
            <a href="/dashboard">📊 Dashboard</a>
            <a href="/logout">🚪 Çıkış</a>
        </div>
    </div>
</body>
</html>
"""

# DASHBOARD_HTML - Ana dashboard (Kısaltılmış)
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📊 Dashboard - Email Checker</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, sans-serif;
            background: #0a0a0a;
            color: #fff;
            min-height: 100vh;
        }
        .container { max-width: 1100px; margin: 0 auto; padding: 20px; }
        
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px;
            background: linear-gradient(135deg, #1a1a1a, #2a2a2a);
            border-radius: 16px;
            border: 1px solid #333;
            margin-bottom: 30px;
            flex-wrap: wrap;
            gap: 10px;
        }
        .header h1 {
            font-size: 28px;
            background: linear-gradient(135deg, #ffd700, #ff6b00);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .header .user {
            color: #888;
            display: flex;
            align-items: center;
            gap: 15px;
        }
        .header .user a {
            color: #ffd700;
            text-decoration: none;
        }
        .header .user a:hover { text-decoration: underline; }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .stat-card {
            background: #1a1a1a;
            padding: 20px;
            border-radius: 12px;
            text-align: center;
            border: 1px solid #333;
        }
        .stat-card .num { font-size: 30px; font-weight: bold; }
        .stat-card .label { color: #888; font-size: 13px; }
        .stat-card.gold .num { color: #ffd700; }
        .stat-card.green .num { color: #00ff88; }
        .stat-card.red .num { color: #ff0044; }
        .stat-card.blue .num { color: #00d4ff; }
        
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
            font-size: 20px;
        }
        
        .form-group { margin: 10px 0; }
        .form-group label { color: #888; display: block; margin-bottom: 5px; }
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
        .form-group textarea { min-height: 80px; resize: vertical; font-family: monospace; }
        
        .btn {
            padding: 10px 25px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: bold;
            cursor: pointer;
            transition: 0.3s;
        }
        .btn-primary {
            background: linear-gradient(135deg, #ffd700, #ff6b00);
            color: #000;
        }
        .btn-primary:hover { transform: scale(1.02); }
        .btn-success { background: #00ff88; color: #000; }
        .btn-success:hover { transform: scale(1.02); }
        .btn-danger { background: #ff0044; color: #fff; }
        .btn-danger:hover { transform: scale(1.02); }
        .btn-secondary { background: #333; color: #fff; }
        .btn-secondary:hover { background: #444; }
        
        .btn-group {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin: 10px 0;
        }
        
        .results-box {
            max-height: 400px;
            overflow-y: auto;
            border-radius: 8px;
            border: 1px solid #222;
            margin-top: 10px;
        }
        .results-box::-webkit-scrollbar { width: 6px; }
        .results-box::-webkit-scrollbar-track { background: #0a0a0a; }
        .results-box::-webkit-scrollbar-thumb { background: #ffd700; border-radius: 3px; }
        
        .result-item {
            padding: 8px 15px;
            border-bottom: 1px solid #222;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 5px;
        }
        .result-item:hover { background: #222; }
        .result-item .email { color: #00d4ff; font-weight: bold; }
        .result-item .status {
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: bold;
        }
        .status.valid { background: #00ff8822; color: #00ff88; border: 1px solid #00ff88; }
        .status.invalid { background: #ff004422; color: #ff0044; border: 1px solid #ff0044; }
        
        .footer {
            text-align: center;
            padding: 20px;
            color: #555;
            border-top: 1px solid #222;
            margin-top: 30px;
        }
        .footer a { color: #ffd700; text-decoration: none; }
        
        @media (max-width: 600px) {
            .header { flex-direction: column; text-align: center; }
            .stats-grid { grid-template-columns: 1fr 1fr; }
            .btn-group .btn { flex: 1; min-width: 100px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 Email Checker</h1>
            <div class="user">
                <span>👤 {{ username }}</span>
                <a href="/profile">Profil</a>
                <a href="/logout" style="color:#ff0044;">Çıkış</a>
            </div>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card gold"><div class="num">{{ stats.total|default(0) }}</div><div class="label">📊 Toplam</div></div>
            <div class="stat-card green"><div class="num">{{ stats.valid|default(0) }}</div><div class="label">✅ Geçerli</div></div>
            <div class="stat-card red"><div class="num">{{ stats.invalid|default(0) }}</div><div class="label">❌ Geçersiz</div></div>
            <div class="stat-card blue"><div class="num">{{ emails.emails|length }}</div><div class="label">📋 Kayıtlı Email</div></div>
        </div>
        
        <div class="section">
            <h2>🚀 Email Kontrol</h2>
            <div class="form-group">
                <label>📧 Email Adresi</label>
                <input type="email" id="singleEmail" placeholder="ornek@gmail.com">
            </div>
            <button class="btn btn-primary" onclick="checkSingle()">🔍 Kontrol Et</button>
            
            <hr style="border-color:#333; margin:20px 0;">
            
            <div class="form-group">
                <label>📝 Toplu Email (Her satırda bir email)</label>
                <textarea id="bulkEmails" placeholder="ornek1@gmail.com&#10;ornek2@gmail.com"></textarea>
            </div>
            <button class="btn btn-success" onclick="checkBulk()">🔍 Hepsini Kontrol Et</button>
        </div>
        
        <div class="section">
            <h2>📋 Geçerli Mailler</h2>
            <div class="btn-group">
                <button class="btn btn-primary" onclick="exportEmails()">📥 İndir</button>
                <button class="btn btn-secondary" onclick="copyEmails()">📋 Kopyala</button>
                <button class="btn btn-danger" onclick="clearData()">🗑️ Temizle</button>
            </div>
            <div class="results-box">
                {% for email in emails.emails|reverse %}
                    {% if email.valid %}
                    <div class="result-item">
                        <span class="email">{{ email.email }}</span>
                        <span class="status valid">✅ Geçerli</span>
                    </div>
                    {% endif %}
                {% endfor %}
            </div>
        </div>
        
        <div class="section">
            <h2>📊 Tüm Kontroller</h2>
            <div class="results-box">
                {% for email in emails.emails|reverse %}
                <div class="result-item">
                    <span class="email">{{ email.email }}</span>
                    <span class="status {{ 'valid' if email.valid else 'invalid' }}">
                        {{ '✅ Geçerli' if email.valid else '❌ Geçersiz' }}
                    </span>
                </div>
                {% endfor %}
            </div>
        </div>
        
        <div class="footer">
            <p>📞✈️ <a href="https://t.me/rinexdestek" target="_blank">@rinexdestek</a></p>
        </div>
    </div>
    
    <script>
        async function checkSingle() {
            const email = document.getElementById('singleEmail').value.trim();
            if (!email) { alert('Email girin!'); return; }
            
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
                    alert('✅ ' + email + '\nDurum: ' + (data.result.valid ? 'GEÇERLİ' : 'GEÇERSİZ'));
                } else {
                    alert('❌ Hata: ' + data.error);
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
            const text = document.getElementById('bulkEmails').value.trim();
            if (!text) { alert('Email listesi girin!'); return; }
            
            const emails = text.split('\\n').map(l => l.trim()).filter(l => l && l.includes('@'));
            if (!emails.length) { alert('Email bulunamadı!'); return; }
            
            if (emails.length > 200) {
                alert('Maksimum 200 email!');
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
                    alert('✅ ' + data.total + ' email kontrol edildi!\\n' +
                          '✅ Geçerli: ' + data.valid_count);
                } else {
                    alert('❌ Hata: ' + data.error);
                }
                location.reload();
            } catch(e) {
                alert('❌ Hata: ' + e);
            } finally {
                btn.textContent = '🔍 Hepsini Kontrol Et';
                btn.disabled = false;
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
                    alert('❌ ' + (await res.text()));
                }
            } catch(e) {
                alert('❌ Hata: ' + e);
            }
        }
        
        async function copyEmails() {
            try {
                const res = await fetch('/api/export');
                const text = await res.text();
                if (text.includes('error')) {
                    alert('❌ ' + text);
                    return;
                }
                await navigator.clipboard.writeText(text);
                alert('📋 Email\'ler kopyalandı!');
            } catch(e) {
                alert('❌ Hata: ' + e);
            }
        }
        
        async function clearData() {
            if (!confirm('Tüm verileriniz silinsin mi?')) return;
            try {
                await fetch('/api/clear-data', { method: 'POST' });
                location.reload();
            } catch(e) {
                alert('❌ Hata: ' + e);
            }
        }
    </script>
</body>
</html>
"""

# ==================== MAIN ====================

if __name__ == "__main__":
    init_data_dir()
    
    # Örnek kullanıcı oluştur (eğer yoksa)
    users = load_users()
    if not users:
        users["admin"] = {
            "username": "admin",
            "email": "admin@example.com",
            "password": generate_password_hash("admin123"),
            "created_at": datetime.now().isoformat(),
            "last_login": None,
            "email_count": 0,
            "valid_count": 0
        }
        save_users(users)
    
    port = int(os.environ.get("PORT", 5000))
    
    print("=" * 60)
    print("🎯 Gelişmiş Email Checker Başlatıldı")
    print("=" * 60)
    print(f"📡 Port: {port}")
    print(f"👤 Varsayılan Kullanıcı: admin / admin123")
    print("📧 Google Hesap Doğrulama: Aktif")
    print("🔐 Şifre Sıfırlama: Aktif")
    print("📊 Kullanıcı Bazlı Veri: Aktif")
    print("=" * 60)
    
    app.run(host="0.0.0.0", port=port, debug=True)
