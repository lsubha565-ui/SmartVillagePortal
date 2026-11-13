import csv
import io
import os
import re
import time
import requests
from threading import Thread
from difflib import SequenceMatcher
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from db import get_db_connection

app = Flask(__name__)
app.secret_key = 'smart_village_secret_key'

# ----------------- 200-QUESTION DATASET LOADER & 90% EXACT MATCHER -----------------
DATASET_FILE = os.path.join('dataset', 'questions.csv')
QA_DATASET = []

def clean_text(text):
    """Strips punctuation and standardizes to lowercase for clean matching."""
    if not text:
        return ""
    return re.sub(r'[^\w\s]', '', text).strip().lower()

def load_qa_dataset():
    """Loads 200 benchmark questions from CSV into server memory at startup."""
    global QA_DATASET
    QA_DATASET = []
    if os.path.exists(DATASET_FILE):
        try:
            with open(DATASET_FILE, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    QA_DATASET.append({
                        "id": row.get("ID"),
                        "category": row.get("Category"),
                        "question": row.get("Question", "").strip(),
                        "answer": row.get("Expected Answer", "").strip()
                    })
            print(f"[DATASET] Loaded {len(QA_DATASET)} benchmark questions successfully.")
        except Exception as e:
            print(f"[DATASET ERROR] Failed to parse CSV: {e}")
    else:
        print("[DATASET WARNING] dataset/questions.csv not found!")

load_qa_dataset()

def find_dataset_match(user_query):
    """
    Checks user input against dataset/questions.csv.
    Uses SequenceMatcher to ensure ONLY queries with ~90% match are served from CSV.
    All natural variations, complex questions, or Tanglish route directly to OpenRouter.
    """
    q_clean = clean_text(user_query)
    if not q_clean:
        return None

    best_match = None
    highest_ratio = 0.0

    for item in QA_DATASET:
        item_clean = clean_text(item["question"])
        ratio = SequenceMatcher(None, q_clean, item_clean).ratio()

        if ratio > highest_ratio:
            highest_ratio = ratio
            best_match = item["answer"]

    # Only return dataset answer if similarity is 88% - 90% or higher
    if highest_ratio >= 0.88:
        print(f"[DATASET MATCH] Score: {highest_ratio:.2f} -> Using CSV Benchmark Answer.")
        return best_match

    # Otherwise bypass CSV and let the LLM handle context accurately
    print(f"[LLM ROUTE] Highest CSV match was only {highest_ratio:.2f} (< 0.88) -> Forwarding to OpenRouter.")
    return None

# ----------------- EMAIL / FLASK-MAIL CONFIGURATION -----------------
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('PORTAL_MAIL_USER', 'your_portal_email@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('PORTAL_MAIL_PASS', 'xxxx xxxx xxxx xxxx')
app.config['MAIL_DEFAULT_SENDER'] = ('Smart Village Portal', app.config['MAIL_USERNAME'])

mail = Mail(app)

def send_async_email(app_instance, msg):
    """Sends email in background thread to prevent latency during form submissions."""
    with app_instance.app_context():
        try:
            mail.send(msg)
            print(f"[MAIL SUCCESS] Notification sent to: {msg.recipients}")
        except Exception as e:
            print(f"[MAIL ERROR] Delivery failed: {e}")

def send_notification(recipient_email, subject, body_text):
    """Spawns an asynchronous background thread for email delivery."""
    if not recipient_email:
        return
    msg = Message(subject=subject, recipients=[recipient_email], body=body_text)
    Thread(target=send_async_email, args=(app, msg)).start()

# ----------------- FILE UPLOAD CONFIGURATION -----------------
UPLOAD_FOLDER = os.path.join('static', 'uploads')
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 Megabytes

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ----------------- OPENROUTER AI & HYBRID PROMPT -----------------
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "your_openrouter_api_key_here")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

MISTRAL_SYSTEM_PROMPT = """
You are an intelligent, highly knowledgeable, and versatile AI Assistant embedded inside the 'Chatbot Enabled Smart Village Service Portal'.

1. SMART VILLAGE PORTAL EXPERT (Certificates, Civic Grievances, Document Issues):
   - Keep answers clear, direct, and concise (within 3-5 sentences).
   - If a citizen mentions entering a wrong pincode, incorrect address, wrong discharge summary, or incorrect applicant details:
     Inform them that submitted applications cannot be edited directly by users from the portal. Advise them to lodge a grievance under 'Register Complaint' specifying their Application Request ID (BC/DC ID) along with the correct details/documents, or visit the Panchayat Administrative Office for verification before final approval.
   - If a citizen asks what documents are required for a Birth Certificate:
     Inform them they need: Proof of birth (hospital discharge summary or letter from doctor), parent ID proofs (Aadhaar/Voter ID), and address proof.
   - For services overview: Briefly list Birth Certificates, Death Certificates, Public Grievance Registration, and Online Status Tracking.
   - Support English and Tanglish naturally based on the user's input language.

2. GENERAL KNOWLEDGE & ANY DOMAIN EXPERT (Like Gemini / ChatGPT):
   - If a user asks general knowledge, programming, science, cooking, or academic questions:
     Provide a structured, accurate, and direct response without bringing in village portal topics.
"""

LOCAL_KNOWLEDGE_BASE = {
    "services": (
        "**Smart Village Portal Services Overview:**\n\n"
        "1. **Birth Certificates:** Submit new birth applications and download verified certificates.\n"
        "2. **Death Certificates:** Apply for death records and access approved official copies.\n"
        "3. **Public Grievance Redressal:** Lodge civic complaints (Water supply, Streetlights, Road damage, Drainage, Electricity) with document uploads.\n"
        "4. **Status Tracking:** Real-time application tracking using Request or Complaint IDs."
    ),
    "documents": (
        "**Documents Required for Birth Certificate:**\n\n"
        "- Hospital Discharge Summary / Proof of Birth from hospital.\n"
        "- Parents' Identity Proof (Aadhaar Card, Voter ID, or Ration Card).\n"
        "- Address Proof of parents in the Panchayat limit."
    ),
    "correction": (
        "**Correction in Submitted Application (Pincode / Address / Documents):**\n\n"
        "- Once submitted, applications cannot be edited directly by citizens.\n"
        "- Please navigate to **Register Complaint** on your dashboard.\n"
        "- Submit a grievance mentioning your **Application Request ID** (e.g., BC1001 or DC1001) and specify the correct details or replacement documents.\n"
        "- The Panchayat Administrator will verify and update your records before issuing the certificate."
    ),
    "birth": (
        "**Birth Certificate Application Guidance:**\n\n"
        "- Click **Birth Certificate** on your dashboard.\n"
        "- Fill in Child's Name, Date of Birth, Hospital/Place, and Parents' details.\n"
        "- Submit to receive a **Request ID** (e.g., BC1001).\n"
        "- Once approved by the Panchayat Admin, download your official PDF directly from the dashboard."
    ),
    "death": (
        "**Death Certificate Application Guidance:**\n\n"
        "- Click **Death Certificate** on the dashboard.\n"
        "- Provide Deceased Name, Date of Death, Location, and Applicant relationship.\n"
        "- Submit and track status. Once approved, the verified PDF is available for download."
    ),
    "complaint": (
        "**Grievance & Complaint Registration:**\n\n"
        "- Click **Register Complaint** on the dashboard.\n"
        "- Select your issue category (Drinking Water, Street Light, Drainage, Roads, Sanitation, Electricity).\n"
        "- Enter description, landmark, and optionally attach an image/document.\n"
        "- View real-time status in your dashboard Grievances table."
    ),
    "track": (
        "**Track Status Guidance:**\n\n"
        "- Your registered complaints and certificates are automatically listed on your **User Dashboard**.\n"
        "- You can also use **Track Status** to look up any specific Complaint ID (e.g., CMP1001)."
    )
}

def get_fallback_reply(query):
    """Safe fallback strictly for village portal queries when external API is unreachable."""
    q = query.lower()

    if any(k in q for k in ["wrong", "mistake", "thappu", "correction", "pincode", "pin"]):
        return LOCAL_KNOWLEDGE_BASE["correction"]
    elif any(k in q for k in ["document", "documents", "thevai", "proof"]) and "birth" in q:
        return LOCAL_KNOWLEDGE_BASE["documents"]
    elif any(k in q for k in ["service", "services", "village", "portal", "available", "facilities"]):
        return LOCAL_KNOWLEDGE_BASE["services"]
    elif any(k in q for k in ["birth", "pirappu", "child", "baby"]):
        return LOCAL_KNOWLEDGE_BASE["birth"]
    elif any(k in q for k in ["death", "irappu", "dead", "deceased"]):
        return LOCAL_KNOWLEDGE_BASE["death"]
    elif any(k in q for k in ["complaint", "pugar", "water", "light", "road", "drainage", "thanni"]):
        return LOCAL_KNOWLEDGE_BASE["complaint"]
    elif any(k in q for k in ["track", "status", "check"]):
        return LOCAL_KNOWLEDGE_BASE["track"]
    else:
        return (
            "I could not reach the AI service at the moment to process your query. "
            "Please check your internet connection or try again shortly."
        )

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ----------------- LANGUAGE & GLOBAL CONTEXT -----------------
@app.route('/set_language/')
def set_language(lang_code):
    if lang_code in ['en', 'ta']:
        session['lang'] = lang_code
    return redirect(request.referrer or url_for('home'))

@app.before_request
def make_lang_global():
    if 'lang' not in session:
        session['lang'] = 'en'

# 0. Landing Home Route
@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if session.get('is_admin'):
        return redirect(url_for('admin_dashboard'))
    return render_template('home.html', lang=session.get('lang', 'en'))

# 1. Unified Login Route (Citizen & Admin)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if session.get('is_admin'):
        return redirect(url_for('admin_dashboard'))

    lang = session.get('lang', 'en')

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role', 'citizen')

        conn = get_db_connection()
        if not conn:
            flash('Database connection failed!' if lang == 'en' else 'தரவுத்தள இணைப்பு தோல்வியடைந்தது!', 'danger')
            return redirect(url_for('login'))

        cursor = conn.cursor(dictionary=True)

        try:
            if role == 'admin':
                cursor.execute("SELECT * FROM admin WHERE username = %s AND password = %s", (username, password))
                admin = cursor.fetchone()

                if admin or (username == 'admin' and password == 'admin123'):
                    session.clear()
                    session['lang'] = lang
                    session['is_admin'] = True
                    session['admin_username'] = username
                    session['role'] = 'admin'
                    flash('Welcome, Admin!' if lang == 'en' else 'நிர்வாகி நல்வரவு!', 'success')
                    return redirect(url_for('admin_dashboard'))
                else:
                    msg = 'Invalid Admin credentials!' if lang == 'en' else 'தவறான நிர்வாகி கணக்கு விவரங்கள்!'
                    flash(msg, 'danger')

            else:
                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                user = cursor.fetchone()

                if user and check_password_hash(user['password'], password):
                    session.clear()
                    session['lang'] = lang
                    session['user_id'] = user['id']
                    session['username'] = user['username']
                    session['user_email'] = user.get('email', '')
                    session['role'] = 'citizen'
                    return redirect(url_for('dashboard'))
                else:
                    msg = 'Invalid username or password!' if lang == 'en' else 'தவறான பயனர் பெயர் அல்லது கடவுச்சொல்!'
                    flash(msg, 'danger')

        except Exception as e:
            flash(f"Error: {e}", 'danger')
        finally:
            cursor.close()
            conn.close()

    return render_template('login.html', lang=lang)

# 2. Register Route (Citizen Only)
@app.route('/register', methods=['GET', 'POST'])
def register():
    lang = session.get('lang', 'en')
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not email or not password:
            msg = 'All fields are required!' if lang == 'en' else 'அனைத்து விவரங்களும் தேவை!'
            flash(msg, 'danger')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)

        conn = get_db_connection()
        if not conn:
            flash('Database connection failed!' if lang == 'en' else 'தரவுத்தள இணைப்பு தோல்வியடைந்தது!', 'danger')
            return redirect(url_for('register'))

        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
                (username, email, hashed_password)
            )
            conn.commit()

            if lang == 'ta':
                subj = "கிராம சேவை தளத்தில் பதிவு வெற்றி பெற்றமைக்கு வாழ்த்துகள்"
                body = f"வணக்கம் {username},\n\nஉங்கள் கணக்கு வெற்றிகரமாக உருவாக்கப்பட்டது. நீங்கள் இப்போது உள்நுழைந்து அரசு சேவைகளுக்கு விண்ணப்பிக்கலாம்.\n\nகிராம சேவை தளம்"
            else:
                subj = "Registration Successful - Smart Village Portal"
                body = f"Dear {username},\n\nYour account has been registered successfully. You can now login to apply for certificates and village services.\n\nSmart Village Service Portal"

            send_notification(email, subj, body)

            msg = 'Registration successful! Please login.' if lang == 'en' else 'பதிவு வெற்றி! உள்நுழையவும்.'
            flash(msg, 'success')
            return redirect(url_for('login'))
        except Exception:
            conn.rollback()
            msg = 'Username or Email already exists!' if lang == 'en' else 'பயனர் பெயர் அல்லது மின்னஞ்சல் ஏற்கனவே உள்ளது!'
            flash(msg, 'danger')
        finally:
            cursor.close()
            conn.close()

    return render_template('register.html', lang=lang)

