from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session, flash, make_response, jsonify
import mysql.connector
from mysql.connector import Error
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from flask_mail import Mail, Message
import qrcode
import base64
from io import BytesIO
from xhtml2pdf import pisa
import os
import time
import threading
from pdf_extractor import extract_students_from_pdf
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'sabari_super_secret_key_123'

# MySQL Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'sabari@2006',
    'database': 'examdb'
}

# Flask-Mail Config
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USE_SSL=False,
    MAIL_USERNAME='sabarilathapandi@gmail.com',
    MAIL_PASSWORD='fssv tsdk chxw prgu',
    MAIL_DEFAULT_SENDER='sabarilathapandi@gmail.com'
)

# Department Code Mapping
DEPARTMENT_CODES = {
    'TAM': '101',
    'ENG': '103',
    'HIS': '111',
    'MATHS': '121',
    'PHY': '122',
    'CHE': '124',
    'BOT': '125',
    'ZOO': '126',
    'BCA': '127',
    'CS': '128',
    'GEO': '136',
    'B.COM': '151',
    'BBA': '153',
    'ECO': '158',
    'ALL': '999'
}

# Reverse mapping for display
DEPARTMENT_CODES_REVERSE = {v: k for k, v in DEPARTMENT_CODES.items()}

# Department name to code mapping (handles both full names and abbreviations)
DEPARTMENT_NAME_TO_CODE = {
    # Abbreviations (from DEPARTMENT_CODES)
    'TAM': 'TAM', 'ENG': 'ENG', 'HIS': 'HIS', 'MATHS': 'MATHS', 'PHY': 'PHY',
    'CHE': 'CHE', 'BOT': 'BOT', 'ZOO': 'ZOO', 'BCA': 'BCA', 'CS': 'CS',
    'GEO': 'GEO', 'B.COM': 'B.COM', 'BBA': 'BBA', 'ECO': 'ECO',
    
    # Full names (common variations found in student data)
    'TAMIL': 'TAM', 'Tamil': 'TAM', 'tamil': 'TAM',
    'ENGLISH': 'ENG', 'English': 'ENG', 'english': 'ENG',
    'HISTORY': 'HIS', 'History': 'HIS', 'history': 'HIS',
    'MATH': 'MATHS', 'MATHEMATICS': 'MATHS', 'Maths': 'MATHS', 'Maths': 'MATHS', 'maths': 'MATHS',
    'PHYSICS': 'PHY', 'Physics': 'PHY', 'physics': 'PHY',
    'CHEMISTRY': 'CHE', 'Chem': 'CHE', 'Chemistry': 'CHE', 'chemistry': 'CHE',
    'BOTANY': 'BOT', 'Botany': 'BOT', 'botany': 'BOT',
    'ZOOLOGY': 'ZOO', 'Zoology': 'ZOO', 'zoology': 'ZOO',
    'BCA': 'BCA', 'Bca': 'BCA', 'bca': 'BCA',
    'COMPUTER SCIENCE': 'CS', 'Computer Science': 'CS', 'Cs': 'CS', 'cs': 'CS', 'CS': 'CS',
    'GEOLOGY': 'GEO', 'Geology': 'GEO', 'geology': 'GEO',
    'B.COM': 'B.COM', 'B.Com': 'B.COM', 'bcom': 'B.COM', 'BCOM': 'B.COM', 'Bcom': 'B.COM',
    'COMMERCE': 'B.COM',
    'BBA': 'BBA', 'Bba': 'BBA', 'bba': 'BBA',
    'ECONOMICS': 'ECO', 'Economics': 'ECO', 'Eco': 'ECO', 'eco': 'ECO', 'ECO': 'ECO',
    'ALL': 'ALL'
}

def normalize_department(dept_name):
    """Convert any department name to standard code"""
    if not dept_name:
        return None
    dept_str = str(dept_name).strip()
    return DEPARTMENT_NAME_TO_CODE.get(dept_str, dept_str.upper())

mail = Mail(app)

# Custom Jinja2 filter to sort dictionary items by exam code, then by room/hall within exam code
def sort_halls(halls_dict):
    """Sort halls: first by exam_code, then by room/hall (வா first, then B.COM, then others), maintaining allocation order"""
    import re
    
    def sort_key(item):
        hall_no = item[0]  # e.g., "வா1", "B.COM1", "BBA1"
        hall_data = item[1]
        # Default values
        exam_code = ''
        year = 9999
        dept_code = ''
        class_num = 0
        suffix = ''
        # Get the info from the first seat in the hall
        if 'info' in hall_data and hall_data['info']:
            # Primary: Sort by exam_code
            exam_code = hall_data['info'].get('exam_code', '')
            # Parse exam_code: e.g., "23BAE3C2" -> year=23, dept=BAE, class=3, suffix=C2
            exam_match = re.match(r'^(\d+)([A-Z]+)(\d+)([A-Z]\d?)$', exam_code)
            if exam_match:
                year = int(exam_match.group(1))
                dept_code = exam_match.group(2)
                class_num = int(exam_match.group(3))
                suffix = exam_match.group(4)
            else:
                dept_code = exam_code
        # Secondary: Sort by hall/room name (வா, B.COM, BBA, BCA, etc.)
        # Determine priority for room type
        if hall_no.startswith('வா'):
            room_priority = 0
        elif hall_no.startswith('B.COM'):
            room_priority = 1
        elif hall_no.startswith('BBA'):
            room_priority = 2
        elif hall_no.startswith('BCA'):
            room_priority = 3
        elif hall_no.startswith('BOT'):
            room_priority = 4
        else:
            room_priority = 5
        # Extract number from hall_no: "வா1" -> 1, "B.COM2" -> 2, "BBA3" -> 3
        num_match = re.search(r'(\d+)$', hall_no)
        room_number = int(num_match.group(1)) if num_match else 999
        # Return tuple: exam_code first, then room priority, then room number
        return (year, dept_code, class_num, suffix, room_priority, room_number)
    
    return sorted(halls_dict.items(), key=sort_key)

app.jinja_env.filters['sort_halls'] = sort_halls

@app.route('/test_mail')
def test_mail():
    try:
        msg = Message(
            "Test Email",
            recipients=["your_email@gmail.com"]
        )
        msg.body = "Flask-Mail is working!"
        mail.send(msg)
        return "[OK] Email sent successfully!"
    except Exception as e:
        return f"[ERROR] Error: {str(e)}"

def get_db_connection():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as e:
        print(f"Error connecting to database: {e}")
        return None

def notify_students_by_exam(exam_code, mode='new'):
    """Send notifications to students in background with rate limiting"""
    def send_emails_background():
        # Must create application context for Flask extensions to work in threads
        with app.app_context():
            conn = get_db_connection()
            if not conn:
                print("Failed to connect to database for notifications")
                return
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM exams WHERE exam_code = %s", (exam_code,))
            exam = cursor.fetchone()
            if not exam:
                print("No exam found for code:", exam_code)
                cursor.close()
                conn.close()
                return

            department = exam['department']
            subject = exam['subject']
            exam_date = exam['exam_date']
            exam_time = exam['start_time']

            cursor.execute("SELECT email FROM students WHERE department = %s", (department,))
            students = cursor.fetchall()
            print(f"Department: {department}, Students found: {len(students)}")

            if mode == 'new':
                subject_line = f"New Exam Scheduled: {subject}"
                body = f"""Dear Student,

A new exam has been scheduled.

Subject: {subject}
Date: {exam_date}
Time: {exam_time}

Please check the portal for more details.

- Exam Committee"""
            elif mode == 'update':
                subject_line = f"Exam Updated: {subject}"
                body = f"""Dear Student,

An existing exam has been modified.

Subject: {subject}
New Date: {exam_date}
New Time: {exam_time}

Please verify the changes on the portal.

- Exam Committee"""
            elif mode == 'delete':
                subject_line = f"Exam Cancelled: {subject}"
                body = f"""Dear Student,

The following exam has been cancelled.

Subject: {subject}
Scheduled Date: {exam_date}
Time: {exam_time}

Please ignore any previous communication regarding this exam.

- Exam Committee"""

            # Send emails with rate limiting (2 second delay between emails)
            # This prevents hitting Gmail's daily limit
            sent_count = 0
            failed_count = 0
            
            for idx, student in enumerate(students):
                email = student['email']
                print(f"Sending to: {email} ({idx + 1}/{len(students)})")
                try:
                    msg = Message(subject_line, sender=app.config['MAIL_USERNAME'], recipients=[email])
                    msg.body = body
                    mail.send(msg)
                    sent_count += 1
                except Exception as e:
                    failed_count += 1
                    print(f"Error sending to {email}: {e}")
                
                # Rate limiting: wait 2 seconds between emails to avoid hitting Gmail limits
                # Gmail free accounts can send ~500 emails/day, so this spacing is safe
                if idx < len(students) - 1:  # Don't sleep after the last email
                    time.sleep(2)
            
            print(f"\n[SUMMARY] Email notification complete!")
            print(f"Successfully sent: {sent_count}/{len(students)}")
            if failed_count > 0:
                print(f"Failed to send: {failed_count}/{len(students)}")
            
            cursor.close()
            conn.close()

    # Run email sending in background thread so it doesn't block the request
    thread = threading.Thread(target=send_emails_background, daemon=True)
    thread.start()


