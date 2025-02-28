from flask import Flask, render_template, request, jsonify, send_file, after_this_request #Shalini
from werkzeug.utils import secure_filename   #Anand
from csv import DictReader, reader  #Anand
import os  #Anand
import uuid #Anand
import threading #Shalini && Anand
import csv
import re  #Shalini
import dns.resolver   #Shalini && Anand
import smtplib    #Shalini && Anand
import tempfile     #Anand
import logging   #Shalaini
from datetime import datetime
from typing import List, Dict, Union #Shalini && Anand

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
app.config.update({
    'MAX_CONTENT_LENGTH': 500 * 1024 * 1024,  # 500MB
    'UPLOAD_FOLDER': tempfile.gettempdir(),
    'ALLOWED_EXTENSIONS': {'csv'},
    'DISPOSABLE_DOMAINS_PATH': 'disposable_domains.txt',
    'ROLE_PREFIXES': ['admin', 'support', 'info', 'sales', 'contact'],
    'CACHE_TIMEOUT': 3600  # 1 hour
})

tasks = {}

class EmailValidator:
    def __init__(self):
        self.disposable_domains = self.load_disposable_domains()
        self.cache = {}
        self.role_prefixes = app.config['ROLE_PREFIXES']
        
    def load_disposable_domains(self) -> set:
        try:
            with open(app.config['DISPOSABLE_DOMAINS_PATH']) as f:
                return {line.strip() for line in f}
        except FileNotFoundError:
            logger.warning("Disposable domains file not found")
            return set()

    def validate(self, email: str) -> Dict:
        result = {
            'email': email,
            'syntax_valid': False,
            'domain_valid': False,
            'smtp_valid': False,
            'is_disposable': False,
            'is_role': False,
            'is_catch_all': False,
            'errors': []
        }

        try:
            # Syntax validation
            if not re.match(r'^[\w\.\+\-]+\@[a-zA-Z0-9\-]+\.[a-zA-Z0-9\-\.]+$', email):
                raise ValueError("Invalid email syntax")
            
            result['syntax_valid'] = True
            local_part, domain = email.split('@')

            # Disposable check
            result['is_disposable'] = domain in self.disposable_domains

            # Role-based check
            result['is_role'] = any(
                local_part.lower().startswith(prefix)
                for prefix in self.role_prefixes
            )

            # Domain validation with caching
            result['domain_valid'] = self.check_domain(domain)
            if not result['domain_valid']:
                raise ValueError("Domain validation failed")

            # SMTP validation
            result['smtp_valid'] = self.check_smtp(email, domain)

            # Catch-all check
            result['is_catch_all'] = self.check_catch_all(domain)

        except Exception as e:
            result['errors'].append(str(e))
            logger.debug(f"Validation error for {email}: {str(e)}")

        return result

    def check_domain(self, domain: str) -> bool:
        if domain in self.cache:
            return self.cache[domain]
        
        try:
            mx_records = dns.resolver.resolve(domain, 'MX')
            valid = len(mx_records) > 0
            self.cache[domain] = valid
            return valid
        except Exception as e:
            logger.debug(f"Domain check failed for {domain}: {str(e)}")
            return False

    def check_smtp(self, email: str, domain: str) -> bool:
        try:
            mx_records = dns.resolver.resolve(domain, 'MX')
            mx_server = str(mx_records[0].exchange)
            
            with smtplib.SMTP(mx_server, timeout=10) as server:
                server.docmd('HELO example.com')
                server.docmd(f'MAIL FROM:<verify@{domain}>')
                code, _ = server.docmd(f'RCPT TO:<{email}>')
                return code == 250
        except Exception as e:
            logger.debug(f"SMTP check failed for {email}: {str(e)}")
            return False

    def check_catch_all(self, domain: str) -> bool:
        try:
            test_email = f'test-{datetime.now().timestamp()}@{domain}'
            return self.check_smtp(test_email, domain)
        except Exception as e:
            logger.debug(f"Catch-all check failed for {domain}: {str(e)}")
            return False