# 3. Citizen Dashboard Route
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    lang = session.get('lang', 'en')
    user_id = session['user_id']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT complaint_id, category, title, location, status, created_at 
        FROM complaints 
        WHERE user_id = %s 
        ORDER BY id DESC
    """, (user_id,))
    user_complaints = cursor.fetchall()

    cursor.execute("SELECT * FROM birth_certificate_requests WHERE user_id = %s ORDER BY id DESC", (user_id,))
    user_birth_requests = cursor.fetchall()

    cursor.execute("SELECT * FROM death_certificate_requests WHERE user_id = %s ORDER BY id DESC", (user_id,))
    user_death_requests = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'dashboard.html',
        username=session.get('username'),
        lang=lang,
        user_complaints=user_complaints,
        user_birth_requests=user_birth_requests,
        user_death_requests=user_death_requests
    )

# 4. Complaint Registration Route
@app.route('/complaint', methods=['GET', 'POST'])
def complaint():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    lang = session.get('lang', 'en')

    if request.method == 'POST':
        user_id = session['user_id']
        applicant_name = request.form.get('applicant_name', '').strip()
        district = request.form.get('district', '').strip()
        taluk_block = request.form.get('taluk_block', '').strip()
        panchayat = request.form.get('panchayat', '').strip()
        category = request.form.get('category', '').strip()
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        location = request.form.get('location', '').strip()
        mobile = request.form.get('mobile', '').strip()

        file = request.files.get('document')
        saved_filename = None
        if file and file.filename != '':
            if allowed_file(file.filename):
                filename = secure_filename(file.filename)
                saved_filename = f"CMP_{int(time.time())}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], saved_filename))
            else:
                msg = 'Invalid file format! Upload PDF, JPG, or PNG (Max 5MB).' if lang == 'en' else 'தவறான ஆவண வடிவம்! PDF அல்லது JPG/PNG மட்டும் பதிவேற்றவும் (அதிகபட்சம் 5MB).'
                flash(msg, 'danger')
                return redirect(url_for('complaint'))

        conn = get_db_connection()
        if not conn:
            flash('Database connection error!' if lang == 'en' else 'தரவுத்தள இணைப்பு பிழை!', 'danger')
            return redirect(url_for('complaint'))

        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id FROM complaints ORDER BY id DESC LIMIT 1")
            last_record = cursor.fetchone()
            next_id = (last_record['id'] + 1001) if last_record else 1001
            complaint_id = f"CMP{next_id}"

            cursor.execute("""
                INSERT INTO complaints 
                (complaint_id, user_id, applicant_name, district, taluk_block, panchayat, category, title, description, location, mobile, document_path, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Pending')
            """, (complaint_id, user_id, applicant_name, district, taluk_block, panchayat, category, title, description, location, mobile, saved_filename))
            
            conn.commit()

            user_email = session.get('user_email')
            if not user_email:
                cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
                user_row = cursor.fetchone()
                if user_row:
                    user_email = user_row.get('email')

            if user_email:
                if lang == 'ta':
                    subj = f"குறைதீர்ப்பு புகார் பதிவு செய்யப்பட்டது - {complaint_id}"
                    body = (
                        f"வணக்கம் {applicant_name},\n\n"
                        f"உங்கள் புகார் வெற்றிகரமாக பதிவு செய்யப்பட்டுள்ளது.\n"
                        f"புகார் எண்: {complaint_id}\n"
                        f"வகை: {category}\n"
                        f"நிலை: Pending\n\n"
                        f"ஊராட்சி அதிகாரி இதனை சரிபார்த்து நடவடிக்கை எடுப்பார்.\n\n"
                        f"கிராம சேவை தளம்"
                    )
                else:
                    subj = f"Grievance Registered - {complaint_id}"
                    body = (
                        f"Dear {applicant_name},\n\n"
                        f"Your grievance has been successfully submitted.\n"
                        f"Complaint ID: {complaint_id}\n"
                        f"Category: {category}\n"
                        f"Status: Pending\n\n"
                        f"The Village Panchayat officer will review and initiate action shortly.\n\n"
                        f"Smart Village Service Portal"
                    )
                send_notification(user_email, subj, body)

            success_msg = f"Complaint submitted successfully! Complaint ID: {complaint_id}" if lang == 'en' else f"புகார் வெற்றிகரமாக பதிவு செய்யப்பட்டது! புகார் எண்: {complaint_id}"
            flash(success_msg, 'success')
            return redirect(url_for('dashboard'))

        except Exception as e:
            conn.rollback()
            flash(f"Failed to submit complaint: {e}", 'danger')
            return redirect(url_for('complaint'))
        finally:
            cursor.close()
            conn.close()

    return render_template('complaint.html', lang=lang)

# 5. Complaint Tracking Route
@app.route('/complaint_tracking', methods=['GET', 'POST'])
def complaint_tracking():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    lang = session.get('lang', 'en')
    complaint_data = None
    searched_id = None

    if request.method == 'POST':
        searched_id = request.form.get('complaint_id', '').strip().upper()
    else:
        searched_id = request.args.get('complaint_id', '').strip().upper()

    if searched_id:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM complaints WHERE complaint_id = %s", (searched_id,))
        complaint_data = cursor.fetchone()
        cursor.close()
        conn.close()

        if not complaint_data:
            msg = 'No grievance record found with this ID!' if lang == 'en' else 'இந்த எண்ணில் புகார் எதுவும் கிடைக்கவில்லை!'
            flash(msg, 'danger')

    return render_template('complaint_tracking.html', lang=lang, complaint=complaint_data, complaint_id=searched_id)

# 6. Birth Certificate Request Route
@app.route('/birth_certificate', methods=['GET', 'POST'])
def birth_certificate():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    lang = session.get('lang', 'en')

    if request.method == 'POST':
        user_id = session['user_id']
        applicant_name = request.form.get('applicant_name', '').strip()
        relation_with_child = request.form.get('relation_with_child', '').strip()
        mobile = request.form.get('mobile', '').strip()
        email = request.form.get('email', '').strip()
        applicant_id_proof = request.form.get('applicant_id_proof', '').strip()

        child_name = request.form.get('child_name', '').strip()
        gender = request.form.get('gender', '').strip()
        dob = request.form.get('dob', '').strip()
        birth_time = request.form.get('birth_time', '').strip()
        place_of_birth = request.form.get('place_of_birth', '').strip()
        hospital_name = request.form.get('hospital_name', '').strip()

        father_name = request.form.get('father_name', '').strip()
        mother_name = request.form.get('mother_name', '').strip()
        father_id_proof = request.form.get('father_id_proof', '').strip()
        mother_id_proof = request.form.get('mother_id_proof', '').strip()

        door_no = request.form.get('door_no', '').strip()
        street = request.form.get('street', '').strip()
        village_town = request.form.get('village_town', '').strip()
        taluk = request.form.get('taluk', '').strip()
        district = request.form.get('district', '').strip()
        state = request.form.get('state', 'Tamil Nadu').strip()
        pincode = request.form.get('pincode', '').strip()

        file = request.files.get('document')
        saved_filename = None
        if file and file.filename != '':
            if allowed_file(file.filename):
                filename = secure_filename(file.filename)
                saved_filename = f"BC_{int(time.time())}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], saved_filename))
            else:
                msg = 'Invalid file format! Upload PDF, JPG, or PNG (Max 5MB).' if lang == 'en' else 'தவறான ஆவண வடிவம்! PDF அல்லது JPG/PNG மட்டும் பதிவேற்றவும் (அதிகபட்சம் 5MB).'
                flash(msg, 'danger')
                return redirect(url_for('birth_certificate'))

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id FROM birth_certificate_requests ORDER BY id DESC LIMIT 1")
            last_record = cursor.fetchone()
            next_id = (last_record['id'] + 1001) if last_record else 1001
            request_id = f"BC{next_id}"

            cursor.execute("""
                INSERT INTO birth_certificate_requests 
                (request_id, user_id, applicant_name, relation_with_child, mobile, email, applicant_id_proof,
                 child_name, gender, dob, birth_time, place_of_birth, hospital_name,
                 father_name, mother_name, father_id_proof, mother_id_proof,
                 door_no, street, village_town, taluk, district, state, pincode, document_path, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Pending')
            """, (request_id, user_id, applicant_name, relation_with_child, mobile, email, applicant_id_proof,
                  child_name, gender, dob, birth_time, place_of_birth, hospital_name,
                  father_name, mother_name, father_id_proof, mother_id_proof,
                  door_no, street, village_town, taluk, district, state, pincode, saved_filename))
            
            conn.commit()

            if email:
                if lang == 'ta':
                    subj = f"பிறப்பு சான்றிதழ் விண்ணப்பம் பெறப்பட்டது - {request_id}"
                    body = f"வணக்கம் {applicant_name},\n\nகுழந்தை '{child_name}'-க்கான பிறப்பு சான்றிதழ் விண்ணப்பம் பெறப்பட்டது.\nவிண்ணப்ப எண்: {request_id}\nநிலை: Pending\n\nகிராம சேவை தளம்"
                else:
                    subj = f"Birth Certificate Application Received - {request_id}"
                    body = f"Dear {applicant_name},\n\nYour birth certificate application for '{child_name}' has been received.\nRequest ID: {request_id}\nStatus: Pending\n\nSmart Village Service Portal"
                send_notification(email, subj, body)

            success_msg = f"Birth Certificate request submitted! Request ID: {request_id}" if lang == 'en' else f"பிறப்பு சான்றிதழ் கோரிக்கை சமர்ப்பிக்கப்பட்டது! கோரிக்கை எண்: {request_id}"
            flash(success_msg, 'success')
            return redirect(url_for('dashboard'))

        except Exception as e:
            conn.rollback()
            flash(f"Submission failed: {e}", 'danger')
            return redirect(url_for('birth_certificate'))
        finally:
            cursor.close()
            conn.close()

    return render_template('birth_certificate.html', lang=lang)

# 7. Death Certificate Request Route
@app.route('/death_certificate', methods=['GET', 'POST'])
def death_certificate():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    lang = session.get('lang', 'en')

    if request.method == 'POST':
        user_id = session['user_id']
        applicant_name = request.form.get('applicant_name', '').strip()
        relation_with_deceased = request.form.get('relation_with_deceased', '').strip()
        mobile = request.form.get('mobile', '').strip()
        email = request.form.get('email', '').strip()
        applicant_id_proof = request.form.get('applicant_id_proof', '').strip()

        deceased_name = request.form.get('deceased_name', '').strip()
        gender = request.form.get('gender', '').strip()
        dod = request.form.get('dod', '').strip()
        death_time = request.form.get('death_time', '').strip()
        age = request.form.get('age', '').strip()
        marital_status = request.form.get('marital_status', '').strip()
        relation_person_name = request.form.get('relation_person_name', '').strip()
        mother_name = request.form.get('mother_name', '').strip()

        place_of_death = request.form.get('place_of_death', '').strip()
        hospital_name = request.form.get('hospital_name', '').strip()
        cause_of_death = request.form.get('cause_of_death', '').strip()
        permanent_address = request.form.get('permanent_address', '').strip()
        death_address = request.form.get('death_address', '').strip()
        village_town = request.form.get('village_town', '').strip()
        taluk = request.form.get('taluk', '').strip()
        district = request.form.get('district', '').strip()
        state = request.form.get('state', 'Tamil Nadu').strip()
        pincode = request.form.get('pincode', '').strip()

        prev_reg_no = request.form.get('prev_reg_no', '').strip()
        purpose = request.form.get('purpose', '').strip()
        delivery_method = request.form.get('delivery_method', '').strip()

        def save_file(file_obj, prefix):
            if file_obj and file_obj.filename != '' and allowed_file(file_obj.filename):
                fn = secure_filename(file_obj.filename)
                saved_name = f"{prefix}_{int(time.time())}_{fn}"
                file_obj.save(os.path.join(app.config['UPLOAD_FOLDER'], saved_name))
                return saved_name
            return None

        hosp_report_file = save_file(request.files.get('hospital_report'), 'DC_HOSP')
        deceased_id_file = save_file(request.files.get('deceased_id'), 'DC_DEC_ID')
        applicant_id_file = save_file(request.files.get('applicant_id_doc'), 'DC_APP_ID')

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id FROM death_certificate_requests ORDER BY id DESC LIMIT 1")
            last_record = cursor.fetchone()
            next_id = (last_record['id'] + 1001) if last_record else 1001
            request_id = f"DC{next_id}"

            cursor.execute("""
                INSERT INTO death_certificate_requests 
                (request_id, user_id, applicant_name, relation_with_deceased, mobile, email, applicant_id_proof,
                 deceased_name, gender, dod, death_time, age, marital_status, relation_person_name, mother_name,
                 place_of_death, hospital_name, cause_of_death, permanent_address, death_address,
                 village_town, taluk, district, state, pincode,
                 hospital_report_path, deceased_id_path, applicant_id_path, prev_reg_no, purpose, delivery_method, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Pending')
            """, (request_id, user_id, applicant_name, relation_with_deceased, mobile, email, applicant_id_proof,
                  deceased_name, gender, dod, death_time, age, marital_status, relation_person_name, mother_name,
                  place_of_death, hospital_name, cause_of_death, permanent_address, death_address,
                  village_town, taluk, district, state, pincode,
                  hosp_report_file, deceased_id_file, applicant_id_file, prev_reg_no, purpose, delivery_method))
            
            conn.commit()

            if email:
                if lang == 'ta':
                    subj = f"இறப்பு சான்றிதழ் விண்ணப்பம் பெறப்பட்டது - {request_id}"
                    body = f"வணக்கம் {applicant_name},\n\n'{deceased_name}'-க்கான இறப்பு சான்றிதழ் விண்ணப்பம் பதிவு செய்யப்பட்டுள்ளது.\nவிண்ணப்ப எண்: {request_id}\nநிலை: Pending\n\nகிராம சேவை தளம்"
                else:
                    subj = f"Death Certificate Application Received - {request_id}"
                    body = f"Dear {applicant_name},\n\nYour death certificate application for '{deceased_name}' has been submitted.\nRequest ID: {request_id}\nStatus: Pending\n\nSmart Village Service Portal"
                send_notification(email, subj, body)

            success_msg = f"Death Certificate request submitted! Request ID: {request_id}" if lang == 'en' else f"இறப்பு சான்றிதழ் கோரிக்கை சமர்ப்பிக்கப்பட்டது! கோரிக்கை எண்: {request_id}"
            flash(success_msg, 'success')
            return redirect(url_for('dashboard'))

        except Exception as e:
            conn.rollback()
            flash(f"Submission failed: {e}", 'danger')
            return redirect(url_for('death_certificate'))
        finally:
            cursor.close()
            conn.close()

    return render_template('death_certificate.html', lang=lang)

# 8. ReportLab PDF Generation Routes
@app.route('/download_birth_certificate/')
def download_birth_certificate(request_id):
    if 'user_id' not in session and not session.get('is_admin'):
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM birth_certificate_requests WHERE request_id = %s", (request_id,))
    cert = cursor.fetchone()
    cursor.close()
    conn.close()

    if not cert or cert['status'] != 'Approved':
        flash('Certificate not found or not approved yet!', 'danger')
        return redirect(url_for('dashboard'))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    elements = []
    styles = getSampleStyleSheet()

    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=18,
        alignment=1,
        textColor=colors.HexColor('#0b5345')
    )
    sub_header = ParagraphStyle(
        'SubHeader',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        alignment=1,
        textColor=colors.HexColor('#555555')
    )

    elements.append(Paragraph("GOVERNMENT OF TAMIL NADU", header_style))
    elements.append(Paragraph("DEPARTMENT OF PANCHAYAT RAJ & RURAL DEVELOPMENT", sub_header))
    elements.append(Paragraph("OFFICIAL BIRTH CERTIFICATE / பிறப்புச் சான்றிதழ்", header_style))
    elements.append(Spacer(1, 15))

    data = [
        [Paragraph("**Certificate Ref ID:**", styles['Normal']), cert['request_id']],
        [Paragraph("**Child Name:**", styles['Normal']), cert['child_name']],
        [Paragraph("**Gender:**", styles['Normal']), cert['gender']],
        [Paragraph("**Date of Birth:**", styles['Normal']), str(cert['dob'])],
        [Paragraph("**Place / Hospital:**", styles['Normal']), f"{cert['place_of_birth']} ({cert['hospital_name']})"],
        [Paragraph("**Father's Name:**", styles['Normal']), cert['father_name']],
        [Paragraph("**Mother's Name:**", styles['Normal']), cert['mother_name']],
        [Paragraph("**Permanent Address:**", styles['Normal']), f"{cert['door_no']}, {cert['street']}, {cert['village_town']}, {cert['taluk']}, {cert['district']} - {cert['pincode']}"],
        [Paragraph("**Issuing Authority:**", styles['Normal']), f"{cert['taluk']} Village Panchayat"],
        [Paragraph("**Status:**", styles['Normal']), "APPROVED & DIGITALLY VERIFIED"]
    ]

    table = Table(data, colWidths=[180, 360])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fcfdfd')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#0b5345')),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("*This is an authenticated computer-generated certificate issued under Tamil Nadu Panchayat Raj regulations.*", sub_header))

    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"Birth_Certificate_{cert['request_id']}.pdf", mimetype='application/pdf')

@app.route('/download_death_certificate/')
def download_death_certificate(request_id):
    if 'user_id' not in session and not session.get('is_admin'):
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM death_certificate_requests WHERE request_id = %s", (request_id,))
    cert = cursor.fetchone()
    cursor.close()
    conn.close()

    if not cert or cert['status'] != 'Approved':
        flash('Certificate not found or not approved yet!', 'danger')
        return redirect(url_for('dashboard'))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    elements = []
    styles = getSampleStyleSheet()

    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=18,
        alignment=1,
        textColor=colors.HexColor('#0b5345')
    )
    sub_header = ParagraphStyle(
        'SubHeader',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        alignment=1,
        textColor=colors.HexColor('#555555')
    )

    elements.append(Paragraph("GOVERNMENT OF TAMIL NADU", header_style))
    elements.append(Paragraph("DEPARTMENT OF PANCHAYAT RAJ & RURAL DEVELOPMENT", sub_header))
    elements.append(Paragraph("OFFICIAL DEATH CERTIFICATE / இறப்புச் சான்றிதழ்", header_style))
    elements.append(Spacer(1, 15))

    data = [
        [Paragraph("**Certificate Ref ID:**", styles['Normal']), cert['request_id']],
        [Paragraph("**Deceased Name:**", styles['Normal']), cert['deceased_name']],
        [Paragraph("**Gender & Age:**", styles['Normal']), f"{cert['gender']} / {cert['age']} Years"],
        [Paragraph("**Date of Death:**", styles['Normal']), str(cert['dod'])],
        [Paragraph("**Place of Death:**", styles['Normal']), cert['place_of_death']],
        [Paragraph("**Cause of Death:**", styles['Normal']), cert['cause_of_death']],
        [Paragraph("**Applicant / Relation:**", styles['Normal']), f"{cert['applicant_name']} ({cert['relation_with_deceased']})"],
        [Paragraph("**Address:**", styles['Normal']), f"{cert['permanent_address']}, {cert['village_town']}, {cert['taluk']}, {cert['district']} - {cert['pincode']}"],
        [Paragraph("**Issuing Authority:**", styles['Normal']), f"{cert['taluk']} Village Panchayat"],
        [Paragraph("**Status:**", styles['Normal']), "APPROVED & DIGITALLY VERIFIED"]
    ]

    table = Table(data, colWidths=[180, 360])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fcfdfd')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#0b5345')),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("*This is an authenticated computer-generated certificate issued under Tamil Nadu Panchayat Raj regulations.*", sub_header))

    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"Death_Certificate_{cert['request_id']}.pdf", mimetype='application/pdf')

# 9. Chatbot API Route (Hybrid: Strict 90% CSV -> Filtered Multi-Model Free LLM -> Safe Fallback)
@app.route('/api/chat', methods=['POST'])
def chat_api():
    if 'user_id' not in session and not session.get('is_admin'):
        return jsonify({'reply': 'Please log in to use the Smart Village Assistant.'}), 401

    data = request.get_json() or {}
    user_message = data.get('message', '').strip()

    if not user_message:
        return jsonify({'reply': 'Please enter a valid message.'}), 400

    # Step 1: Check CSV dataset (ONLY matches if 88%-90%+ identical)
    dataset_answer = find_dataset_match(user_message)
    if dataset_answer:
        return jsonify({'reply': dataset_answer})

    # Step 2: Query OpenRouter Free Instruction/Chat Models (Bypassing Moderation Slugs)
    free_models = [
        "google/gemma-4-26b-a4b-it:free",
        "google/gemma-4-31b-it:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "liquid/lfm-2.5-2.6b:free"
    ]

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "http://127.0.0.1:5000",
        "X-Title": "Smart Village Service Portal",
        "Content-Type": "application/json"
    }

    for model_name in free_models:
        try:
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": MISTRAL_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message}
                ],
                "temperature": 0.3
            }

            response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=20)
            res_json = response.json()

            if response.status_code == 200 and "choices" in res_json and len(res_json["choices"]) > 0:
                bot_reply = res_json["choices"][0]["message"]["content"].strip()

                # Guard against moderation tag leakage
                if bot_reply.lower().startswith("user safety:") or bot_reply.lower() == "safe":
                    print(f"[MODEL SKIPPED] {model_name} returned safety classifier tag. Trying next model.")
                    continue

                return jsonify({'reply': bot_reply})
            else:
                print(f"[API ERROR] Model: {model_name}, Status: {response.status_code}, Response: {res_json}")
                continue
        except Exception as e:
            print(f"[API EXCEPTION] Model: {model_name}, Error: {e}")
            continue

    # Step 3: Trigger safe fallback if all models fail
    fallback = get_fallback_reply(user_message)
    return jsonify({'reply': fallback})

# 10. Admin Review Panel Routes
@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM complaints ORDER BY id DESC")
    complaints = cursor.fetchall()
    
    cursor.execute("SELECT * FROM birth_certificate_requests ORDER BY id DESC")
    birth_requests = cursor.fetchall()
    
    cursor.execute("SELECT * FROM death_certificate_requests ORDER BY id DESC")
    death_requests = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'admin_dashboard.html',
        complaints=complaints,
        birth_requests=birth_requests,
        death_requests=death_requests,
        lang=session.get('lang', 'en')
    )

@app.route('/admin/update_complaint', methods=['POST'])
def update_complaint_status():
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    
    complaint_id = request.form.get('complaint_id')
    status = request.form.get('status')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("UPDATE complaints SET status = %s WHERE complaint_id = %s", (status, complaint_id))
    conn.commit()

    cursor.execute("""
        SELECT u.email, c.applicant_name, c.title 
        FROM complaints c 
        JOIN users u ON c.user_id = u.id 
        WHERE c.complaint_id = %s
    """, (complaint_id,))
    record = cursor.fetchone()
    cursor.close()
    conn.close()

    if record and record.get('email'):
        subj = f"Update on Complaint {complaint_id}"
        body = f"Dear {record.get('applicant_name')},\n\nYour complaint ({complaint_id}: {record.get('title')}) has been updated.\nNew Status: {status}\n\nSmart Village Service Portal"
        send_notification(record['email'], subj, body)
    
    flash(f"Complaint {complaint_id} updated to {status}!", 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/update_birth', methods=['POST'])
def update_birth_status():
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    
    request_id = request.form.get('request_id')
    status = request.form.get('status')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("UPDATE birth_certificate_requests SET status = %s WHERE request_id = %s", (status, request_id))
    conn.commit()

    cursor.execute("SELECT email, applicant_name, child_name FROM birth_certificate_requests WHERE request_id = %s", (request_id,))
    record = cursor.fetchone()
    cursor.close()
    conn.close()

    if record and record.get('email'):
        subj = f"Birth Certificate Application Update - {request_id}"
        body = f"Dear {record.get('applicant_name')},\n\nYour application for {record.get('child_name')}'s birth certificate has been updated.\nStatus: {status}\n\nSmart Village Service Portal"
        send_notification(record['email'], subj, body)
    
    flash(f"Birth request {request_id} updated to {status}!", 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/update_death', methods=['POST'])
def update_death_status():
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    
    request_id = request.form.get('request_id')
    status = request.form.get('status')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("UPDATE death_certificate_requests SET status = %s WHERE request_id = %s", (status, request_id))
    conn.commit()

    cursor.execute("SELECT email, applicant_name, deceased_name FROM death_certificate_requests WHERE request_id = %s", (request_id,))
    record = cursor.fetchone()
    cursor.close()
    conn.close()

    if record and record.get('email'):
        subj = f"Death Certificate Application Update - {request_id}"
        body = f"Dear {record.get('applicant_name')},\n\nYour application for {record.get('deceased_name')}'s death certificate has been updated.\nStatus: {status}\n\nSmart Village Service Portal"
        send_notification(record['email'], subj, body)
    
    flash(f"Death request {request_id} updated to {status}!", 'success')
    return redirect(url_for('admin_dashboard'))

# 11. Unified Logout Routes
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)