def init_db():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS exams (
                exam_code VARCHAR(20) PRIMARY KEY,
                subject VARCHAR(100),
                semester VARCHAR(10),
                department VARCHAR(50),
                exam_date DATE,
                start_time VARCHAR(20),
                end_time VARCHAR(20),
                total_students INT,
                college_code VARCHAR(10),
                department_code VARCHAR(10),
                exam_session VARCHAR(20),
                register_range VARCHAR(50),
                is_arrear TINYINT(1) DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS students (
                roll_no VARCHAR(20) PRIMARY KEY,
                name VARCHAR(100),
                email VARCHAR(100),
                department VARCHAR(50),
                semester VARCHAR(10),
                image_path VARCHAR(255),
                is_arrear TINYINT(1) DEFAULT 0,
                arrear_semester INT DEFAULT NULL,
                arrear_exam_code VARCHAR(50) DEFAULT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS exam_seating (
                id INT AUTO_INCREMENT PRIMARY KEY,
                exam_code VARCHAR(20),
                roll_no VARCHAR(20),
                room VARCHAR(50),
                class_no INT,
                col INT,
                position VARCHAR(20),
                bench_no INT,
                seat_num INT,
                staff_id INT,
                invigilator VARCHAR(100),
                exam_date DATE,
                exam_session VARCHAR(20),
                is_absent TINYINT(1) DEFAULT 0,
                absence_reason VARCHAR(255) DEFAULT NULL,
                marked_absent_at DATETIME DEFAULT NULL,
                UNIQUE KEY (exam_code, roll_no)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS staff (
                staff_id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100),
                email VARCHAR(100),
                department VARCHAR(50)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS department_bench_info (
                id INT AUTO_INCREMENT PRIMARY KEY,
                department VARCHAR(50),
                block_number INT,
                class_number INT,
                bench_count INT,
                total_capacity INT,
                UNIQUE KEY (department, block_number, class_number)
            )
        ''')
        conn.commit()
        print(f"[OK] Database initialized successfully")
    except Error as e:
        print(f"[ERROR] Error initializing DB: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/create-manage')
def create_page():
    return render_template('create-manage.html')

@app.route('/notifications')
def notifications_page():
    return render_template('notifications.html')

@app.route('/multi-user')
def multi_user_page():
    return render_template('multi-user.html')

@app.route('/reports')
def reports_page():
    return render_template('reports.html')

@app.route('/admin-feature')
def admin_feature_page():
    return render_template('admin_feature.html')

@app.route('/invigilator')
def invigilator_page():
    return render_template('invigilator.html')

@app.route('/filter')
def filter_page():
    return render_template('filter.html')

@app.route('/views')
def views_page():
    return render_template('views.html')

@app.route('/index', methods=['GET'])
def index():
    semester = str(request.args.get('semester', '')).strip()
    department = request.args.get('department', '')
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = '''
            SELECT exam_code, subject, semester, department, exam_date, start_time, end_time, total_students, college_code, department_code, exam_session, register_range
            FROM exams WHERE 1=1
        '''
        params = []
        if semester:
            query += ' AND CAST(semester AS CHAR) = %s'
            params.append(semester)
        if department:
            query += " AND (UPPER(department) = %s OR department = 'ALL')"
            params.append(department.upper())
        cursor.execute(query, params)
        exams = [
            {
                'exam_code': row[0],
                'subject': row[1],
                'semester': row[2],
                'department': row[3],
                'exam_date': row[4].strftime('%d-%m-%Y'),
                'start_time': row[5],
                'end_time': row[6],
                'total_students': row[7],
                'college_code': row[8],
                'department_code': row[9],
                'exam_session': row[10],
                'register_range': row[11]
            } for row in cursor.fetchall()
        ]
    except Error as e:
        exams = []
        print(f"Error fetching exams: {e}")
    finally:
        cursor.close()
        conn.close()
    return render_template('index.html', exams=exams)
@app.route('/add_department', methods=['GET', 'POST'])
def add_department():
    if request.method == 'POST':
        department = request.form['department'].upper()
        num_blocks = int(request.form['num_blocks'])
        num_classes = int(request.form['num_classes'])

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # normalize the name we'll store and display (VA uses Tamil character)
            if department == 'VA':
                department_display = 'வா'
            else:
                department_display = department

            # delete any existing rows for this department so we don't end up
            # with duplicate entries when the same department is submitted twice.
            # This makes the POST idempotent: re‑submitting simply replaces the
            # previous configuration instead of appending another set of rows.
            cursor.execute(
                "DELETE FROM department_bench_info WHERE department = %s",
                (department_display,)
            )

            # Insert one record per class per block
            for block in range(1, num_blocks + 1):
                for class_no in range(1, num_classes + 1):
                    # Get bench count from form (will be submitted for each class)
                    bench_count_key = f'bench_count_{block}_{class_no}'
                    bench_count = int(request.form.get(bench_count_key, 15))
                    total_capacity = bench_count * 3  # Each bench seats 3 students

                    cursor.execute('''
                        INSERT INTO department_bench_info
                        (department, block_number, class_number, bench_count, total_capacity)
                        VALUES (%s, %s, %s, %s, %s)
                    ''', (department_display, block, class_no, bench_count, total_capacity))
            
            conn.commit()
            cursor.close()
            conn.close()

            # after bench information changes, refresh seating for all upcoming exams
            threading.Thread(target=allocate_seating_for_all_upcoming_exams, daemon=True).start()

            flash(f'[OK] Department {department} with {num_blocks} blocks and {num_classes} classes added successfully!')
        except mysql.connector.Error as e:
            flash(f'[ERROR] Error saving data: {e}')

        return redirect(url_for('add_department'))

    return render_template('add_department.html')

@app.route('/add-student', methods=['GET', 'POST'])
def add_student():
    if not session.get('student_admin'):
        return redirect(url_for('login', next='student'))
    message = None
    if request.method == 'POST':
        roll_no = request.form['roll_no']
        name = request.form['name']
        email = request.form['email']
        department = request.form['department']
        semester = request.form['semester']
        is_arrear = request.form.get('is_arrear', '0')  # 0 = No, 1 = Yes
        arrear_semester = request.form.get('arrear_semester', None)
        arrear_exam_code = request.form.get('arrear_exam_code', None)
        
        image = request.files.get('image')
        image_filename = None
        if image:
            image_filename = f"{roll_no}_{email.replace('@','_')}.jpg"
            image_path = os.path.join('static/uploads', image_filename)
            os.makedirs(os.path.dirname(image_path), exist_ok=True)
            image.save(image_path)
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Normalize department name before storing
            normalized_dept = normalize_department(department)
            print(f"[DEBUG] Student {roll_no}: dept_input='{department}' -> normalized='{normalized_dept}'")
            
            # Check if students table has arrear columns, if not add them
            cursor.execute("DESCRIBE students")
            columns = [col[0] for col in cursor.fetchall()]
            
            if 'is_arrear' not in columns:
                cursor.execute("ALTER TABLE students ADD COLUMN is_arrear TINYINT(1) DEFAULT 0")
            if 'arrear_semester' not in columns:
                cursor.execute("ALTER TABLE students ADD COLUMN arrear_semester INT DEFAULT NULL")
            if 'arrear_exam_code' not in columns:
                cursor.execute("ALTER TABLE students ADD COLUMN arrear_exam_code VARCHAR(50) DEFAULT NULL")
            
            conn.commit()
            
            # Insert student with normalized department and arrear information
            cursor.execute(
                "INSERT INTO students (roll_no, name, email, department, semester, image_path, is_arrear, arrear_semester, arrear_exam_code) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (roll_no, name, email, normalized_dept, semester, image_filename, is_arrear, arrear_semester if is_arrear == '1' else None, arrear_exam_code if is_arrear == '1' else None)
            )
            conn.commit()
            message = "[OK] Student added successfully."
            
            # If student is arrear, log the arrear information
            if is_arrear == '1':
                message = f"[OK] Student added successfully. Marked as ARREAR in Sem {arrear_semester} for exam {arrear_exam_code}."

            # fire seating refresh asynchronously so the new student is seated
            threading.Thread(target=allocate_seating_for_all_upcoming_exams, daemon=True).start()
        except Error as e:
            message = f"[ERROR] Error adding student: {str(e)}"
        finally:
            cursor.close()
            conn.close()
    return render_template('add_student.html', message=message)

@app.route('/upload_students_pdf', methods=['POST'])
def upload_students_pdf():
    """Handle PDF upload for bulk student addition"""
    if not session.get('student_admin'):
        return jsonify({'success': False, 'errors': ['Unauthorized access']}), 401
    
    action = request.form.get('action', 'preview')  # 'preview' or 'upload'
    
    if 'pdf_file' not in request.files:
        return jsonify({'success': False, 'errors': ['No PDF file provided']})
    
    pdf_file = request.files['pdf_file']
    
    if pdf_file.filename == '':
        return jsonify({'success': False, 'errors': ['No file selected']})
    
    if not pdf_file.filename.lower().endswith('.pdf'):
        return jsonify({'success': False, 'errors': ['Please upload a PDF file']})
    
    try:
        # Extract students from PDF
        students, errors = extract_students_from_pdf(pdf_file)
        
        if action == 'preview':
            # Just return preview data
            return jsonify({
                'success': len(students) > 0 or len(errors) == 0,
                'students': students,
                'errors': errors
            })
        
        elif action == 'upload':
            # Insert students into database
            if not students:
                return jsonify({
                    'success': False,
                    'errors': ['No valid students to upload'] + errors
                })
            
            conn = get_db_connection()
            if not conn:
                return jsonify({'success': False, 'errors': ['Database connection failed']})
            
            cursor = conn.cursor()
            uploaded_count = 0
            insert_errors = []
            
            try:
                # Check if students table has arrear columns
                cursor.execute("DESCRIBE students")
                columns = [col[0] for col in cursor.fetchall()]
                
                if 'is_arrear' not in columns:
                    cursor.execute("ALTER TABLE students ADD COLUMN is_arrear TINYINT(1) DEFAULT 0")
                if 'arrear_semester' not in columns:
                    cursor.execute("ALTER TABLE students ADD COLUMN arrear_semester INT DEFAULT NULL")
                if 'arrear_exam_code' not in columns:
                    cursor.execute("ALTER TABLE students ADD COLUMN arrear_exam_code VARCHAR(50) DEFAULT NULL")
                
                conn.commit()
                
                # Insert each student
                for student in students:
                    try:
                        # Normalize department name
                        normalized_dept = normalize_department(student.get('department', ''))
                        
                        # Set defaults for optional fields
                        is_arrear = student.get('is_arrear', '0')
                        arrear_semester = student.get('arrear_semester') if is_arrear == '1' else None
                        arrear_exam_code = student.get('arrear_exam_code') if is_arrear == '1' else None
                        
                        cursor.execute(
                            """INSERT INTO students 
                               (roll_no, name, email, department, semester, image_path, is_arrear, arrear_semester, arrear_exam_code) 
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                               ON DUPLICATE KEY UPDATE 
                               name=VALUES(name), email=VALUES(email), department=VALUES(department), 
                               semester=VALUES(semester), is_arrear=VALUES(is_arrear), 
                               arrear_semester=VALUES(arrear_semester), arrear_exam_code=VALUES(arrear_exam_code)
                            """,
                            (student['roll_no'], student['name'], student['email'], 
                             normalized_dept, student['semester'], None,
                             is_arrear, arrear_semester, arrear_exam_code)
                        )
                        uploaded_count += 1
                    except Error as e:
                        insert_errors.append(f"Error adding {student.get('roll_no', 'N/A')}: {str(e)}")
                
                conn.commit()
                cursor.close()
                conn.close()
                
                # kick off seating update for all upcoming exams
                threading.Thread(target=allocate_seating_for_all_upcoming_exams, daemon=True).start()

                message = f"[OK] Successfully uploaded {uploaded_count} student(s)"
                if insert_errors:
                    message += f". {len(insert_errors)} error(s) occurred."
                
                return jsonify({
                    'success': True,
                    'message': message,
                    'uploaded_count': uploaded_count,
                    'errors': insert_errors
                })
                
            except Error as e:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()
                return jsonify({
                    'success': False,
                    'errors': [f'Database error: {str(e)}'] + insert_errors
                })
        
        else:
            return jsonify({'success': False, 'errors': ['Invalid action']})
    
    except Exception as e:
        return jsonify({
            'success': False,
            'errors': [f'Error processing PDF: {str(e)}']
        })

def chatbot_answer(question):
    intent = detect_intent(question)
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if intent == "exam_list":
        department, semester, _ = extract_details(question)
        if not department or not semester:
            return "Please mention both department and semester."
        semester_str = str(semester).strip()
        cursor.execute("""
            SELECT subject, exam_date, start_time
            FROM exams
            WHERE (department = %s OR department = 'ALL')
              AND CAST(semester AS CHAR) = %s
            ORDER BY exam_date
        """, (department, semester_str))
        exams = cursor.fetchall()
        cursor.close()
        conn.close()
        if not exams:
            return f"No exams scheduled for {department} semester {semester}."
        response = f"📘 Exams for {department} Semester {semester}:\n"
        for e in exams:
            response += f"- {e['subject']} on {e['exam_date']} at {e['start_time']}\n"
        return response
    
    elif intent == "exam_date":
        # Extract date from message
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", question)
        if not date_match:
            return "Please provide a valid date in YYYY-MM-DD format."
        exam_date = date_match.group(1)
        cursor.execute("""
            SELECT exam_code, subject, semester, department, start_time, end_time
            FROM exams
            WHERE exam_date = %s
        """, (exam_date,))
        exams = cursor.fetchall()
        cursor.close()
        conn.close()
        if not exams:
            return f"No exams scheduled on {exam_date}."
        response = f"📅 Exams on {exam_date}:\n"
        for e in exams:
            response += f"- {e['subject']} ({e['department']} Sem {e['semester']}) from {e['start_time']} to {e['end_time']}\n"
        return response
    
    cursor.close()
    conn.close()
    return "I didn’t get that. Try asking about exams."
import re

def detect_intent(message):
    """
    Detects the user's intent based on the message text.

    Returns one of the following intents:
    - 'exam_list'       : List exams by department + semester
    - 'exam_date'       : List exams on a specific date
    - 'exam_time'       : Ask about exam timing
    - 'invigilator'     : Ask about invigilator
    - 'room'            : Ask about room/bench allocation
    - 'unknown'         : Default fallback
    """
    msg = message.lower()

    # 1️⃣ Department + semester queries
    if "what exams" in msg or "exam available" in msg or "available for me" in msg:
        return "exam_list"

    # 2️⃣ Date-based queries (YYYY-MM-DD or DD-MM-YYYY)
    date_match_iso = re.search(r"\b\d{4}-\d{2}-\d{2}\b", msg)
    date_match_eu = re.search(r"\b\d{2}-\d{2}-\d{4}\b", msg)
    if date_match_iso or date_match_eu:
        return "exam_date"

    # 3️⃣ Queries about exam time
    if "time" in msg or "timing" in msg or "when" in msg:
        return "exam_time"

    # 4️⃣ Queries about invigilator
    if "invigilator" in msg or "who supervises" in msg:
        return "invigilator"

    # 5️⃣ Queries about room/bench
    if "room" in msg or "bench" in msg or "allocated" in msg:
        return "room"

    # Default fallback
    return "unknown"

import re
def extract_details(message):
    msg = message.lower()
    department = None
    semester = None

    # Check for common department names
    for dept in ["cs", "phy", "chem", "tam", "eng", "math", "eco", "hist"]:
        if dept in msg:
            department = dept.upper()
            break

    # Check for semester
    sem_match = re.search(r"sem\s*(\d+)", msg)
    if sem_match:
        semester = sem_match.group(1)
    else:
        # Default to 6 if user didn't specify
        semester = '6'

    return department, semester, None

import speech_recognition as sr

def voice_to_text():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        audio = r.listen(source)
    return r.recognize_google(audio)
import pyttsx3

def speak(text):
    engine = pyttsx3.init()
    engine.say(text)
    engine.runAndWait()
@app.route('/chatbot', methods=['GET', 'POST'])
def chatbot():
    if request.method == 'GET':
        return render_template('chatbot.html')  # chatbot UI page

    user_text = request.form.get('message')
    if not user_text:
        return {"reply": "Please ask a question"}

    reply = chatbot_answer(user_text)
    
    # [WARNING] Remove server-side speech
    # speak(reply)   # [ERROR] Don't call pyttsx3 here

    return {"reply": reply}


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    next_page = request.args.get('next')

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('pass')
        next_page = request.form.get('next')

        if email == 'sabarilathapandi@gmail.com' and password == '2346':
            session['admin'] = True

            if next_page == 'add' or next_page == 'add_exam':
                return redirect(url_for('add_exam'))
            elif next_page == 'manage':
                return redirect(url_for('admin'))
            elif next_page == 'student' or next_page == 'add_student':
                session['student_admin'] = True
                return redirect(url_for('add_student'))
            elif next_page == 'add_department':
                return redirect(url_for('add_department'))
            elif next_page == 'add_staff':   #  NEW: Redirect to staff form
                return redirect(url_for('add_staff'))
            elif next_page == 'mark_absent_new':
                session['student_admin'] = True
                return redirect(url_for('mark_absent_new'))
            else:
                return redirect(url_for('index'))
        else:
            error = 'Invalid email or password.'

    return render_template('login.html', error=error, next=next_page)

def get_students_for_exam(cursor, exam_code):
    """
    Fetch students for an exam based on exam type (regular or arrear):
    
    FOR REGULAR EXAMS (is_arrear = 0):
    - Get regular students of the exam semester (not arrear students)
    
    FOR ARREAR EXAMS (is_arrear = 1):
    - Get only arrear students who have arrear_exam_code matching this exam
    
    Returns: List of student dictionaries with 'roll_no', 'name', 'department', 'semester'
    """
    # Get exam details including is_arrear flag
    cursor.execute("SELECT * FROM exams WHERE exam_code = %s", (exam_code,))
    exam = cursor.fetchone()
    if not exam:
        print(f"[DEBUG] Exam {exam_code} not found", flush=True)
        return []
    
    department = exam['department']
    exam_semester = str(exam['semester']).strip()
    is_arrear_exam = exam.get('is_arrear', 0)  # 0 = Regular, 1 = Arrear
    arrear_exam_code = exam_code.upper()
    
    # Normalize department name
    normalized_dept = normalize_department(department)
    
    print(f"[DEBUG] get_students_for_exam: exam_code={exam_code}, dept={department} (normalized: {normalized_dept}), sem={exam_semester}, is_arrear={is_arrear_exam}", flush=True)
    
    all_students = []
    
    if is_arrear_exam == 1:
        # ARREAR EXAM: Only get arrear students marked for this specific exam
        print(f"[DEBUG] ARREAR EXAM MODE: Fetching arrear students for {arrear_exam_code}", flush=True)
        
        if department == 'ALL':
            cursor.execute("""
                SELECT roll_no, name, department, semester 
                FROM students 
                WHERE is_arrear = 1 
                  AND arrear_exam_code IS NOT NULL
                  AND UPPER(arrear_exam_code) = UPPER(%s)
                ORDER BY department, roll_no
            """, (arrear_exam_code,))
        else:
            # Try multiple matching strategies for department
            cursor.execute("""
                SELECT roll_no, name, department, semester 
                FROM students 
                WHERE is_arrear = 1 
                  AND arrear_exam_code IS NOT NULL
                  AND UPPER(arrear_exam_code) = UPPER(%s)
                  AND (UPPER(department) = %s 
                       OR UPPER(department) LIKE CONCAT(%s, '%%')
                       OR department LIKE %s
                       OR UPPER(department) IN ('BOT', 'BOTANY', 'ZOOLOGY', 'ZOO', 'PHYSICS', 'PHY', 'CHEMISTRY', 'CHE', 'ENGLISH', 'ENG', 'TAMIL', 'TAM', 'HISTORY', 'HIS', 'MATHS', 'MATHEMATICS', 'GEOLOGY', 'GEO', 'ECONOMICS', 'ECO', 'CS', 'COMPUTER SCIENCE', 'BCA', 'B.COM', 'BCOM', 'B.COM', 'BBA'))
                ORDER BY roll_no
            """, (arrear_exam_code, normalized_dept.upper(), normalized_dept.upper(), f'{department}%'))
        
        arrear_students = cursor.fetchall()
        all_students.extend(arrear_students)
        print(f"[DEBUG] Arrear students for exam {arrear_exam_code}: {len(arrear_students)}", flush=True)
    
    else:
        # REGULAR EXAM: Only get regular students of this semester (not arrear)
        print(f"[DEBUG] REGULAR EXAM MODE: Fetching regular students for semester {exam_semester}, dept={normalized_dept}", flush=True)
        
        regular_students = []
        if department == 'ALL':
            # For ALL department, fetch all students with matching semester
            cursor.execute("""
                SELECT roll_no, name, department, semester 
                FROM students 
                WHERE CAST(semester AS CHAR) = %s
                  AND (is_arrear IS NULL OR is_arrear = 0)
                ORDER BY department, roll_no
            """, (exam_semester,))
            regular_students = cursor.fetchall()
        else:
            # For specific department - use flexible matching
            # First try exact normalized match
            cursor.execute("""
                SELECT roll_no, name, department, semester 
                FROM students 
                WHERE CAST(semester AS CHAR) = %s
                  AND (is_arrear IS NULL OR is_arrear = 0)
                  AND (UPPER(department) = %s 
                       OR UPPER(department) LIKE CONCAT(%s, '%%')
                       OR LOWER(department) LIKE LOWER(%s))
                ORDER BY roll_no
            """, (exam_semester, normalized_dept.upper(), normalized_dept.upper(), f'{department}%'))
            
            regular_students = cursor.fetchall()
            print(f"[DEBUG] Found {len(regular_students)} students with normalized match (dept={normalized_dept})", flush=True)
            
            # If no students found, try more flexible matching with all known variations
            if not regular_students:
                print(f"[DEBUG] No students found with normalized match. Trying flexible match for '{department}'", flush=True)
                # Build a list of possible department variations
                possible_depts = []
                for key in DEPARTMENT_NAME_TO_CODE:
                    if DEPARTMENT_NAME_TO_CODE[key] == normalized_dept:
                        possible_depts.append(key)
                
                if possible_depts:
                    placeholders = ','.join(['%s'] * len(possible_depts))
                    query = f"""
                        SELECT roll_no, name, department, semester 
                        FROM students 
                        WHERE CAST(semester AS CHAR) = %s
                          AND (is_arrear IS NULL OR is_arrear = 0)
                          AND (UPPER(department) IN ({placeholders}) OR LOWER(department) IN ({placeholders}))
                        ORDER BY roll_no
                    """
                    params = [exam_semester] + possible_depts + possible_depts
                    cursor.execute(query, params)
                    regular_students = cursor.fetchall()
                    print(f"[DEBUG] Found {len(regular_students)} students with flexible match. Tried: {possible_depts}", flush=True)
        
        all_students.extend(regular_students)
        print(f"[DEBUG] Regular students for {department} (normalized: {normalized_dept}) sem {exam_semester}: {len(regular_students)}", flush=True)
    
    print(f"[DEBUG] Total students for exam {exam_code}: {len(all_students)}", flush=True)
    return all_students

def _allocate_seating_background(exam_code):
    """
    Background worker thread for seating allocation.
    Runs allocate_seating_for_exam in a separate thread with error handling.
    """
    try:
        print(f"\n[OK] Background: Starting seating allocation for exam {exam_code}...")
        alloc_ok, alloc_msg = allocate_seating_for_exam(exam_code)
        if alloc_ok:
            print(f"[OK] Background: Seating allocation completed successfully!")
        else:
            print(f"[ERROR] Background: Seating allocation failed: {alloc_msg}")
    except Exception as e:
        print(f"[ERROR] Background: Exception during seating allocation: {str(e)}")
        import traceback
        traceback.print_exc()

def allocate_seating_for_exam(exam_code):
    """
    SEQUENTIAL SEATING ALLOCATION ALGORITHM:
    Fill halls sequentially - 12 students per position (LEFT, CENTER, RIGHT)
    - First 12 students → PHY1 LEFT
    - Next 12 students → PHY1 CENTER
    - Next 12 students → PHY1 RIGHT
    - Next 12 students → PHY2 LEFT
    - And so on for CHEM, ECO, etc. as needed
    
    Returns: tuple (success: bool, message: str or None).
    - success will be True if allocation completed or skipped (e.g. no students).
    - message will contain error details when success is False.
    """
    import sys
    import io
    # Handle UTF-8 encoding for Tamil characters in print statements
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    
    print(f"\n[DEBUG] ===== ALLOCATE SEATING CALLED FOR {exam_code} =====", flush=True)
    sys.stdout.flush()
    print(f"\n[DEBUG] allocate_seating_for_exam() called with exam_code={exam_code}", flush=True)
    sys.stdout.flush()
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        if not conn:
            msg = "Could not connect to database"
            print(f"[ERROR] {msg}", flush=True)
            return False, msg
            
        cursor = conn.cursor(dictionary=True)

        # 1️⃣ Fetch exam details
        cursor.execute("SELECT * FROM exams WHERE exam_code = %s", (exam_code,))
        exam = cursor.fetchone()
        if not exam:
            msg = f"Exam {exam_code} not found"
            print(f"[ERROR] {msg}", flush=True)
            return False, msg
        
        print(f"[DEBUG] Exam fetched: {exam_code}, Semester: {exam['semester']}, Department: {exam['department']}")

        # Extract exam details
        department = exam['department']
        exam_date = exam['exam_date']
        start_time = exam['start_time']
        end_time = exam['end_time']

        # 2️⃣ Get students for THIS exam - USE total_students from exam record
        total_students_limit = exam.get('total_students', None)
        exam_semester = str(exam['semester']).strip()  # Ensure semester is string and trimmed
        
        # Use helper function to fetch regular + arrear students
        all_students = get_students_for_exam(cursor, exam_code)
        
        if all_students:
            if department == 'ALL':
                print(f"[OK] Fetching ALL students (Semester {exam_semester}) for exam {exam_code} - including arrear students")
            else:
                print(f"[OK] Fetching {department} students (Semester {exam_semester}) for exam {exam_code} - including arrear students")
        
        all_students_original = all_students
        if not all_students:
            # no students currently registered for this exam; not a fatal error
            print(f"[INFO] No students found for {department} Semester {exam_semester} - will skip allocation for now")
            print(f"[DEBUG] Querying students with: department={department}, semester={exam_semester}")
            cursor.execute("SELECT DISTINCT semester FROM students ORDER BY semester")
            semesters = [row['semester'] for row in cursor.fetchall()]
            print(f"[DEBUG] Available semesters in DB: {semesters}")
            cursor.execute("SELECT DISTINCT department FROM students ORDER BY department")
            depts = [row['department'] for row in cursor.fetchall()]
            print(f"[DEBUG] Available departments in DB: {depts}")
            # success but nothing allocated
            return True, None

        print(f"[DEBUG] Found {len(all_students)} students for exam {exam_code}")

        # ALLOCATE ALL STUDENTS (regular + arrear)
        # Note: total_students field in exams table is informational only, 
        # we allocate all registered students including arrear
        students_for_exam = all_students
        
        student_count = len(students_for_exam)
        print(f"[OK] Will allocate {student_count} students for exam {exam_code} (including {len([s for s in students_for_exam if 'is_arrear' in str(s)])} arrear if any)")

        # 3️⃣ Get ALL available EXAM HALLS (PHY, CHEM, ECO, etc. that have benches configured)
        cursor.execute("""
            SELECT DISTINCT department
            FROM department_bench_info 
            ORDER BY department
        """)
        available_halls = [row['department'] for row in cursor.fetchall()]
        
        if not available_halls:
            msg = "No exam hall configurations found in department_bench_info table"
            print(f"[ERROR] {msg}")
            print(f"[INFO] Please configure bench info for at least one department (PHY, CHEM, CS, etc.) first")
            print(f"[DEBUG] Check department_bench_info table - it should have entries like:")
            print(f"[DEBUG]   - department='CS', block_number=1, class_number=1, bench_count=15")
            cursor.execute("SELECT COUNT(*) as count FROM department_bench_info")
            result = cursor.fetchone()
            print(f"[DEBUG] Total bench configurations in DB: {result['count'] if result else 0}")
            return False, msg
        
        try:
            print(f"[OK] Available halls for allocation: {', '.join(available_halls)}")
        except UnicodeEncodeError:
            # Windows console encoding issue with Tamil characters
            print(f"[OK] Available halls for allocation: {len(available_halls)} halls configured")
        
        # PRIORITY ALLOCATION: வா > BCOM > Other Departments
        # Reorder halls to prioritize வா and BCOM first
        priority_order = ['வா', 'VA', 'BCOM', 'B.COM']  # வா/VA and BCOM first
        
        # Sort available_halls by priority
        def get_hall_priority(hall):
            if hall in priority_order:
                return priority_order.index(hall)
            else:
                return len(priority_order)  # Other departments come last
        
        available_halls_sorted = sorted(available_halls, key=get_hall_priority)
        try:
            print(f"[OK] Halls sorted by priority: {available_halls_sorted}", flush=True)
        except UnicodeEncodeError:
            print(f"[OK] Halls sorted by priority: {len(available_halls_sorted)} halls", flush=True)

        # 4️⃣ Build room list from all available halls - PRIORITIZED ORDER
        rooms_available = []
        room_counter_per_hall = {}  # Track room counter per hall department
        
        try:
            print(f"[DEBUG] Building room list from halls: {available_halls_sorted}")
        except UnicodeEncodeError:
            print(f"[DEBUG] Building room list from halls")
        
        for hall_dept in available_halls_sorted:  # Use SORTED halls (வா first, then BCOM, then others)
            cursor.execute("""
                SELECT block_number, class_number, bench_count, total_capacity 
                FROM department_bench_info 
                WHERE department = %s
                ORDER BY block_number, class_number
            """, (hall_dept,))
            dept_classes = cursor.fetchall()
            
            # Determine number of classes per block for this department
            num_classes_per_block = 0
            if dept_classes:
                max_class = max(row['class_number'] for row in dept_classes)
                num_classes_per_block = max_class
            
            # Initialize room counter for this hall
            room_counter_per_hall[hall_dept] = 0
            
            for row in dept_classes:
                bench_count = row['bench_count']
                block_number = row['block_number']
                class_number = row['class_number']
                benches_per_col = bench_count // 3
                extra_benches = bench_count % 3
                
                col_benches = [
                    benches_per_col + (1 if i < extra_benches else 0) 
                    for i in range(3)
                ]
                
                # Generate room_id using formula: (block-1) * num_classes + class_number
                room_id = (block_number - 1) * num_classes_per_block + class_number
                room_name = f"{hall_dept}{room_id}"  # வா1, வா2, வா3, BCOM1, BCOM2, ..., BCOM8, etc.
                
                # Create benches for this room - organized by position
                seats_by_position = {'LEFT': [], 'CENTER': [], 'RIGHT': []}
                
                # Calculate column and position multipliers based on actual bench_count
                col_multiplier = bench_count // 5 * 15  # For 15 benches: 15, for 21 benches: 21, etc.
                pos_multiplier = bench_count // 5 * 5   # For 15 benches: 5, for 21 benches: 7, etc.
                
                for col_idx in range(3):
                    for bench in range(1, col_benches[col_idx] + 1):
                        for pos_idx, position in enumerate(['LEFT', 'CENTER', 'RIGHT']):
                            seat_num = (col_idx * col_multiplier) + (pos_idx * pos_multiplier) + bench
                            
                            seats_by_position[position].append({
                                'room': room_name,
                                'bench_no': bench,
                                'col': col_idx + 1,
                                'position': position,
                                'seat_num': seat_num,
                                'student': None,
                                'roll_no': None,
                                'department': hall_dept
                            })
                
                rooms_available.append({
                    'room_name': room_name,
                    'department': hall_dept,
                    'seats_by_position': seats_by_position,
                    'total_seats': sum(len(v) for v in seats_by_position.values())
                })
        
        total_available_seats = sum(r['total_seats'] for r in rooms_available)
        print(f"[OK] {len(rooms_available)} rooms available, {total_available_seats} total seats", flush=True)
        try:
            print(f"[DEBUG] Rooms created: {[r['room_name'] for r in rooms_available]}", flush=True)
        except UnicodeEncodeError:
            print(f"[DEBUG] Rooms created: {len(rooms_available)} rooms", flush=True)

        if total_available_seats < student_count:
            print(f"[WARNING] Insufficient seats: {total_available_seats} < {student_count}", flush=True)
        
        if len(rooms_available) == 0:
            msg = "CRITICAL: rooms_available is EMPTY! Cannot allocate students!"
            print(f"[ERROR] {msg}", flush=True)
            return False, msg

        # 5️⃣ Get available invigilators
        cursor.execute("""
            SELECT DISTINCT es.staff_id
            FROM exam_seating es
            JOIN exams e ON e.exam_code = es.exam_code
            WHERE e.exam_date = %s
              AND e.end_time > %s
              AND e.start_time < %s
        """, (exam_date, start_time, end_time))
        busy_staff_ids = {row['staff_id'] for row in cursor.fetchall()}

        if busy_staff_ids:
            placeholders = ",".join(["%s"] * len(busy_staff_ids))
            query = f"""
                SELECT staff_id, name, email
                FROM staff
                WHERE staff_id NOT IN ({placeholders})
                ORDER BY staff_id
            """
            cursor.execute(query, list(busy_staff_ids))
        else:
            cursor.execute("SELECT staff_id, name, email FROM staff ORDER BY staff_id")
        
        staff_list = cursor.fetchall()
        if not staff_list:
            msg = "No available invigilators found"
            print(f"[ERROR] {msg}")
            return False, msg

        print(f"[OK] Found {len(staff_list)} available invigilators")

        # 6️⃣ Clear old seating
        cursor.execute("DELETE FROM exam_seating WHERE exam_code = %s", (exam_code,))
        conn.commit()

        # 7️⃣ NEW ALLOCATION LOGIC: Exam-position-locked allocation
        # All students of same exam use same position across halls
        # Different exams can use different positions in same hall
        # Bench constraint: 1 student per exam per bench
        # HALL ALLOCATION: Any student (from any department) can sit in any available hall
        # Priority: வா halls → BCOM halls → Other halls
        
        print(f"\n[OK] Starting exam-position-locked allocation...")
        print(f"[OK] Exam Department: {department}")
        print(f"[OK] Students for this exam: {student_count} (from any/all departments)")
        print(f"[OK] Halls available (in priority order): {', '.join(available_halls_sorted)}")
        print(f"[OK] NOTE: Students will be seated in ANY hall with available space (not restricted to their department)")
        print(f"[OK] Constraint: All students of same exam locked to single position across halls")
        print(f"[OK] Constraint: One student per exam per bench")
        
        room_staff = {}
        staff_index = 0
        staff_assignments = {s['staff_id']: [] for s in staff_list}
        
        allocated_count = 0
        unallocated_students = []
        student_index = 0
        
        # Track occupied benches per room for this exam
        occupied_benches_by_room = {}  # {room: set of bench_nos}
        
        # Group rooms by hall department
        rooms_by_hall = {}
        for room in rooms_available:
            hall_dept = room['department']
            if hall_dept not in rooms_by_hall:
                rooms_by_hall[hall_dept] = []
            rooms_by_hall[hall_dept].append(room)
        
        print(f"[OK] Rooms grouped by hall:", flush=True)
        print(f"[DEBUG] rooms_by_hall keys: {list(rooms_by_hall.keys())}", flush=True)
        print(f"[DEBUG] available_halls from DB: {available_halls}", flush=True)
        print(f"[DEBUG] available_halls SORTED (வா/BCOM first): {available_halls_sorted}", flush=True)
        
        for hall, rooms in rooms_by_hall.items():
            total_seats = sum(r['total_seats'] for r in rooms)
            print(f"     {hall}: {len(rooms)} room(s), {total_seats} total seats", flush=True)
        
        # Pre-load occupied benches for this exam in each room
        for room_name in [r['room_name'] for rooms in rooms_by_hall.values() for r in rooms]:
            cursor.execute("""
                SELECT DISTINCT bench_no FROM exam_seating 
                WHERE room = %s AND exam_code = %s
            """, (room_name, exam_code))
            occupied_benches_by_room[room_name] = {row['bench_no'] for row in cursor.fetchall()}
        
        # Find which position this exam should use
        # Position fallback strategy (same for all exams):
        # 1. Try CENTER first
        # 2. If CENTER is full, try RIGHT
        # 3. If RIGHT is full, try LEFT
        
        positions = ['CENTER', 'RIGHT', 'LEFT']  # Fixed priority order for all exams
        assigned_position = None
        
        print(f"\n[DEBUG] Exam Code: {exam_code}")
        print(f"[DEBUG] Position priority: {positions} (CENTER → RIGHT → LEFT)")
        print(f"[DEBUG] Checking which position has available capacity...")
        
        print(f"[DEBUG] Exam date: {exam_date}", flush=True)
        print(f"[DEBUG] Exam start_time: {start_time}", flush=True)
        print(f"[DEBUG] Exam end_time: {end_time}", flush=True)
        
        # Check what exams are already scheduled on this date
        cursor.execute("""
            SELECT DISTINCT exam_code, exam_date, start_time, end_time FROM exams WHERE DATE(exam_date) = %s
        """, (exam_date,))
        existing_exams = cursor.fetchall()
        print(f"[DEBUG] Existing exams on {exam_date}: {[e['exam_code'] for e in existing_exams]}", flush=True)
        
        # Get positions already used by OTHER exams on this date (ANY time)
        cursor.execute("""
            SELECT DISTINCT es.position FROM exam_seating es
            JOIN exams e ON es.exam_code = e.exam_code
            WHERE DATE(e.exam_date) = %s AND e.exam_code != %s
        """, (exam_date, exam_code))
        used_positions = {row['position'] for row in cursor.fetchall()}
        print(f"[DEBUG] Positions already used by other exams on {exam_date}: {used_positions}", flush=True)
        
        for position in positions:
            if position not in used_positions:
                assigned_position = position
                print(f"[OK] Position {position} is available (not used by other exams) - Assigning", flush=True)
                break
        
        if assigned_position is None:
            print(f"[WARNING] All positions (LEFT, RIGHT, CENTER) are used on {exam_date}", flush=True)
            print(f"[INFO] Assigning to first position (LEFT) - students will overlap with other exams", flush=True)
            assigned_position = 'LEFT'
        
        # PRIORITY-BASED ALLOCATION: வா → B.COM → Others
        # Strategy:
        # 1. Fill ALL வா halls COMPLETELY in assigned position
        # 2. Then fill ALL B.COM halls COMPLETELY in assigned position
        # 3. Then fill other halls in assigned position
        # 4. Use fallback positions only when assigned position is exhausted everywhere
        
        print(f"\n[OK] PRIORITY-BASED ALLOCATION SYSTEM")
        print(f"[OK] Strategy: வா halls (complete) → B.COM halls (complete) → Others")
        print(f"[OK] Allocating {len(students_for_exam)} students to {assigned_position} position...\n")
        
        # Group halls by priority
        priority_halls = {'வா': [], 'B.COM': [], 'others': []}
        for hall in available_halls_sorted:
            if hall in ['வா', 'VA']:
                priority_halls['வா'].append(hall)
            elif hall in ['B.COM', 'BCOM']:
                priority_halls['B.COM'].append(hall)
            else:
                priority_halls['others'].append(hall)
        
        # Create ordered list: வா first, then B.COM, then others
        ordered_halls = priority_halls['வா'] + priority_halls['B.COM'] + priority_halls['others']
        
        print(f"[OK] Hall allocation order (PRIORITY):")
        print(f"     Priority 1 - வா halls: {priority_halls['வா']}")
        print(f"     Priority 2 - B.COM halls: {priority_halls['B.COM']}")
        print(f"     Priority 3 - Other halls: {priority_halls['others']}\n")
        
        # ROTATING POSITION ASSIGNMENT: Balance load across positions
        # Count total exams created to determine position rotation
        cursor.execute("SELECT COUNT(*) as total FROM exams")
        total_exams = cursor.fetchone()['total']
        
        # Position rotation: Exam 1 → CENTER (0), Exam 2 → RIGHT (1), Exam 3 → LEFT (2), Exam 4 → CENTER (0)...
        positions_sequence = ['CENTER', 'RIGHT', 'LEFT']
        position_index = total_exams % 3  # Rotate through positions
        assigned_position = positions_sequence[position_index]
        
        print(f"[OK] ROTATING POSITION ASSIGNMENT")
        print(f"[OK] Total exams in system: {total_exams}")
        print(f"[OK] Rotation index: {total_exams} % 3 = {position_index}")
        print(f"[OK] Assigning position: {assigned_position}")
        print(f"[OK] Position sequence: Exam 1→CENTER, Exam 2→RIGHT, Exam 3→LEFT, Exam 4→CENTER...\n")
        
        # Try assigned position first, then fallback to others if no capacity
        positions_to_try = [assigned_position]
        for pos in ['CENTER', 'RIGHT', 'LEFT']:
            if pos != assigned_position:
                positions_to_try.append(pos)
        
        print(f"[OK] Position priority for allocation: {positions_to_try}\n")
        
        exam_position = None  # Track which position is actually used for this exam
        
        # CHANGE: Try to distribute students across ALL available positions
        # Loop through halls first, and within each hall, try all positions
        for hall_dept in ordered_halls:
            if student_index >= len(students_for_exam):
                break  # All students allocated
            
            # For each hall, try to fill all positions with students
            for try_position in positions_to_try:
                if student_index >= len(students_for_exam):
                    break  # All students allocated
                
                if exam_position is None:
                    exam_position = try_position  # Lock first position used
                print(f"[OK] Using {try_position} position for exam {exam_code}\n")
                
                hall_rooms = rooms_by_hall.get(hall_dept, [])
                
                print(f"     [OK] Filling {try_position} position in {hall_dept} (all rooms sequentially)...")
                
                # Fill ALL rooms of this hall completely before moving to next hall
                position_filled = False
                for room in hall_rooms:
                    if student_index >= len(students_for_exam):
                        break  # All students allocated
                    
                    room_name = room['room_name']
                    available_seats = room['seats_by_position'][try_position]
                    
                    if not available_seats:
                        continue  # No seats in this position
                    
                    # Check if position already has allocations from another exam
                    cursor.execute("""
                        SELECT COUNT(*) as count FROM exam_seating 
                        WHERE room = %s AND position = %s AND exam_code != %s
                    """, (room_name, try_position, exam_code))
                    existing = cursor.fetchone()
                    if existing and existing['count'] > 0:
                        existing_count = existing['count']
                        remaining_seats = len(available_seats) - existing_count
                        if remaining_seats <= 0:
                            continue  # No free seats in this position
                        available_seats = available_seats[existing_count:]
                        if not available_seats:
                            continue
                    
                    # Get occupied benches for this room
                    occupied_benches = occupied_benches_by_room[room_name]
                    
                    # Get or assign invigilator for this room
                    if room_name not in room_staff:
                        room_staff[room_name] = staff_list[staff_index]['staff_id']
                        staff_index = (staff_index + 1) % len(staff_list)
                        invig_name = staff_list[(staff_index - 1) % len(staff_list)]['name']
                        print(f"          [OK] Assigned invigilator {invig_name} to {room_name}")
                    
                    invigilator_id = room_staff[room_name]
                    
                    # Filter seats: exclude benches already occupied by this exam
                    free_seats = [seat for seat in available_seats if seat['bench_no'] not in occupied_benches]
                    
                    if not free_seats:
                        print(f"          [INFO] {room_name} {try_position}: No free benches available")
                        continue
                    
                    # Fill available seats - FILL COMPLETELY (or until no students left)
                    seats_to_fill = min(len(free_seats), len(students_for_exam) - student_index)
                    allocated_in_room = 0
                    
                    if seats_to_fill == 0:
                        continue
                    
                    print(f"     [DEBUG] {room_name} {try_position}: Allocating {seats_to_fill} students ({len(free_seats)} free seats available)")
                    
                    for seat_idx in range(seats_to_fill):
                        if student_index >= len(students_for_exam):
                            break
                        
                        seat = free_seats[seat_idx]
                        student = students_for_exam[student_index]
                        
                        # Check double booking: student cannot have two exams at same start_time on same date
                        # Only check within the same semester to allow different semesters to have exams at same time
                        cursor.execute("""
                            SELECT COUNT(*) as count
                            FROM exam_seating es
                            JOIN exams e ON e.exam_code = es.exam_code
                            WHERE es.roll_no = %s
                              AND e.exam_date = %s
                              AND e.start_time = %s
                              AND CAST(e.semester AS CHAR) = %s
                        """, (student['roll_no'], exam_date, exam['start_time'], str(exam['semester']).strip()))
                        
                        double_booking_check = cursor.fetchone()
                        if double_booking_check and double_booking_check['count'] > 0:
                            print(f"          [WARNING] {student['roll_no']} ({department}) has double booking at same time - skipping")
                            student_index += 1
                            continue
                        
                        # Allocate student to seat
                        try:
                            # Check if this student is marked as absent in student_absent table
                            cursor.execute("""
                                SELECT absence_reason FROM student_absent 
                                WHERE roll_no = %s AND department = %s
                                LIMIT 1
                            """, (student['roll_no'], student['department']))
                            absent_record = cursor.fetchone()
                            is_absent_flag = 1 if absent_record else 0
                            absence_reason = absent_record['absence_reason'] if absent_record else None
                            
                            # Get invigilator name
                            invigilator_name = next((s['name'] for s in staff_list if s['staff_id'] == invigilator_id), 'Unknown')
                            
                            cursor.execute("""
                                INSERT INTO exam_seating
                                (exam_code, roll_no, room, class_no, col, position, bench_no, seat_num, staff_id, invigilator, exam_date, exam_session, is_absent, absence_reason, marked_absent_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                            """, (
                                exam_code, student['roll_no'], room_name, 1,
                                seat['col'], seat['position'], seat['bench_no'], seat['seat_num'], invigilator_id,
                                invigilator_name,
                                exam_date, exam['exam_session'], is_absent_flag, absence_reason
                            ))
                        except Exception as e:
                            print(f"          [ERROR] Failed to allocate {student['roll_no']} to {room_name}: {e}")
                            student_index += 1
                            continue
                        
                        allocated_count += 1
                        allocated_in_room += 1
                        occupied_benches.add(seat['bench_no'])
                        
                        staff_assignments[invigilator_id].append({
                            'student': student['name'],
                            'roll': student['roll_no'],
                            'dept': department,
                            'room': room_name,
                            'column': seat['col'],
                            'position': seat['position'],
                            'bench': seat['bench_no'],
                            'seat_num': seat['seat_num']
                        })
                        
                        student_index += 1
                    
                    if allocated_in_room > 0:
                        print(f"          [OK] {room_name} {try_position}: Allocated {allocated_in_room} students")
                        position_filled = True
                
                if position_filled:
                    print(f"     [OK] Hall {hall_dept} {try_position} position: FILLED")
        
        # Check if all students allocated
        if student_index < len(students_for_exam):
            remaining = len(students_for_exam) - student_index
            print(f"\n[WARNING] {remaining} students could NOT be allocated")
            print(f"[INFO] Total students available: {len(students_for_exam)}")
            print(f"[INFO] Successfully allocated: {allocated_count}")
            for i in range(student_index, len(students_for_exam)):
                unallocated_students.append(students_for_exam[i]['roll_no'])
        else:
            primary = assigned_position
            fallback = " → ".join([p for p in positions_to_try if p != assigned_position][:2])
            print(f"\n[OK] All {len(students_for_exam)} students allocated ({primary} position, no fallback needed)!")

        conn.commit()


        # 8️⃣ Email invigilators
        for staff in staff_list:
            assignments = staff_assignments[staff['staff_id']]
            if not assignments:
                continue

            text = ""
            current_position = None
            current_dept = None
            
            for a in assignments:
                # Group by position and department for clarity
                if current_position != a['position'] or current_dept != a['dept']:
                    if current_position is not None:
                        text += "\n"
                    text += f"  [{a['dept']} - {a['position']}]\n"
                    current_position = a['position']
                    current_dept = a['dept']
                
                text += f"    • {a['student']} ({a['roll']}) → {a['room']}, Col{a['column']}, Bench{a['bench']}, Seat#{a['seat_num']}\n"

            try:
                msg = Message(
                    subject=f"Invigilation Duty – {exam['subject']}",
                    sender=app.config['MAIL_USERNAME'],
                    recipients=[staff['email']]
                )
                msg.body = f"""Dear {staff['name']},

You are assigned as invigilator for:

📘 Subject: {exam['subject']}
📅 Date: {exam_date}
⏰ Time: {start_time} – {end_time}

Your allocations ({len(assignments)} students):
{text}

Please report on time.

– Exam Committee
"""
                mail.send(msg)
                print(f"[OK] Email sent to {staff['email']}")
            except Exception as e:
                print(f"[WARNING] Email error: {e}")

        print(f"\n[OK] Seating allocated successfully!")
        print(f"   • Total students: {student_count}")
        print(f"   • Allocated (with students): {allocated_count}")
        if unallocated_students:
            print(f"   • Could not allocate: {len(unallocated_students)} students")
            print(f"     Roll numbers: {', '.join(unallocated_students[:10])}")
            if len(unallocated_students) > 10:
                print(f"     ... and {len(unallocated_students) - 10} more")
        
        return True, None  # Success


    except Exception as e:
        err_str = str(e)
        print(f"[ERROR] Allocation error: {err_str}", flush=True)
        import traceback
        traceback.print_exc()
        import sys
        sys.stdout.flush()
        return False, err_str  # Failed
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def allocate_seating_for_all_upcoming_exams():
    """Refresh seating allocations for all exams occurring today or later.
    Useful to call after students/bench configuration changes so new seats are
    automatically assigned without manual intervention.
    """
    conn = get_db_connection()
    if not conn:
        print("[ERROR] Could not connect to database when refreshing all exams")
        return
    cursor = conn.cursor()
    exam_codes = []
    try:
        cursor.execute("SELECT exam_code FROM exams WHERE exam_date >= CURDATE()")
        exam_codes = [row[0] for row in cursor.fetchall()]
    except Exception as e:
        print(f"[ERROR] Failed to fetch upcoming exams: {e}")
    finally:
        cursor.close()
        conn.close()

    for code in exam_codes:
        try:
            print(f"[INFO] Re‑allocating seating for exam {code}")
            ok, msg = allocate_seating_for_exam(code)
            if not ok:
                print(f"[WARNING] Seating allocation for {code} failed: {msg}")
        except Exception as e:
            print(f"[WARNING] Error reallocating seating for {code}: {e}")

@app.route('/staff-view', methods=['GET', 'POST'])
def staff_view():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Staff dropdown
    cursor.execute("SELECT * FROM staff ORDER BY department, name")
    staff_list = cursor.fetchall()

    allocations = []
    selected_staff_id = None

    if request.method == 'POST':
        staff_id = request.form.get('staff_id')
        selected_staff_id = staff_id

        if staff_id:
            cursor.execute("""
                SELECT 
                    e.exam_code,
                    e.subject,
                    e.semester,
                    e.department,
                    es.room,
                    es.class_no,
                    MIN(s.roll_no) AS start_roll,
                    MAX(s.roll_no) AS end_roll,
                    COUNT(s.roll_no) AS student_count
                FROM exam_seating es
                JOIN exams e ON e.exam_code = es.exam_code
                JOIN students s ON s.roll_no = es.roll_no
                WHERE es.staff_id = %s
                GROUP BY 
                    e.exam_code, e.subject, e.semester, e.department,
                    es.room, es.class_no
                ORDER BY e.exam_date, es.room
            """, (staff_id,))

            allocations = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'staff_view.html',
        staff_list=staff_list,
        allocations=allocations,
        selected_staff_id=selected_staff_id
    )

def notify_staff_by_exam(exam_code, mode='new'):
    """
    Notify staff about their invigilation allocations for a specific exam.
    Mode can be 'new', 'update', 'cancel'.
    """
    conn = get_db_connection()
    if not conn:
        print("Failed to connect to database for staff notifications")
        return
    cursor = conn.cursor(dictionary=True)

    # Fetch all seating allocations for this exam
    cursor.execute("""
        SELECT es.room, es.class_no, es.bench_no, st.name AS staff_name, st.email AS staff_email,
               e.subject, e.exam_date, e.start_time
        FROM exam_seating es
        JOIN staff st ON st.staff_id = es.staff_id
        JOIN exams e ON e.exam_code = es.exam_code
        WHERE es.exam_code = %s
        ORDER BY st.name, es.room, es.bench_no
    """, (exam_code,))

    allocations = cursor.fetchall()

    if not allocations and mode != 'cancel':
        print("No allocations found for staff notifications")
        cursor.close()
        conn.close()
        return

    staff_allocations = {}
    for alloc in allocations:
        staff_email = alloc['staff_email']
        if staff_email not in staff_allocations:
            staff_allocations[staff_email] = {
                'name': alloc['staff_name'],
                'allocations': [],
                'subject': alloc['subject'],
                'exam_date': alloc['exam_date'],
                'start_time': alloc['start_time']
            }
        staff_allocations[staff_email]['allocations'].append(
            f"Room {alloc['room']}, Class {alloc['class_no']}, Bench {alloc['bench_no']}"
        )

    for staff_email, info in staff_allocations.items():
        if mode == 'new':
            subject_line = f"Invigilation Assignment: {info['subject']}"
            alloc_text = "\n".join(info['allocations'])
            body = f"""Dear {info['name']},

You have been assigned to invigilate the following exam:

Subject: {info['subject']}
Date: {info['exam_date']}
Start Time: {info['start_time']}

Your allocated rooms/benches are:
{alloc_text}

Please check the portal for more details.

- Exam Committee
"""
        elif mode == 'update':
            subject_line = f"Updated Invigilation Assignment: {info['subject']}"
            alloc_text = "\n".join(info['allocations'])
            body = f"""Dear {info['name']},

Your invigilation assignment has been updated for the following exam:

Subject: {info['subject']}
Date: {info['exam_date']}
Start Time: {info['start_time']}

Your new room/bench allocations are:
{alloc_text}

Please verify the changes on the portal.

- Exam Committee
"""
        elif mode == 'cancel':
            subject_line = f"Cancelled Invigilation Assignment: {info['subject']}"
            body = f"""Dear {info['name']},

The invigilation assignment for the exam "{info['subject']}" scheduled on {info['exam_date']} has been cancelled.

- Exam Committee
"""

        try:
            msg = Message(subject_line, sender=app.config['MAIL_USERNAME'], recipients=[staff_email])
            msg.body = body
            mail.send(msg)
            print(f"[OK] Email sent to staff: {staff_email}")
        except Exception as e:
            print(f"[ERROR] Error sending to {staff_email}: {e}")

    cursor.close()
    conn.close()

@app.route('/diagnostic')
def diagnostic():
    """Diagnostic endpoint to check database configuration and seating setup"""
    if not session.get('admin'):
        return redirect(url_for('login'))
    
    output = []
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Cannot connect to database'}), 500
    
    try:
        cursor = conn.cursor(dictionary=True)
        
        # Check exams
        cursor.execute("SELECT COUNT(*) as count FROM exams")
        exam_count = cursor.fetchone()['count']
        output.append(f"📋 Exams: {exam_count} record(s)")
        
        # Check students
        cursor.execute("SELECT COUNT(*) as count FROM students")
        student_count = cursor.fetchone()['count']
        output.append(f"👥 Students: {student_count} record(s)")
        
        # Check department_bench_info (halls)
        cursor.execute("SELECT COUNT(*) as count FROM department_bench_info")
        halls_count = cursor.fetchone()['count']
        output.append(f"🏛️  Exam Halls Configured: {halls_count} record(s)")
        
        if halls_count > 0:
            cursor.execute("""
                SELECT DISTINCT department
                FROM department_bench_info
                ORDER BY department
            """)
            halls = [row['department'] for row in cursor.fetchall()]
            output.append(f"   Halls: {', '.join(halls)}")
        
        # Check exam_seating allocations
        cursor.execute("SELECT COUNT(*) as count FROM exam_seating")
        seating_count = cursor.fetchone()['count']
        output.append(f"💺 Seating Allocations: {seating_count} seat(s) allocated")
        
        # Check for recent exams
        cursor.execute("""
            SELECT exam_code, subject, department, semester, exam_date
            FROM exams
            ORDER BY exam_date DESC
            LIMIT 5
        """)
        recent_exams = cursor.fetchall()
        if recent_exams:
            output.append(f"\n📚 Recent Exams (Last 5):")
            for exam in recent_exams:
                cursor.execute("""
                    SELECT COUNT(*) as count FROM exam_seating WHERE exam_code = %s
                """, (exam['exam_code'],))
                seat_count = cursor.fetchone()['count']
                output.append(f"   {exam['exam_code']}: {exam['subject']} ({exam['department']} Sem {exam['semester']}) - {seat_count} students seated")
        
        # Check student count by department and semester
        output.append(f"\n📊 Students by Department & Semester:")
        cursor.execute("""
            SELECT department, semester, COUNT(*) as count
            FROM students
            WHERE is_arrear = 0 OR is_arrear IS NULL
            GROUP BY department, semester
            ORDER BY department, semester
        """)
        dept_sem_data = cursor.fetchall()
        if dept_sem_data:
            for row in dept_sem_data[:20]:  # Limit output
                output.append(f"   {row['department']} Sem {row['semester']}: {row['count']} students")
        else:
            output.append(f"   No student data found")
        
        # Check staff
        cursor.execute("SELECT COUNT(*) as count FROM staff")
        staff_count = cursor.fetchone()['count']
        output.append(f"\n👔 Staff/Invigilators: {staff_count} record(s)")
        
        output_html = "<pre style='font-family: monospace; white-space: pre-wrap;'>" + "\n".join(output) + "</pre>"
        return output_html
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/setup_default_halls', methods=['POST'])
def setup_default_halls():
    """Setup default exam halls if they don't exist"""
    if not session.get('admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Cannot connect to database'}), 500
    
    cursor = conn.cursor()
    try:
        # Define default halls with bench configurations
        default_halls = [
            ('வா', 1, 1, 16, 48),
            ('வா', 1, 2, 16, 48),
            ('வா', 1, 3, 16, 48),
            ('B.COM', 1, 1, 16, 48),
            ('B.COM', 1, 2, 16, 48),
            ('B.COM', 1, 3, 16, 48),
            ('B.COM', 1, 4, 16, 48),
            ('B.COM', 1, 5, 16, 48),
            ('B.COM', 1, 6, 16, 48),
            ('B.COM', 1, 7, 16, 48),
            ('B.COM', 1, 8, 16, 48),
            ('CS', 1, 1, 15, 45),
            ('CS', 1, 2, 15, 45),
            ('CS', 1, 3, 15, 45),
            ('PHY', 1, 1, 15, 45),
            ('CHEM', 1, 1, 15, 45),
            ('BOT', 1, 1, 15, 45),
            ('ZOO', 1, 1, 15, 45),
            ('MATHS', 1, 1, 15, 45),
        ]
        
        added = 0
        skipped = 0
        
        for dept, block, class_num, bench_count, capacity in default_halls:
            try:
                cursor.execute("""
                    INSERT INTO department_bench_info (department, block_number, class_number, bench_count, total_capacity)
                    VALUES (%s, %s, %s, %s, %s)
                """, (dept, block, class_num, bench_count, capacity))
                added += 1
            except Exception as e:
                if "1062" in str(e):  # Duplicate key
                    skipped += 1
                else:
                    raise
        
        conn.commit()
        return jsonify({
            'success': True,
            'message': f'Setup complete: Added {added} hall configuration(s), Skipped {skipped} (already exist)'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/fix_db')
def fix_db():
    """Admin route to update database schema - add missing columns and rename 'column' to 'col'"""
    conn = get_db_connection()
    if not conn:
        return "[ERROR] Failed to connect to database"
    
    cursor = conn.cursor()
    try:
        # Fix exams table
        alter_statements = [
            "ALTER TABLE exams ADD COLUMN IF NOT EXISTS college_code VARCHAR(10)",
            "ALTER TABLE exams ADD COLUMN IF NOT EXISTS department_code VARCHAR(10)",
            "ALTER TABLE exams ADD COLUMN IF NOT EXISTS exam_session VARCHAR(20)",
            "ALTER TABLE exams ADD COLUMN IF NOT EXISTS register_range VARCHAR(50)",
            "ALTER TABLE exams ADD COLUMN IF NOT EXISTS is_arrear TINYINT(1) DEFAULT 0"
        ]
        
        for alter_stmt in alter_statements:
            try:
                cursor.execute(alter_stmt)
                print(f"[OK] Executed: {alter_stmt}")
            except Error as e:
                if "1060" in str(e):  # Column already exists
                    print(f"ℹ️ Column already exists: {alter_stmt}")
                else:
                    print(f"[WARNING] Error: {e}")
        
        # Fix exam_seating table - rename 'column' to 'col' if it exists, add new columns
        try:
            cursor.execute("ALTER TABLE exam_seating CHANGE COLUMN `column` col INT")
            print(f"[OK] Renamed 'column' to 'col' in exam_seating table")
        except Error as e:
            if "1054" in str(e):  # Column doesn't exist
                print(f"ℹ️ Column 'column' doesn't exist (already renamed or new table)")
            else:
                print(f"ℹ️ Column rename info: {e}")
        
        # Add exam_date and exam_session columns if missing
        try:
            cursor.execute("ALTER TABLE exam_seating ADD COLUMN IF NOT EXISTS exam_date DATE")
            print(f"[OK] Added exam_date column to exam_seating table")
        except Error as e:
            print(f"ℹ️ exam_date column: {e}")
        
        try:
            cursor.execute("ALTER TABLE exam_seating ADD COLUMN IF NOT EXISTS exam_session VARCHAR(20)")
            print(f"[OK] Added exam_session column to exam_seating table")
        except Error as e:
            print(f"ℹ️ exam_session column: {e}")
        
        conn.commit()
        cursor.close()
        conn.close()
        return "[OK] Database schema updated successfully!"
    
    except Error as e:
        return f"[ERROR] Error updating database: {str(e)}"

def determine_exam_session(start_time):
    """
    Auto-determine exam session from start time:
    - 10:00 AM to 1:00 PM = FN (Forenoon)
    - 2:00 PM to 5:00 PM = AN (Afternoon)
    - Otherwise = NONE
    """
    try:
        # Parse start time (format: "10.00 AM" or "10.00 PM")
        parts = start_time.strip().split()
        time_part = parts[0]
        period = parts[1].upper() if len(parts) > 1 else ''
        
        time_components = time_part.split('.')
        hour = int(time_components[0])
        minute = int(time_components[1]) if len(time_components) > 1 else 0
        
        # Convert to 24-hour format
        if period == 'PM' and hour != 12:
            hour += 12
        elif period == 'AM' and hour == 12:
            hour = 0
        
        # Determine session
        if (hour == 10 and minute >= 0) or (hour == 11) or (hour == 12 and minute < 60):
            return 'FN'  # 10:00 AM to 1:00 PM
        elif (hour == 14 and minute >= 0) or (hour == 15) or (hour == 16) or (hour == 17 and minute <= 0):
            return 'AN'  # 2:00 PM to 5:00 PM
        else:
            return 'NONE'
    except Exception as e:
        print(f"Error determining exam session: {e}")
        return 'NONE'

def get_register_range(department, semester):
    """
    Auto-fetch register range from students table
    Returns: "23bce1223-23bce1267" or None
    If department = ALL, gets first and last from all departments
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        semester = str(semester).strip()  # Ensure semester is string and trimmed
        
        # Normalize department
        normalized_dept = normalize_department(department)
        
        if normalized_dept == 'ALL':
            # Get all students across all departments for this semester
            cursor.execute('''
                SELECT roll_no FROM students 
                WHERE CAST(semester AS CHAR) = %s
                AND (is_arrear IS NULL OR is_arrear = 0)
                ORDER BY roll_no ASC
            ''', (semester,))
            print(f"[OK] Fetching ALL students for Semester {semester}")
        else:
            # Build flexible query for department matching
            cursor.execute('''
                SELECT roll_no FROM students 
                WHERE (UPPER(department) = %s OR LOWER(department) LIKE LOWER(%s))
                AND CAST(semester AS CHAR) = %s
                AND (is_arrear IS NULL OR is_arrear = 0)
                ORDER BY roll_no ASC
            ''', (normalized_dept, f'{department}%', semester))
            print(f"[OK] Fetching {normalized_dept} students for Semester {semester}")
        
        students = cursor.fetchall()
        cursor.close()
        conn.close()
        
        if not students:
            print(f"No students found for {department}, Semester {semester}")
            return None
        
        register_start = students[0]['roll_no']
        register_end = students[-1]['roll_no']
        register_range = f"{register_start}-{register_end}"
        
        print(f"[OK] Register Range: {register_range}")
        return register_range
    
    except Exception as e:
        print(f"Error fetching register range: {e}")
        return None

@app.route('/add', methods=['GET', 'POST'])
def add_exam():
    if not session.get('admin'):
        return redirect(url_for('login', next='add'))
    if request.method == 'POST':
        exam_code = request.form['exam_code'].upper()
        subject = request.form['subject'].upper()
        semester = str(request.form['semester']).strip()  # Ensure semester is string and trimmed
        department = request.form['department'].upper()
        
        # Normalize department name
        normalized_dept = normalize_department(department)
        print(f"[DEBUG] add_exam: dept_input='{department}' -> normalized='{normalized_dept}'")
        
        exam_date_input = request.form['exam_date']
        exam_date = datetime.strptime(exam_date_input, '%d.%m.%Y').strftime('%Y-%m-%d')
        start_time = request.form['start_time']
        end_time = request.form['end_time']
        total_students = int(request.form['total_students'])
        is_arrear = int(request.form.get('is_arrear', '0'))  # Convert to integer: 0 = Regular exam, 1 = Arrear exam
        
        #  STATIC: College Code
        college_code = 'AU01'
        print(f"[OK] College Code: {college_code}")
        
        # AUTO-POPULATE: Department Code
        department_code = DEPARTMENT_CODES.get(normalized_dept, '')
        print(f"[OK] Auto-set Department Code: {normalized_dept} -> {department_code}")
        
        # AUTO-POPULATE: Exam Session (FN/AN based on time)
        exam_session = determine_exam_session(start_time)
        print(f"[OK] Auto-set Exam Session: {start_time} -> {exam_session}")
        
        #  VERIFY: Check if students exist BEFORE inserting exam
        conn_check = get_db_connection()
        if conn_check:
            cursor_check = conn_check.cursor(dictionary=True)
            
            if is_arrear == 1:
                # ARREAR EXAM: Check for arrear students
                print(f"[INFO] Checking for ARREAR students for exam code: {exam_code}")
                if normalized_dept == 'ALL':
                    cursor_check.execute("""
                        SELECT COUNT(*) as count FROM students 
                        WHERE is_arrear = 1 AND arrear_exam_code IS NOT NULL AND UPPER(arrear_exam_code) = UPPER(%s)
                    """, (exam_code,))
                else:
                    # Check with flexible department matching
                    cursor_check.execute("""
                        SELECT COUNT(*) as count FROM students 
                        WHERE is_arrear = 1 
                          AND arrear_exam_code IS NOT NULL 
                          AND UPPER(arrear_exam_code) = UPPER(%s)
                          AND (UPPER(department) = %s OR LOWER(department) LIKE LOWER(%s))
                    """, (exam_code, normalized_dept, f'{department}%'))
            else:
                # REGULAR EXAM: Check for regular students in semester
                print(f"[INFO] Checking for REGULAR students for {normalized_dept}, Semester {semester}")
                if normalized_dept == 'ALL':
                    cursor_check.execute("""
                        SELECT COUNT(*) as count FROM students WHERE CAST(semester AS CHAR) = %s AND (is_arrear IS NULL OR is_arrear = 0)
                    """, (semester,))
                else:
                    cursor_check.execute("""
                        SELECT COUNT(*) as count FROM students 
                        WHERE (UPPER(department) = %s OR LOWER(department) LIKE LOWER(%s))
                          AND CAST(semester AS CHAR) = %s
                          AND (is_arrear IS NULL OR is_arrear = 0)
                    """, (normalized_dept, f'{department}%', semester))
            
            result = cursor_check.fetchone()
            student_count_check = result['count'] if result else 0
            cursor_check.close()
            conn_check.close()
            
            if student_count_check == 0:
                if is_arrear == 1:
                    flash(f"[ERROR] No arrear students found for {normalized_dept} exam code {exam_code}. Check is_arrear=1 and arrear_exam_code in students table.")
                else:
                    flash(f"[ERROR] No students found for {normalized_dept}, Semester {semester}. Cannot add exam without students.")
                return redirect(url_for('add_exam'))
            
            if is_arrear == 1:
                print(f"[OK] Found {student_count_check} ARREAR students for {normalized_dept}, exam code {exam_code}")
            else:
                print(f"[OK] Found {student_count_check} regular students for {normalized_dept}, Semester {semester}")
        
        #  AUTO-POPULATE: Register Range from students table
        register_range = get_register_range(normalized_dept, semester)
        if not register_range:
            flash(f"[ERROR] No students found for {normalized_dept}, Semester {semester}")
            return redirect(url_for('add_exam'))

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Ensure required columns exist in exams table
            try:
                cursor.execute("ALTER TABLE exams ADD COLUMN IF NOT EXISTS college_code VARCHAR(10)")
                cursor.execute("ALTER TABLE exams ADD COLUMN IF NOT EXISTS department_code VARCHAR(10)")
                cursor.execute("ALTER TABLE exams ADD COLUMN IF NOT EXISTS exam_session VARCHAR(20)")
                cursor.execute("ALTER TABLE exams ADD COLUMN IF NOT EXISTS register_range VARCHAR(50)")
                cursor.execute("ALTER TABLE exams ADD COLUMN IF NOT EXISTS is_arrear TINYINT(1) DEFAULT 0")
                conn.commit()
            except Exception as col_err:
                print(f"[WARNING] Error adding columns: {col_err}")
            
            cursor.execute('''
                INSERT INTO exams (exam_code, subject, semester, department, exam_date, start_time, end_time, total_students, college_code, department_code, exam_session, register_range, is_arrear)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (exam_code, subject, semester, department, exam_date, start_time, end_time, total_students, college_code, department_code, exam_session, register_range, is_arrear))
            conn.commit()
            cursor.close()
            conn.close()

            # Notify students
            notify_students_by_exam(exam_code, mode='new')

            # AUTOMATIC SEATING ALLOCATION (in background thread)
            # Start allocation in background so response returns immediately
            allocation_thread = threading.Thread(
                target=_allocate_seating_background,
                args=(exam_code,),
                daemon=True
            )
            allocation_thread.start()
            
            flash(f"[OK] Exam added! College: {college_code} | Dept Code: {department_code} | Session: {exam_session} | Range: {register_range} | Seating allocation in progress...")
            return redirect(url_for('add_exam'))

        except mysql.connector.IntegrityError as ie:
            if "1062" in str(ie):
                flash(f"[ERROR] Exam code {exam_code} already exists!")
                return redirect(url_for('add_exam'))
            else:
                flash(f"[ERROR] DB Integrity error: {str(ie)}")
                return redirect(url_for('add_exam'))

        except Error as e:
            flash(f"[ERROR] General DB error: {str(e)}")
            return redirect(url_for('add_exam'))

    return render_template('add.html')

def link_callback(uri, rel):
    if uri.startswith('http://') or uri.startswith('https://'):
        return uri
    if uri.startswith('/'):
        path = os.path.join(app.root_path, uri[1:])
    else:
        path = os.path.join(app.root_path, uri)
    if os.path.exists(path):
        return path
    print(f"link_callback: URI {uri} resolved to {path}, exists={os.path.exists(path)}")
    return path

@app.route('/test_qr')
def test_qr():
    qr_data = "Test QR Code"
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_io = BytesIO()
    qr_img.save(qr_io, format="PNG")
    qr_b64 = base64.b64encode(qr_io.getvalue()).decode('utf-8')
    return f'<img src="data:image/png;base64,{qr_b64}" />'
@app.route("/get_hall_ticket", methods=["GET", "POST"])
def get_hall_ticket():
    if request.method == "POST":
        email = request.form.get("email")
        roll_no = request.form.get("roll_no")
        semester = request.form.get("semester")
        
        if not semester:
            return "[ERROR] Please provide semester.", 400

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Determine which search method to use
        student = None
        
        if email:
            # Method 1: Search by email
            cursor.execute("SELECT * FROM students WHERE email = %s", (email,))
            student = cursor.fetchone()
            if not student:
                cursor.close()
                conn.close()
                return "[ERROR] No student found with that email.", 404
        
        elif roll_no:
            # Method 2: Search by roll number
            cursor.execute("SELECT * FROM students WHERE roll_no = %s", (roll_no,))
            student = cursor.fetchone()
            if not student:
                cursor.close()
                conn.close()
                return "[ERROR] No student found with that registration number.", 404
        
        else:
            cursor.close()
            conn.close()
            return "[ERROR] Please provide email or registration number.", 400

        # record the requested semester back into the student dict for later use
        student['semester'] = semester
        if student['image_path']:
            student['image_path'] = url_for('static', filename=f"uploads/{student['image_path']}", _external=True)

        # normalize the student's department so variations still match exam records
        stu_dept_norm = normalize_department(student.get('department') or '')
        print(f"[DEBUG] Hall ticket lookup: student department='{student.get('department')}' normalized='{stu_dept_norm}', semester='{student['semester']}'")

        # Fetch exams for the student's department/semester (including ALL and prefix matches)
        cursor.execute("""
            SELECT exam_code, subject, semester, department AS exam_department,
                   exam_date, start_time, end_time, college_code, department_code
            FROM exams
            WHERE (
                    UPPER(department) = %s
                    OR department = 'ALL'
                    OR UPPER(department) LIKE %s
                  )
              AND CAST(semester AS CHAR) = %s
            ORDER BY exam_date
        """, (stu_dept_norm.upper(), f"{stu_dept_norm}%", str(student['semester']).upper()))

        exams = cursor.fetchall()
        if not exams:
            print(f"[WARNING] No exams found with parameters dept='{stu_dept_norm}' semester='{student['semester']}'")
            cursor.close()
            conn.close()
            return "[ERROR] No exams scheduled for your department and semester.", 404

        # For each exam, fetch seating info for this student
        for exam in exams:
            # Initialize default values
            exam['room'] = None
            exam['class_no'] = None
            exam['bench_no'] = None
            exam['position'] = None
            exam['invigilator'] = None

            cursor.execute(
                """
                SELECT room, class_no, bench_no, position, staff_id
                FROM exam_seating
                WHERE UPPER(exam_code) = UPPER(%s) AND UPPER(roll_no) = UPPER(%s)
                LIMIT 1
                """,
                (exam['exam_code'], student['roll_no'])
            )
            seat_row = cursor.fetchone()
            if seat_row:
                exam['room'] = seat_row.get('room')
                exam['class_no'] = seat_row.get('class_no')
                exam['bench_no'] = seat_row.get('bench_no')
                exam['position'] = seat_row.get('position')
                staff_id = seat_row.get('staff_id')
                if staff_id:
                    cursor.execute("SELECT name FROM staff WHERE staff_id = %s", (staff_id,))
                    st = cursor.fetchone()
                    if st:
                        exam['invigilator'] = st.get('name')

        # Format exam dates
        for exam in exams:
            if hasattr(exam["exam_date"], "strftime"):
                exam["exam_date"] = exam["exam_date"].strftime("%d-%m-%Y")

        cursor.close()
        conn.close()

        # Generate QR code
        qr_data = f"{student['name']} | {student['email']} | {student['roll_no']}"
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(qr_data)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_io = BytesIO()
        qr_img.save(qr_io, format="PNG")
        qr_b64 = base64.b64encode(qr_io.getvalue()).decode('utf-8')

        return render_template("hall_ticket_template.html", student=student, exams=exams, qr_b64=qr_b64)

    return render_template("hall_ticket_form.html")

def generate_hall_ticket_pdf(student):
    conn = get_db_connection()
    if not conn:
        return "[ERROR] Database connection failed.", 500
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT e.exam_code, e.subject, e.semester, e.exam_date, e.start_time, e.end_time,
               s.room, s.invigilator
        FROM exams e
        LEFT JOIN exam_seating s ON UPPER(e.exam_code) = UPPER(s.exam_code) AND UPPER(s.roll_no) = UPPER(%s)
        WHE THEN ANOTHER PROBLEM SOMERE (UPPER(e.department) = %s OR e.department = 'ALL') AND e.semester = %s
        ORDER BY e.exam_date
    """
    params = (student["roll_no"].upper(), student["department"].upper(), student["semester"])
    print(f"Executing query: {query % params}")
    cursor.execute(query, (student["roll_no"], student["department"], student["semester"]))
    exams = cursor.fetchall()
    if not exams:
        cursor.close()
        conn.close()
        return "[ERROR] No exams scheduled for your department and semester.", 404
    for exam in exams:
        if hasattr(exam["exam_date"], "strftime"):
            exam["exam_date"] = exam["exam_date"].strftime("%d-%m-%Y")
        print(f"Exam {exam['exam_code']}: Roll={student['roll_no']}, Room={exam['room']}, Invigilator={exam['invigilator']}")
    cursor.close()
    conn.close()

    # QR Code Generation
    qr_data = f"{student['name']} | {student['email']} | {student['roll_no']}"
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_path = os.path.join('static', 'qr_codes', f"qr_{student['roll_no']}.png")
    os.makedirs(os.path.dirname(qr_path), exist_ok=True)
    qr_img.save(qr_path)
    qr_url = url_for('static', filename=f'qr_codes/qr_{student["roll_no"]}.png', _external=True)

    try:
        html = render_template("hall_ticket_template.html", student=student, exams=exams, qr_url=qr_url)
        pdf = BytesIO()
        pisa_status = pisa.CreatePDF(BytesIO(html.encode('utf-8')), dest=pdf, link_callback=link_callback)
        if pisa_status.err:
            return f"[ERROR] Error generating PDF: {pisa_status.err}", 500
        pdf.seek(0)
        response = make_response(pdf.getvalue())
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = f"inline; filename=hall_ticket_{student['roll_no']}.pdf"
        return response
    except Exception as e:
        return f"[ERROR] Error generating PDF: {str(e)}", 500

def generate_hall_ticket_pdf(student):
    conn = get_db_connection()
    if not conn:
        return "[ERROR] Database connection failed.", 500
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT e.exam_code, e.subject, e.semester, e.exam_date, e.start_time, e.end_time,
               s.room, s.invigilator
        FROM exams e
        LEFT JOIN exam_seating s ON UPPER(e.exam_code) = UPPER(s.exam_code) AND UPPER(s.roll_no) = UPPER(%s)
        WHERE (UPPER(e.department) = %s OR e.department = 'ALL') AND CAST(e.semester AS CHAR) = %s
        ORDER BY e.exam_date
    """
    student_semester = str(student.get("semester", "")).strip()
    # normalize department for matching
    stu_dept_norm = normalize_department(student.get("department") or "")
    params = (student["roll_no"].upper(), stu_dept_norm.upper(), student_semester)
    print(f"Executing hall ticket PDF query with dept='{stu_dept_norm}' semester='{student_semester}'")
    cursor.execute(query, (student["roll_no"], stu_dept_norm, student_semester))
    exams = cursor.fetchall()
    if not exams:
        print(f"[WARNING] PDF query returned no exams for dept='{stu_dept_norm}' sem='{student_semester}'")
        cursor.close()
        conn.close()
        return "[ERROR] No exams scheduled for your department and semester.", 404
    for exam in exams:
        if hasattr(exam["exam_date"], "strftime"):
            exam["exam_date"] = exam["exam_date"].strftime("%d-%m-%Y")
        print(f"Exam {exam['exam_code']}: Roll={student['roll_no']}, Room={exam['room']}, Invigilator={exam['invigilator']}")
    cursor.close()
    conn.close()

    # QR Code Generation
    qr_data = f"{student['name']} | {student['email']} | {student['roll_no']}"
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_path = os.path.join('static', 'qr_codes', f"qr_{student['roll_no']}.png")
    os.makedirs(os.path.dirname(qr_path), exist_ok=True)
    qr_img.save(qr_path)
    qr_url = url_for('static', filename=f'qr_codes/qr_{student["roll_no"]}.png', _external=True)

    try:
        html = render_template("hall_ticket_template.html", student=student, exams=exams, qr_url=qr_url)
        pdf = BytesIO()
        pisa_status = pisa.CreatePDF(BytesIO(html.encode('utf-8')), dest=pdf, link_callback=link_callback)
        if pisa_status.err:
            return f"[ERROR] Error generating PDF: {pisa_status.err}", 500
        pdf.seek(0)
        response = make_response(pdf.getvalue())
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = f"inline; filename=hall_ticket_{student['roll_no']}.pdf"
        return response
    except Exception as e:
        return f"[ERROR] Error generating PDF: {str(e)}", 500
@app.route('/seating')
def seating():
    department = request.args.get('department', '').upper()
    exam_code = request.args.get('exam_code', '').upper()
    hall_no = request.args.get('hall_no', '').upper()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Get all seating data with bench count info
        query = """
        SELECT 
            es.id,
            es.exam_code,
            es.roll_no,
            s.name AS student_name,
            s.department AS student_department,
            e.department AS exam_department,
            es.room AS room_no,
            es.class_no,
            es.col,
            es.position,
            es.bench_no,
            es.seat_num,
            st.name AS invigilator,
            e.exam_date,
            e.exam_session,
            e.subject,
            CAST(COALESCE(es.is_absent, 0) AS UNSIGNED) AS is_absent,
            es.absence_reason,
            dbi.bench_count
        FROM exam_seating es
        LEFT JOIN students s ON s.roll_no = es.roll_no
        LEFT JOIN staff st ON st.staff_id = es.staff_id
        LEFT JOIN exams e ON e.exam_code = es.exam_code
        LEFT JOIN department_bench_info dbi ON (
            UPPER(dbi.department) = UPPER(REGEXP_SUBSTR(es.room, '^[^0-9]+'))
            AND dbi.class_number = CAST(REGEXP_SUBSTR(es.room, '[0-9]+$') AS UNSIGNED)
        )
        WHERE 1=1
        """

        params = []
        if department:
            # If only department is provided, show all seats where department matches
            # This handles searching by just department code (e.g., PHY, CS, COM)
            query += " AND (UPPER(e.department) = %s OR UPPER(es.room) LIKE %s)"
            params.append(department)
            params.append(f"{department}%")  # Match PHY, PHY1, PHY-1-1, etc.
        if exam_code:
            query += " AND UPPER(es.exam_code) = %s"
            params.append(exam_code)
        if hall_no:
            query += " AND UPPER(es.room) LIKE %s"
            params.append(f"{hall_no}%")  # Match PHY-1-1, PHY1, etc.

        # Order by: exam_code (for hall grouping), then by seat position within hall
        query += " ORDER BY es.exam_code, es.room, es.class_no, es.col, es.position, es.bench_no, es.seat_num"

        cursor.execute(query, params)
        allocated_seats = cursor.fetchall()
        
        # Build complete seating layout with all possible seats
        seating_data = []
        
        # Group allocated seats by hall
        halls_dict = {}
        for seat in allocated_seats:
            if seat['exam_code'] and seat['room_no']:
                # Use room_no directly as hall_no (e.g., PHY1, PHY2, etc.)
                hall_no = seat['room_no'].strip()  # PHY1, COM1, CS2, etc.
                
                if hall_no not in halls_dict:
                    halls_dict[hall_no] = {
                        'seats': {},
                        'info': seat
                    }
                
                key = (seat['col'], seat['position'], seat['bench_no'])
                halls_dict[hall_no]['seats'][key] = seat
        
        # Generate all seats for each hall with proper seat numbering
        for hall_no, hall_data in halls_dict.items():
            info_seat = hall_data['info']
            
            # Get bench_count directly from the seating data
            # The bench_count was joined from department_bench_info table
            bench_count = info_seat.get('bench_count', 15)
            
            # If bench_count is None (no matching department_bench_info row), try to look it up
            if bench_count is None:
                # Extract department and class_no from room_no (format: "வா1", "B.COM2", etc.)
                import re as regex_module
                hall_match = regex_module.match(r'^([^\d]+?)(\d+)$', hall_no.strip())
                
                if hall_match:
                    hall_dept = hall_match.group(1).upper()  # "வா", "B.COM", etc.
                    class_num = int(hall_match.group(2))     # 1, 2, 3, etc.
                    
                    # Get bench config for the specific class using a separate cursor
                    helper_cursor = conn.cursor(dictionary=True)
                    try:
                        helper_cursor.execute("""
                            SELECT bench_count FROM department_bench_info 
                            WHERE UPPER(department) = %s AND class_number = %s
                        """, (hall_dept, class_num))
                        dept_config = helper_cursor.fetchone()
                        bench_count = dept_config['bench_count'] if dept_config and dept_config['bench_count'] else 15
                    finally:
                        helper_cursor.fetchall()  # Consume any remaining results
                        helper_cursor.close()
                else:
                    # Fallback if regex doesn't match
                    bench_count = 15
            
            # Calculate benches per column
            benches_per_col_base = bench_count // 3
            remainder = bench_count % 3
            column_benches = [benches_per_col_base + (1 if i < remainder else 0) for i in range(3)]
            
            # Find max benches in any column
            max_benches_in_hall = max(column_benches) if column_benches else 5
            
            # Generate seat numbers using CORRECT formula
            seat_num_map = {}  # Map (col, position, bench) -> seat_num
            
            # Position multiplier for seat numbering (benches per column)
            POSITION_MULTIPLIER = max_benches_in_hall  
            COLUMN_MULTIPLIER = 3 * POSITION_MULTIPLIER  
            
            for bench in range(1, max_benches_in_hall + 1):
                for col in [1, 2, 3]:
                    num_benches = column_benches[col - 1]
                    # Only create seats if this column has this many benches
                    if bench <= num_benches:
                        for pos_idx, position in enumerate(['LEFT', 'CENTER', 'RIGHT']):
                            # Calculate seat number: bench + (col-1)*max_benches*3 + pos_idx*max_benches
                            # For 5 benches: seat = bench + (col-1)*15 + pos_idx*5
                            seat_num = bench + (col - 1) * (3 * max_benches_in_hall) + pos_idx * max_benches_in_hall
                            seat_num_map[(col, position, bench)] = seat_num
            
            # Generate all seats in BENCH-FIRST order
            for bench in range(1, max_benches_in_hall + 1):
                for col in [1, 2, 3]:
                    num_benches = column_benches[col - 1]
                    # Only create seats if this column has this many benches
                    if bench <= num_benches:
                        for position in ['LEFT', 'CENTER', 'RIGHT']:
                            key = (col, position, bench)
                            calculated_seat_num = seat_num_map[key]
                            
                            if key in hall_data['seats']:
                                # Seat is allocated - use the actual seat_num from database
                                seat_obj = hall_data['seats'][key]
                            else:
                                # Empty seat - generate calculated seat_num
                                seat_obj = {
                                    'id': None,
                                    'exam_code': info_seat['exam_code'],
                                    'roll_no': None,
                                    'student_name': None,
                                    'exam_department': info_seat['exam_department'],
                                    'room_no': info_seat['room_no'],
                                    'class_no': info_seat['class_no'],
                                    'col': col,
                                    'position': position,
                                    'bench_no': bench,
                                    'seat_num': calculated_seat_num,
                                    'invigilator': None,
                                    'exam_date': info_seat['exam_date'],
                                    'exam_session': info_seat['exam_session'],
                                    'subject': info_seat['subject']
                                }
                            
                            # Use seat_num from database for allocated seats, calculated for empty ones
                            if key not in hall_data['seats']:
                                seat_obj['seat_num'] = calculated_seat_num
                            
                            # Store bench count info for template usage
                            seat_obj['max_benches'] = max_benches_in_hall
                            seat_obj['column_benches'] = column_benches
                            
                            # Format exam date
                            if seat_obj['exam_date']:
                                seat_obj['exam_date_formatted'] = seat_obj['exam_date'].strftime('%d-%m-%Y') if hasattr(seat_obj['exam_date'], 'strftime') else seat_obj['exam_date']
                            else:
                                seat_obj['exam_date_formatted'] = 'N/A'
                            
                            # Create hall number FROM room_no (physical location, e.g., PHY1, CS2, COM3)
                            # NOT from exam_department (home department)
                            seat_obj['hall_no'] = seat_obj['room_no'] if seat_obj['room_no'] else 'HLL'
                            
                            seating_data.append(seat_obj)

    finally:
        cursor.fetchall()  # Consume any remaining results before closing
        cursor.close()
        conn.close()

    # Build hall summary for department allocations
    hall_summary = {}
    for seat in seating_data:
        if seat['hall_no'] not in hall_summary:
            hall_summary[seat['hall_no']] = {}
        
        exam_code = seat['exam_code']
        if exam_code and seat['roll_no']:  # Only count allocated seats
            if exam_code not in hall_summary[seat['hall_no']]:
                # Get department from exam_department, or extract from exam_code if NULL
                department = seat['exam_department']
                if not department:
                    # Extract department code from exam_code (e.g., 23BCO3C2 -> BCO, 22BEN3C2 -> BEN)
                    import re as regex_module
                    dept_match = regex_module.search(r'^(\d+)([A-Z]+)', exam_code)
                    if dept_match:
                        dept_code = dept_match.group(2)
                        # Map common department codes
                        dept_map = {
                            'BCO': 'B.COM', 'TAM': 'TAMIL', 'ENG': 'ENGLISH', 'CHE': 'CHEMISTRY',
                            'BEN': 'ENGLISH', 'BZO': 'ZOOLOGY', 'BCE': 'ECONOMICS', 'BBO': 'BOTANY',
                            'HIS': 'HISTORY', 'GEO': 'GEOGRAPHY', 'PHY': 'PHYSICS', 'MAT': 'MATHEMATICS'
                        }
                        department = dept_map.get(dept_code, dept_code)
                    else:
                        department = 'Unknown'
                
                hall_summary[seat['hall_no']][exam_code] = {
                    'department': department,
                    'subject': seat['subject'],
                    'roll_numbers': []
                }
            
            hall_summary[seat['hall_no']][exam_code]['roll_numbers'].append(seat['roll_no'])
    
    # Process roll number ranges and totals per exam per hall
    hall_allocation_summary = {}
    for hall_no, exams in hall_summary.items():
        hall_allocation_summary[hall_no] = []
        for exam_code, exam_info in exams.items():
            roll_numbers = sorted(exam_info['roll_numbers'])
            if roll_numbers:
                hall_allocation_summary[hall_no].append({
                    'exam_code': exam_code,
                    'department': exam_info['department'],
                    'subject': exam_info['subject'],
                    'start_reg': roll_numbers[0],
                    'end_reg': roll_numbers[-1],
                    'total_students': len(roll_numbers)
                })

    return render_template('seating.html', seating=seating_data, hall_allocation_summary=hall_allocation_summary)

@app.route('/seating_details_debug')
def seating_details_debug():
    """Debug route to check what data exists in exam_seating"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Check all departments that have seating allocations
        cursor.execute("""
            SELECT 
                COALESCE(s.department, e.department) AS department,
                COUNT(*) as seat_count,
                MIN(e.exam_date) as first_exam_date,
                MAX(e.exam_date) as last_exam_date
            FROM exam_seating es
            JOIN exams e ON e.exam_code = es.exam_code
            LEFT JOIN students s ON s.roll_no = es.roll_no
            GROUP BY COALESCE(s.department, e.department)
            ORDER BY COALESCE(s.department, e.department)
        """)
        
        dept_stats = cursor.fetchall()
        
        # Check what exams exist in exams table
        cursor.execute("""
            SELECT 
                exam_code,
                subject,
                department,
                exam_date,
                exam_session,
                (SELECT COUNT(*) FROM exam_seating WHERE exam_code = exams.exam_code) as seating_count
            FROM exams
            ORDER BY exam_date DESC
            LIMIT 20
        """)
        
        exams_list = cursor.fetchall()
        
        return jsonify({
            'department_stats': dept_stats,
            'exams_with_seating_count': exams_list
        })
    
    finally:
        cursor.close()
        conn.close()

@app.route('/seating_details')
def seating_details():
    """
    Display seating allocation details in a single table.
    Shows all departments and their hall allocations for selected exam date.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Get all exam dates with seating allocations
        cursor.execute("""
            SELECT DISTINCT e.exam_date, e.exam_session
            FROM exams e
            WHERE e.exam_code IN (SELECT DISTINCT exam_code FROM exam_seating)
            ORDER BY e.exam_date DESC
        """)
        
        exam_dates = cursor.fetchall()
        
        if not exam_dates:
            return render_template('seating_details.html', 
                                 exam_date=None,
                                 exam_session=None,
                                 grouped_data={},
                                 exam_dates=[])
        
        # Get selected date from request, default to earliest date to show all departments
        selected_date = request.args.get('exam_date')
        
        if not selected_date:
            # Default to earliest date (to show most allocations)
            selected_date = exam_dates[-1]['exam_date']  # Last in DESC order = earliest
        else:
            # Parse the selected date
            from datetime import datetime
            selected_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        
        exam_date = selected_date
        
        # Get session for the selected date
        cursor.execute("""
            SELECT DISTINCT exam_session
            FROM exams
            WHERE exam_date = %s
            LIMIT 1
        """, (exam_date,))
        
        session_row = cursor.fetchone()
        exam_session = session_row['exam_session'] if session_row else None
        
        # Get all seating allocations for the selected date
        cursor.execute("""
            SELECT 
                es.room AS hall_no,
                COALESCE(s.department, e.department, SUBSTRING(es.roll_no, 7, 3)) AS student_department,
                MIN(CAST(es.roll_no AS UNSIGNED)) AS min_roll,
                MAX(CAST(es.roll_no AS UNSIGNED)) AS max_roll,
                COUNT(*) AS student_count
            FROM exam_seating es
            JOIN exams e ON e.exam_code = es.exam_code
            LEFT JOIN students s ON s.roll_no = es.roll_no
            WHERE e.exam_date = %s
            GROUP BY es.room, COALESCE(s.department, e.department, SUBSTRING(es.roll_no, 7, 3))
            ORDER BY es.room
        """, (exam_date,))
        
        seating_data = cursor.fetchall()
        
        # Group data by STUDENT DEPARTMENT, then collect halls under each department
        grouped_by_dept = {}
        for row in seating_data:
            dept = row['student_department']
            hall_no = row['hall_no']
            
            if dept not in grouped_by_dept:
                grouped_by_dept[dept] = []
            
            grouped_by_dept[dept].append(row)
        
        # Sort by department priority (வா first, then B.COM, then others)
        def get_dept_priority(dept_name):
            priority_order = ['வா', 'VA', 'BCOM', 'B.COM']
            if dept_name in priority_order:
                return priority_order.index(dept_name)
            else:
                return len(priority_order)
        
        # Sort departments by priority
        from collections import OrderedDict
        sorted_depts = sorted(grouped_by_dept.items(), key=lambda x: get_dept_priority(x[0]))
        sorted_grouped_data = OrderedDict(sorted_depts)
        
        print(f"[DEBUG] Sorted department display order: {list(sorted_grouped_data.keys())}", flush=True)
        
        return render_template('seating_details.html', 
                             exam_date=exam_date,
                             exam_session=exam_session,
                             grouped_data=sorted_grouped_data,
                             exam_dates=exam_dates)
    
    finally:
        cursor.close()
        conn.close()

@app.route('/add_staff', methods=['GET', 'POST'])
def add_staff():
    if not session.get('admin'):
        return redirect(url_for('login', next='add_staff'))
    
    message = None
    if request.method == 'POST':
        name = request.form['name']
        department = request.form['department'].upper()
        email = request.form.get('email')

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO staff (name, department, email) VALUES (%s, %s, %s)",
                (name, department, email)
            )
            conn.commit()
            message = f"[OK] Staff {name} added successfully to {department}."
        except Error as e:
            message = f"[ERROR] Error adding staff: {str(e)}"
        finally:
            cursor.close()
            conn.close()

    # Fetch existing staff to show in admin page
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM staff ORDER BY department, name")
        staff_list = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template('add_staff.html', message=message, staff_list=staff_list)
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        action = request.form.get('action')
        exam_code = request.form.get('exam_code')
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)

            if action == 'delete':
                cursor.execute('SELECT * FROM exams WHERE exam_code = %s', (exam_code,))
                exam = cursor.fetchone()
                if exam:
                    # Notify students
                    notify_students_by_exam(exam_code, mode='delete')
                    # Notify staff
                    notify_staff_by_exam(exam_code, mode='cancel')

                # Delete exam record
                cursor.execute('DELETE FROM exams WHERE exam_code = %s', (exam_code,))
                conn.commit()
                return redirect(url_for('admin'))

            elif action == 'edit':
                subject = request.form.get('subject').upper()
                semester = request.form.get('semester')
                department = request.form.get('department').upper()
                exam_date = request.form.get('exam_date')
                start_time = request.form.get('start_time')
                end_time = request.form.get('end_time')

                if not all([subject, semester, department, exam_date, start_time, end_time]):
                    return render_template('admin.html', error="All fields are required for editing.", exams=[])

                cursor.execute('''
                    UPDATE exams 
                    SET subject = %s, semester = %s, department = %s, exam_date = %s, start_time = %s, end_time = %s
                    WHERE exam_code = %s
                ''', (subject, semester, department, exam_date, start_time, end_time, exam_code))
                conn.commit()

                # Notify students and staff about the update
                notify_students_by_exam(exam_code, mode='update')
                notify_staff_by_exam(exam_code, mode='update')

                # seating needs to be recalculated in case students or timing changed
                try:
                    threading.Thread(target=allocate_seating_for_exam, args=(exam_code,), daemon=True).start()
                except Exception as e:
                    print(f"[WARNING] Could not start seating refresh thread after exam update: {e}")

                return redirect(url_for('admin'))

        except Error as e:
            return render_template('admin.html', error=f"Error processing action: {str(e)}", exams=[])
        finally:
            cursor.close()
            conn.close()

    # GET request: fetch all exams to display
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM exams')
        exam_rows = cursor.fetchall()
        exams = [{
            'exam_code': row[0],
            'subject': row[1],
            'semester': row[2],
            'department': row[3],
            'exam_date': row[4].strftime('%Y-%m-%d') if hasattr(row[4], 'strftime') else row[4],
            'start_time': row[5],
            'end_time': row[6]
        } for row in exam_rows]
    except Error as e:
        exams = []
        return render_template('admin.html', error=f"Error loading exams: {str(e)}", exams=[])
    finally:
        cursor.close()
        conn.close()

    return render_template('admin.html', exams=exams)