class ValidationTask:
    def __init__(self, file_path: str, email_column: str, has_headers: bool):
        self.task_id = str(uuid.uuid4())
        self.file_path = file_path
        self.email_column = email_column
        self.has_headers = has_headers
        self.progress = 0
        self.status = 'pending'
        self.result_file = None
        self.total_rows = 0
        self.processed_rows = 0
        tasks[self.task_id] = self
        logger.info(f"Created task {self.task_id}")

    def process(self):
        try:
            logger.info(f"Starting processing for task {self.task_id}")
            self.status = 'processing'
            validator = EmailValidator()

            # Count total rows
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.total_rows = sum(1 for _ in f) - (1 if self.has_headers else 0)
                self.total_rows = max(self.total_rows, 1)  # Prevent division by zero

            self.result_file = os.path.join(app.config['UPLOAD_FOLDER'], f'results_{self.task_id}.csv')
            
            with open(self.file_path, 'r', encoding='utf-8') as infile, \
                 open(self.result_file, 'w', newline='', encoding='utf-8') as outfile:

                # Configure reader based on headers
                if self.has_headers:
                    csv_reader = DictReader(infile)
                    get_email = lambda row: row.get(self.email_column, '')
                else:
                    csv_reader = reader(infile)
                    col_index = int(self.email_column)
                    get_email = lambda row: row[col_index] if len(row) > col_index else ''

                writer = csv.writer(outfile)
                writer.writerow([
                    'Email', 'Valid Syntax', 'Valid Domain', 'SMTP Valid',
                    'Disposable', 'Role Account', 'Catch-All Domain', 'Errors'
                ])

                for row_num, row in enumerate(csv_reader):
                    if self.has_headers and row_num == 0:
                        continue  # Skip header row

                    email = get_email(row).strip()
                    if not email:
                        continue

                    result = validator.validate(email)
                    writer.writerow([
                        result['email'],
                        result['syntax_valid'],
                        result['domain_valid'],
                        result['smtp_valid'],
                        result['is_disposable'],
                        result['is_role'],
                        result['is_catch_all'],
                        '; '.join(result['errors'])
                    ])
                    
                    self.processed_rows += 1
                    self.progress = min(100, int((self.processed_rows / self.total_rows) * 100))

            self.status = 'completed'
            logger.info(f"Completed task {self.task_id}")

        except Exception as e:
            logger.error(f"Task {self.task_id} failed: {str(e)}")
            self.status = 'failed'
            self.error = str(e)
        finally:
            try:
                os.remove(self.file_path)
            except Exception as e:
                logger.error(f"Error cleaning up input file: {str(e)}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def handle_upload():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
            
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
            
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type'}), 400

        email_column = request.form.get('email_column', '0')
        has_headers = request.form.get('has_headers', 'true').lower() == 'true'

        # Save uploaded file
        filename = secure_filename(file.filename)
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"upload_{uuid.uuid4()}.csv")
        file.save(temp_path)

        # Validate column exists
        with open(temp_path, 'r', encoding='utf-8') as f:
            if has_headers:
                try:
                    headers = next(reader(f))
                    if email_column not in headers:
                        return jsonify({'error': f'Column "{email_column}" not found'}), 400
                except StopIteration:
                    return jsonify({'error': 'Empty CSV file'}), 400
            else:
                try:
                    first_row = next(reader(f))
                    col_index = int(email_column)
                    if col_index >= len(first_row):
                        return jsonify({'error': f'Column index {col_index} out of range'}), 400
                except (ValueError, StopIteration):
                    return jsonify({'error': 'Invalid CSV format'}), 400

        # Create and start task
        task = ValidationTask(temp_path, email_column, has_headers)
        thread = threading.Thread(target=task.process)
        thread.start()
        
        return jsonify({
            'task_id': task.task_id,
            'status_url': f'/status/{task.task_id}',
            'download_url': f'/download/{task.task_id}'
        })

    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/status/<task_id>')
def get_status(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Invalid task ID'}), 404
        
    return jsonify({
        'status': task.status,
        'progress': task.progress,
        'error': getattr(task, 'error', None)
    })

@app.route('/download/<task_id>')
def download_results(task_id):
    task = tasks.get(task_id)
    if not task or task.status != 'completed':
        return jsonify({'error': 'Result not ready'}), 404
    
    @after_this_request
    def cleanup(response):
        try:
            if task.result_file and os.path.exists(task.result_file):
                os.remove(task.result_file)
            del tasks[task_id]
        except Exception as e:
            logger.error(f"Cleanup error: {str(e)}")
        return response
    
    return send_file(
        task.result_file,
        mimetype='text/csv',
        as_attachment=True,
        download_name='validation_results.csv'
    )

def allowed_file(filename: str) -> bool:
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)