@app.route('/admin/allocate/<exam_code>', methods=['GET', 'POST'])
def admin_allocate(exam_code):
    """Admin-only helper to trigger seating allocation for an exam.
    Usage (while logged in as admin): GET /admin/allocate/TAMOR
    """
    if not session.get('admin'):
        return redirect(url_for('login', next='manage'))

    try:
        ok, msg = allocate_seating_for_exam(exam_code.upper())
        if ok:
            return f"[OK] Seating allocation executed for {exam_code.upper()}"
        else:
            return f"[ERROR] Seating allocation returned failure: {msg}"
    except Exception as e:
        return f"[ERROR] Error running allocation: {str(e)}"


@app.route('/admin/debug_seating/<exam_code>/<roll_no>')
def admin_debug_seating(exam_code, roll_no):
    if not session.get('admin'):
        return redirect(url_for('login', next='manage'))
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute('''
            SELECT * FROM exam_seating
            WHERE UPPER(exam_code) = UPPER(%s) AND UPPER(roll_no) = UPPER(%s)
        ''', (exam_code, roll_no))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return f"Error: {e}", 500


@app.route('/admin/fix_invigilators/<exam_code>', methods=['POST','GET'])
def admin_fix_invigilators(exam_code):
    """Admin helper: assign invigilators to exam_seating rows missing staff_id.
    Uses round-robin across all `staff` rows. Requires admin session.
    """
    if not session.get('admin'):
        return redirect(url_for('login', next='manage'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # load available staff
        cursor.execute("SELECT staff_id, name FROM staff ORDER BY staff_id")
        staff_list = cursor.fetchall()
        if not staff_list:
            return "[ERROR] No staff available to assign.", 400

        staff_ids = {s['staff_id'] for s in staff_list}

        # find seating rows for this exam and detect missing/invalid staff_id
        cursor.execute("SELECT id, staff_id FROM exam_seating WHERE UPPER(exam_code)=UPPER(%s)", (exam_code,))
        seating_rows = cursor.fetchall()
        missing_ids = []
        for r in seating_rows:
            sid = r.get('staff_id')
            if not sid or sid not in staff_ids:
                missing_ids.append(r['id'])

        if not missing_ids:
            return jsonify({'updated': 0, 'message': 'No missing invigilators found.'})

        # assign staff round-robin
        updated = 0
        staff_index = 0
        for rid in missing_ids:
            staff = staff_list[staff_index % len(staff_list)]
            cursor.execute("UPDATE exam_seating SET staff_id = %s, invigilator = %s WHERE id = %s", (staff['staff_id'], staff['name'], rid))
            staff_index += 1
            updated += 1

        conn.commit()

        # return the updated seating rows with staff names
        cursor.execute("SELECT es.*, st.name AS staff_name FROM exam_seating es LEFT JOIN staff st ON es.staff_id = st.staff_id WHERE UPPER(es.exam_code)=UPPER(%s)", (exam_code,))
        result_rows = cursor.fetchall()
        return jsonify({'updated': updated, 'rows': result_rows})

    except Exception as e:
        conn.rollback()
        return f"Error fixing invigilators: {e}", 500
    finally:
        cursor.close()
        conn.close()


@app.route('/admin/sync_invigilators/<exam_code>', methods=['GET'])
def admin_sync_invigilators(exam_code):
    """Sync invigilator names for an exam from staff table into exam_seating.invigilator.
    Runs on the server so it bypasses Workbench safe-update mode.
    """
    if not session.get('admin'):
        return redirect(url_for('login', next='manage'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            UPDATE exam_seating es
            JOIN staff st ON es.staff_id = st.staff_id
            SET es.invigilator = st.name
            WHERE UPPER(es.exam_code) = UPPER(%s)
              AND (es.invigilator IS NULL OR es.invigilator = '')
            """,
            (exam_code,)
        )
        updated = cursor.rowcount
        conn.commit()

        cursor.execute("SELECT id, exam_code, roll_no, staff_id, invigilator FROM exam_seating WHERE UPPER(exam_code)=UPPER(%s)", (exam_code,))
        rows = cursor.fetchall()
        return jsonify({'updated': updated, 'rows': rows})
    except Exception as e:
        conn.rollback()
        return f"Error syncing invigilators: {e}", 500
    finally:
        cursor.close()
        conn.close()


@app.route('/download_pdf')
def download_pdf():
    semester = request.args.get('semester', '')
    department = request.args.get('department', '')
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = '''
            SELECT exam_code, subject, semester, department, exam_date, start_time, end_time 
            FROM exams WHERE 1=1
        '''
        params = []
        if semester and semester != "ALL":
            query += ' AND semester = %s'
            params.append(semester)
        if department and department != "ALL":
            query += " AND (UPPER(department) = %s OR department = 'ALL')"
            params.append(department.upper())
        cursor.execute(query, params)
        exams = cursor.fetchall()
    except Error as e:
        return f"Error generating PDF: {str(e)}"
    finally:
        cursor.close()
        conn.close()
    output_dir = os.path.join(app.root_path, 'pdf')
    os.makedirs(output_dir, exist_ok=True)
    filename = 'exam_schedule.pdf'
    filepath = os.path.join(output_dir, filename)
    data = [["Exam Code", "Subject", "Semester", "Department", "Date", "Start Time", "End Time"]]
    for exam in exams:
        exam_date = exam[4].strftime('%d-%m-%Y') if hasattr(exam[4], 'strftime') else str(exam[4])
        data.append([exam[0], exam[1], exam[2], exam[3], exam_date, exam[5], exam[6]])
    pdf = SimpleDocTemplate(filepath, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = [Paragraph("Exam Schedule", styles['Title']), Spacer(1, 12)]
    col_widths = [1.3*inch, 1.8*inch, 0.8*inch, 1.2*inch, 1.1*inch, 1.1*inch, 1.1*inch]
    table = Table(data, repeatRows=1, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#003366")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 12),
        ('BOTTOMPADDING', (0,0), (-1,0), 10),
        ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('FONTSIZE', (0,1), (-1,-1), 10),
    ]))
    elements.append(table)
    pdf.build(elements)
    return send_from_directory(directory=output_dir, path=filename, as_attachment=True)
# exam_chatbot.py
# Exam Chatbot 🤖

exam_schedule = {
    "cs sem6": ["Data Structures", "Algorithms", "DBMS", "Operating Systems"],
    "ee sem5": ["Circuit Analysis", "Electromagnetics", "Control Systems", "Power Electronics"],
    "me sem4": ["Thermodynamics", "Fluid Mechanics", "Material Science", "Machine Design"],
}

def normalize_input(user_input):
    """
    Normalize user input for easier matching:
    - Lowercase
    - Replace 'semester' with 'sem'
    - Remove extra spaces
    """
    user_input = user_input.lower()
    user_input = user_input.replace("semester", "sem")
    user_input = " ".join(user_input.split())  # remove extra spaces
    return user_input

@app.route('/download_seating_pdf')
def download_seating_pdf():
    department = request.args.get('department', '')
    exam_code = request.args.get('exam_code', '')
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = '''
            SELECT s.exam_code, s.roll_no, s.room, s.invigilator
            FROM exam_seating s
            JOIN exams e ON UPPER(e.exam_code) = UPPER(s.exam_code)
            WHERE 1=1
        '''
        params = []
        if department:
            query += ' AND UPPER(e.department) = %s'
            params.append(department.upper())
        if exam_code:
            query += ' AND UPPER(s.exam_code) = %s'
            params.append(exam_code.upper())
        cursor.execute(query, params)
        seating_data = cursor.fetchall()
        print(f"Seating PDF data: {[(row[1], row[2], row[3]) for row in seating_data]}")
    except Error as e:
        return f"Error generating seating PDF: {str(e)}"
    finally:
        cursor.close()
        conn.close()
    output_dir = os.path.join(app.root_path, 'pdf')
    os.makedirs(output_dir, exist_ok=True)
    filename = 'exam_seating.pdf'
    filepath = os.path.join(output_dir, filename)
    data = [["Exam Code", "Roll No", "Room", "Invigilator"]]
    for row in seating_data:
        data.append(list(row))
    pdf = SimpleDocTemplate(filepath, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = [Paragraph("Filtered Exam Seating Plan", styles['Title']), Spacer(1, 12)]
    col_widths = [1.5*inch, 1.2*inch, 1.2*inch, 1.5*inch]
    table = Table(data, repeatRows=1, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#003366")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 12),
        ('BOTTOMPADDING', (0,0), (-1,0), 10),
        ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('FONTSIZE', (0,1), (-1,-1), 10),
    ]))
    elements.append(table)
    pdf.build(elements)
    return send_from_directory(directory=output_dir, path=filename, as_attachment=True)

# ============================================================================
# ABSENT STUDENT MANAGEMENT ROUTES
# ============================================================================

@app.route('/mark-absent-new', methods=['GET', 'POST'])
def mark_absent_new():
    """Admin route to mark students as absent - new interface - CASE 1: Semester-wide & CASE 2: Exam-specific"""
    if not session.get('student_admin'):
        return redirect(url_for('login', next='mark_absent_new'))
    
    if request.method == 'POST':
        try:
            conn = get_db_connection()
            if not conn:
                flash("[ERROR] Database connection failed", category='error')
                return redirect(url_for('mark_absent_new'))
                
            cursor = conn.cursor()
            
            # Ensure required columns exist in exam_seating table
            cursor.execute("DESCRIBE exam_seating")
            columns = [col[0] for col in cursor.fetchall()]
            
            if 'is_absent' not in columns:
                cursor.execute("ALTER TABLE exam_seating ADD COLUMN is_absent TINYINT(1) DEFAULT 0")
            if 'absence_reason' not in columns:
                cursor.execute("ALTER TABLE exam_seating ADD COLUMN absence_reason VARCHAR(255) DEFAULT NULL")
            if 'marked_absent_at' not in columns:
                cursor.execute("ALTER TABLE exam_seating ADD COLUMN marked_absent_at TIMESTAMP DEFAULT NULL")
            if 'marked_by' not in columns:
                cursor.execute("ALTER TABLE exam_seating ADD COLUMN marked_by VARCHAR(100) DEFAULT NULL")
            
            # Create student_absent table if it doesn't exist (for CASE 1 - semester-wide absences)
            try:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS student_absent (
                        id INT PRIMARY KEY AUTO_INCREMENT,
                        roll_no VARCHAR(20) NOT NULL,
                        department VARCHAR(50) NOT NULL,
                        semester INT NOT NULL,
                        absence_reason VARCHAR(255) DEFAULT NULL,
                        marked_by VARCHAR(100) DEFAULT NULL,
                        marked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY unique_absent (roll_no, department, semester)
                    )
                """)
                conn.commit()
                print("[DEBUG] student_absent table created/verified", flush=True)
            except Exception as table_err:
                print(f"[DEBUG] Error creating table: {table_err}", flush=True)
                flash(f"[ERROR] Table creation failed: {str(table_err)}", category='error')
            
            # Get form data - dynamically handle multiple student entries
            student_count = 0
            success_count = 0
            
            # Iterate through all possible student entries
            for i in range(100):  # Support up to 100 students
                roll_no = request.form.get(f'roll_no_{i}', '').strip()
                absence_type = request.form.get(f'absence_type_{i}', '').strip()
                
                # If roll_no is empty, stop processing
                if not roll_no:
                    continue
                
                student_count += 1
                admin_user = session.get('email', 'SYSTEM')
                
                # CASE 1: Mark absent for ENTIRE SEMESTER
                if absence_type == 'semester':
                    department = request.form.get(f'department_{i}', '').strip().upper()
                    semester = request.form.get(f'semester_{i}', '').strip()
                    reason = request.form.get(f'reason_{i}', '').strip()
                    
                    if not department or not semester:
                        flash(f"[WARNING] Incomplete semester entry for {roll_no}. Skipped.", category='error')
                        continue
                    
                    print(f"[DEBUG] CASE 1 - Processing student {i}: roll_no={roll_no}, dept={department}, sem={semester}, reason={reason}, admin={admin_user}", flush=True)
                    
                    # Insert into student_absent table
                    try:
                        cursor.execute("""
                            INSERT INTO student_absent 
                            (roll_no, department, semester, absence_reason, marked_by)
                            VALUES (%s, %s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE
                            absence_reason = VALUES(absence_reason),
                            marked_by = VALUES(marked_by),
                            marked_at = NOW()
                        """, (roll_no, department, semester, reason if reason else None, admin_user))
                        
                        print(f"[DEBUG] Inserted {roll_no} into student_absent. Rows affected: {cursor.rowcount}", flush=True)
                        success_count += 1
                        
                    except Exception as e:
                        print(f"[ERROR] Failed to insert {roll_no}: {str(e)}", flush=True)
                        flash(f"[ERROR] Failed to mark {roll_no} absent (semester): {str(e)}", category='error')
                    
                    # Also mark as absent in exam_seating table if records exist for this student
                    try:
                        update_query = """
                            UPDATE exam_seating 
                            SET is_absent = 1, 
                                absence_reason = %s,
                                marked_absent_at = NOW(),
                                marked_by = %s
                            WHERE roll_no = %s
                        """
                        cursor.execute(update_query, (reason if reason else None, admin_user, roll_no))
                        conn.commit()  # Commit immediately after update
                        
                        rows_updated = cursor.rowcount
                        print(f"[DEBUG] Updated exam_seating for {roll_no}. Rows affected: {rows_updated}", flush=True)
                        success_count += 1
                    
                    except Exception as e:
                        print(f"[DEBUG] Error updating exam_seating for {roll_no}: {str(e)}", flush=True)
                        conn.rollback()  # Rollback on error
                
                # CASE 2: Mark absent for SPECIFIC EXAM CODE
                elif absence_type == 'exam':
                    exam_code = request.form.get(f'exam_code_{i}', '').strip().upper()
                    exam_reason = request.form.get(f'exam_reason_{i}', '').strip()
                    
                    if not exam_code:
                        flash(f"[WARNING] No exam code provided for {roll_no}. Skipped.", category='error')
                        continue
                    
                    print(f"[DEBUG] CASE 2 - Processing student {i}: roll_no={roll_no}, exam_code={exam_code}, reason={exam_reason}, admin={admin_user}", flush=True)
                    
                    # Mark as absent for SPECIFIC exam in exam_seating table
                    try:
                        update_query = """
                            UPDATE exam_seating 
                            SET is_absent = 1, 
                                absence_reason = %s,
                                marked_absent_at = NOW(),
                                marked_by = %s
                            WHERE roll_no = %s AND exam_code = %s
                        """
                        cursor.execute(update_query, (exam_reason if exam_reason else None, admin_user, roll_no, exam_code))
                        conn.commit()  # Commit immediately after update
                        
                        rows_updated = cursor.rowcount
                        if rows_updated > 0:
                            print(f"[DEBUG] Updated exam_seating for {roll_no} in exam {exam_code}. Rows affected: {rows_updated}", flush=True)
                            success_count += 1
                        else:
                            print(f"[WARNING] No records found for {roll_no} in exam {exam_code}", flush=True)
                            flash(f"[WARNING] No seating record found for {roll_no} in exam {exam_code}. Skipped.", category='error')
                    
                    except Exception as e:
                        print(f"[ERROR] Failed to mark {roll_no} absent for exam {exam_code}: {str(e)}", flush=True)
                        flash(f"[ERROR] Failed to mark {roll_no} absent for exam {exam_code}: {str(e)}", category='error')
                        conn.rollback()  # Rollback on error
                
                else:
                    flash(f"[WARNING] Invalid absence type for {roll_no}. Skipped.", category='error')
            
            # Final commit
            print(f"[DEBUG] Final commit of {success_count} changes to database", flush=True)
            conn.commit()
            print(f"[DEBUG] Commit successful", flush=True)
            cursor.close()
            conn.close()
            
            if student_count > 0:
                flash(f"[OK] Successfully marked {success_count}/{student_count} student(s) as absent", category='success')
            else:
                flash("[WARNING] No students added. Please fill in the form.", category='error')
            
            return redirect(url_for('mark_absent_new'))
        
        except Exception as e:
            flash(f"[ERROR] Error marking students absent: {str(e)}", category='error')
    
    return render_template('mark_absent.html')

@app.route('/check-student-absent')
def check_student_absent():
    """Debug route to check student_absent table"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("SELECT * FROM student_absent LIMIT 10")
        records = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return {
            'status': 'success',
            'count': len(records),
            'records': records
        }
    except Exception as e:
        cursor.close()
        conn.close()
        return {
            'status': 'error',
            'message': str(e)
        }

@app.route('/mark-absent', methods=['GET', 'POST'])
def mark_absent():
    """Admin route to mark students as absent"""
    if not session.get('student_admin'):
        return redirect(url_for('login', next='mark_absent'))
    
    if request.method == 'POST':
        department = request.form.get('department', '').upper()
        semester = request.form.get('semester', '').strip()
        roll_no = request.form.get('roll_no', '').upper()
        absence_type = request.form.get('absence_type', 'current')
        absence_reason = request.form.get('absence_reason', '')
        arrear_semester = request.form.get('arrear_semester', '').strip()
        arrear_exam_code = request.form.get('arrear_exam_code', '').upper()
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            # 1. Verify student exists
            cursor.execute(
                "SELECT * FROM students WHERE UPPER(roll_no) = %s AND UPPER(department) = %s AND CAST(semester AS CHAR) = %s",
                (roll_no, department, semester)
            )
            student = cursor.fetchone()
            
            if not student:
                flash(f"[ERROR] Student {roll_no} not found in {department}, Semester {semester}", category='error')
                return redirect(url_for('mark_absent'))
            
            # 2. Find the exam to mark as absent
            if absence_type == 'current':
                # Find exam for current semester
                cursor.execute("""
                    SELECT exam_code FROM exams 
                    WHERE UPPER(department) = %s AND CAST(semester AS CHAR) = %s
                    LIMIT 1
                """, (department, semester))
                exam_row = cursor.fetchone()
                
                if not exam_row:
                    flash(f"[ERROR] No exam found for {department}, Semester {semester}", category='error')
                    return redirect(url_for('mark_absent'))
                
                exam_code = exam_row['exam_code']
            else:  # arrear
                # Use provided exam code
                if not arrear_exam_code:
                    flash(f"[ERROR] Arrear exam code is required", category='error')
                    return redirect(url_for('mark_absent'))
                
                cursor.execute(
                    "SELECT exam_code FROM exams WHERE UPPER(exam_code) = %s LIMIT 1",
                    (arrear_exam_code,)
                )
                exam_row = cursor.fetchone()
                
                if not exam_row:
                    flash(f"[ERROR] Exam code {arrear_exam_code} not found", category='error')
                    return redirect(url_for('mark_absent'))
                
                exam_code = exam_row['exam_code']
            
            # 3. Find the seating record
            cursor.execute(
                "SELECT * FROM exam_seating WHERE exam_code = %s AND UPPER(roll_no) = %s",
                (exam_code, roll_no)
            )
            seating = cursor.fetchone()
            
            if not seating:
                flash(f"[ERROR] Student {roll_no} not allocated to exam {exam_code}", category='error')
                return redirect(url_for('mark_absent'))
            
            # 4. Check if absence columns exist, create if needed
            cursor.execute("DESCRIBE exam_seating")
            columns = [col[0] for col in cursor.fetchall()]
            
            if 'is_absent' not in columns:
                cursor.execute("ALTER TABLE exam_seating ADD COLUMN is_absent TINYINT(1) DEFAULT 0")
            if 'absence_reason' not in columns:
                cursor.execute("ALTER TABLE exam_seating ADD COLUMN absence_reason VARCHAR(255) DEFAULT NULL")
            if 'marked_absent_at' not in columns:
                cursor.execute("ALTER TABLE exam_seating ADD COLUMN marked_absent_at TIMESTAMP DEFAULT NULL")
            if 'marked_by' not in columns:
                cursor.execute("ALTER TABLE exam_seating ADD COLUMN marked_by VARCHAR(100) DEFAULT NULL")
            
            conn.commit()
            
            # 5. Update seating record to mark as absent
            admin_user = session.get('email', 'SYSTEM')
            cursor.execute("""
                UPDATE exam_seating 
                SET is_absent = 1, absence_reason = %s, marked_absent_at = NOW(), marked_by = %s
                WHERE exam_code = %s AND UPPER(roll_no) = %s
            """, (absence_reason if absence_reason else None, admin_user, exam_code, roll_no))
            
            conn.commit()
            
            # 6. Log to absence audit log if exists
            try:
                cursor.execute("""
                    INSERT INTO absence_audit_log (exam_code, roll_no, action, admin_user, notes)
                    VALUES (%s, %s, 'MARKED_ABSENT', %s, %s)
                """, (exam_code, roll_no, admin_user, absence_reason))
                conn.commit()
            except:
                pass  # Ignore if audit table doesn't exist
            
            cursor.close()
            conn.close()
            
            flash(f"[OK] Student {roll_no} marked as ABSENT for exam {exam_code}", category='success')
            return redirect(url_for('mark_absent'))
            
        except Exception as e:
            flash(f"[ERROR] {str(e)}", category='error')
            return redirect(url_for('mark_absent'))
    
    return render_template('mark_absent.html')

@app.route('/absent-details/<hall_no>', methods=['GET'])
def absent_details(hall_no):
    """
    Display absence details for a specific hall.
    Shows all exams and allows filtering by exam date.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Get selected date from dropdown (optional)
        selected_date = request.args.get('exam_date')

        # Fetch seating and exam data for this hall
        query = """
            SELECT 
                es.exam_code,
                es.roll_no,
                es.room,
                CAST(COALESCE(es.is_absent, 0) AS UNSIGNED) AS is_absent,
                es.absence_reason,
                es.invigilator,
                s.name AS student_name,
                s.department,
                DATE_FORMAT(e.exam_date, '%d-%m-%Y') AS exam_date,
                e.exam_session,
                e.start_time,
                e.department_code,
                e.subject
            FROM exam_seating es
            LEFT JOIN students s ON s.roll_no = es.roll_no
            LEFT JOIN exams e ON e.exam_code = es.exam_code
            WHERE UPPER(es.room) = %s
            ORDER BY e.exam_date, e.exam_code, s.department, es.roll_no
        """
        cursor.execute(query, [hall_no.upper()])
        seating_data = cursor.fetchall()

        if not seating_data:
            flash(f"No seating data found for hall {hall_no}", "error")
            return redirect(url_for('seating'))

        # Filter by selected exam date if provided
        if selected_date:
            seating_data = [s for s in seating_data if s['exam_date'] == selected_date]

        # Collect all exam dates for the dropdown
        exam_dates = sorted({s['exam_date'] for s in seating_data})

        # Default session type
        session_type = seating_data[0]['exam_session'] if seating_data[0].get('exam_session') else 'FN'

        # Process data: group by exam_code and department
        exams_data = {}  # {exam_code: {departments: {dept: info}}}
        all_invigilators = []

        for seat in seating_data:
            exam_code = seat.get('exam_code', 'UNKNOWN')

            if exam_code not in exams_data:
                exams_data[exam_code] = {
                    'subject': seat.get('subject', ''),
                    'exam_date': seat.get('exam_date'),
                    'start_time': seat.get('start_time'),
                    'departments': {}
                }

            dept = seat.get('department', 'UNKNOWN').upper()
            if dept not in exams_data[exam_code]['departments']:
                exams_data[exam_code]['departments'][dept] = {
                    'department_name': seat.get('department', ''),
                    'course': dept,
                    'subcode': seat.get('department_code', ''),
                    'total': 0,
                    'absent': 0,
                    'present': 0,
                    'invigilator': None,
                    'absentees': []
                }

            # Track invigilators
            invigilator = seat.get('invigilator')
            if invigilator and invigilator.strip():
                invigilator = invigilator.strip()
                if invigilator not in all_invigilators:
                    all_invigilators.append(invigilator)
                if not exams_data[exam_code]['departments'][dept]['invigilator']:
                    exams_data[exam_code]['departments'][dept]['invigilator'] = invigilator

            # Count present/absent
            exams_data[exam_code]['departments'][dept]['total'] += 1
            if seat['is_absent'] == 1:
                exams_data[exam_code]['departments'][dept]['absent'] += 1
                exams_data[exam_code]['departments'][dept]['absentees'].append({
                    'roll_no': seat['roll_no'],
                    'name': seat['student_name'],
                    'reason': seat['absence_reason']
                })
            else:
                exams_data[exam_code]['departments'][dept]['present'] += 1

            # Attendance %
            total = exams_data[exam_code]['departments'][dept]['total']
            present = exams_data[exam_code]['departments'][dept]['present']
            exams_data[exam_code]['departments'][dept]['attendance_percent'] = round((present / total) * 100, 2) if total else 0

        # Join all invigilators for display
        hall_invigilators = ', '.join(all_invigilators) if all_invigilators else 'Not Assigned'

        cursor.close()
        conn.close()

        return render_template(
            'absent_details.html',
            hall_no=hall_no,
            session_type=session_type,
            hall_invigilators=hall_invigilators,
            exams_data=exams_data,
            exam_dates=exam_dates,
            selected_date=selected_date
        )

    except Exception as e:
        flash(f"[ERROR] Error fetching absent details: {str(e)}", category='error')
        return redirect(url_for('seating'))

@app.route('/absentees-statement', methods=['GET'])

def absentees_statement():
    """Display consolidated absentees statement page (department-wise)"""
    return render_template('absentees_statement.html')

@app.route('/api/departments', methods=['GET'])
def api_get_departments():
    """API endpoint to fetch all departments from DEPARTMENT_CODES"""
    try:
        # Get all departments from the DEPARTMENT_CODES dictionary
        # Exclude 'ALL' from the main list (it will be added separately if needed)
        dept_list = sorted([dept for dept in DEPARTMENT_CODES.keys() if dept != 'ALL'])
        
        return jsonify({
            'departments': dept_list,
            'count': len(dept_list)
        })
    
    except Exception as e:
        print(f"[ERROR] Error fetching departments: {str(e)}", flush=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/exams', methods=['GET'])
def api_get_exams():
    """API endpoint to fetch all exams with their details"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT exam_code, subject, semester, department, exam_date, exam_session
            FROM exams
            ORDER BY semester, exam_code
        """)
        
        exams = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return jsonify({
            'exams': exams,
            'count': len(exams)
        })
    
    except Exception as e:
        print(f"[ERROR] Error fetching exams: {str(e)}", flush=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/absentees-statement', methods=['GET'])
def api_absentees_statement():
    """API endpoint to fetch absentees statement data for selected department"""
    department = request.args.get('department', '').upper()
    
    if not department:
        return jsonify({'error': 'Department not specified'}), 400
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get all exams for this department
        cursor.execute("""
            SELECT DISTINCT exam_code, exam_date, exam_session,
                   department, subject
            FROM exams
            WHERE UPPER(department) = %s
            ORDER BY exam_date
        """, (department,))
        
        exams = cursor.fetchall()
        
        exams_data = []
        
        for exam in exams:
            exam_code = exam['exam_code']
            exam_date = exam['exam_date']
            exam_session = exam['exam_session']
            subject = exam.get('subject', '')
            
            # Get total students for this exam from exam_seating
            cursor.execute("""
                SELECT COUNT(DISTINCT roll_no) as total
                FROM exam_seating
                WHERE exam_code = %s
            """, (exam_code,))
            
            total_result = cursor.fetchone()
            total_students = total_result['total'] if total_result else 0
            
            # Get absentees for this exam
            cursor.execute("""
                SELECT DISTINCT es.roll_no, s.name, es.is_absent
                FROM exam_seating es
                LEFT JOIN students s ON es.roll_no = s.roll_no
                WHERE es.exam_code = %s
                  AND CAST(COALESCE(es.is_absent, 0) AS UNSIGNED) = 1
                ORDER BY es.roll_no
            """, (exam_code,))
            
            absentees = cursor.fetchall()
            
            # Format exam time
            exam_time = exam_session if exam_session else '--'
            
            exams_data.append({
                'exam_code': exam_code,
                'subject': subject,
                'exam_date': str(exam_date) if exam_date else '--',
                'exam_time': exam_time,
                'total_students': total_students,
                'absent_count': len(absentees),
                'absentees': absentees
            })
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'department': department,
            'exams': exams_data,
            'total_exams': len(exams_data)
        })
    
    except Exception as e:
        print(f"[ERROR] Error fetching absentees statement: {str(e)}", flush=True)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    init_db()
    # allocate seating for any pre-existing/upcoming exams on startup
    try:
        allocate_seating_for_all_upcoming_exams()
    except Exception as e:
        print(f"[WARNING] Seating refresh on startup failed: {e}")
    app.run(debug=True)