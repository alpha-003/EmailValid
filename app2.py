from flask import Flask, render_template, request, jsonify, send_file, after_this_request
from werkzeug.utils import secure_filename
from csv import DictReader, reader
import os
import uuid
import threading
import csv
import re
import dns.resolver
import smtplib
import tempfile
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Dict, List

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
app.config.update({
    'MAX_CONTENT_LENGTH': 500 * 1024 * 1024,
    'UPLOAD_FOLDER': tempfile.gettempdir(),
    'ALLOWED_EXTENSIONS': {'csv'},
    'DISPOSABLE_DOMAINS_PATH': 'disposable_domains.txt',
    'ROLE_PREFIXES': ['admin', 'support', 'info', 'sales', 'contact', 'noreply', 'team', 'help'],
    'CACHE_TIMEOUT': 3600,
    'MAX_WORKERS': 10,
    'SMTP_TIMEOUT': 15,
    'SMTP_RETRIES': 3,
    'BATCH_SIZE': 100
})

tasks = {}
executor_lock = Lock()

class EmailValidator:
    def __init__(self):
        self.disposable_domains = self.load_disposable_domains()
        self.cache = {}
        self.cache_timestamps = {}
        self.cache_lock = Lock()
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
            'is_valid': False,
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
                local_part.lower().startswith(prefix.lower())
                for prefix in self.role_prefixes
            )

            # Domain validation with caching
            result['domain_valid'] = self.check_domain(domain)
            if not result['domain_valid']:
                raise ValueError("Domain validation failed")

            # SMTP validation with retries
            result['smtp_valid'] = self.check_smtp_with_retries(email, domain)

            # Catch-all check
            result['is_catch_all'] = self.check_catch_all(domain)

            # Final validity check
            result['is_valid'] = all([
                result['smtp_valid'],
                not result['is_catch_all'],
                result['syntax_valid'],
                result['domain_valid'],
                not result['is_disposable'],
                not result['is_role']
            ])

        except Exception as e:
            result['errors'].append(str(e))
            logger.debug(f"Validation error for {email}: {str(e)}")

        return result

    def check_domain(self, domain: str) -> bool:
        with self.cache_lock:
            # Check cache with TTL validation
            if domain in self.cache:
                age = datetime.now() - self.cache_timestamps[domain]
                if age.total_seconds() < app.config['CACHE_TIMEOUT']:
                    return self.cache[domain]
        
        try:
            mx_records = dns.resolver.resolve(domain, 'MX')
            valid = len(mx_records) > 0
            with self.cache_lock:
                self.cache[domain] = valid
                self.cache_timestamps[domain] = datetime.now()
            return valid
        except dns.resolver.NXDOMAIN:
            logger.error(f"Domain {domain} does not exist")
            return False
        except Exception as e:
            with self.cache_lock:
                self.cache[domain] = False
                self.cache_timestamps[domain] = datetime.now()
            return False

    def check_smtp_with_retries(self, email: str, domain: str) -> bool:
        for attempt in range(1, app.config['SMTP_RETRIES'] + 1):
            try:
                # Get sorted MX records by priority
                mx_records = sorted(dns.resolver.resolve(domain, 'MX'),
                                key=lambda x: x.preference)
                
                for record in mx_records:
                    try:
                        mx_server = str(record.exchange)
                        with smtplib.SMTP(mx_server, 
                                       timeout=app.config['SMTP_TIMEOUT']) as server:
                            server.docmd('EHLO example.com')
                            server.docmd(f'MAIL FROM:<verify@{domain}>')
                            code, _ = server.docmd(f'RCPT TO:<{email}>')
                            if code == 250:
                                return True
                    except smtplib.SMTPException as e:
                        logger.debug(f"Trying next MX server for {email}")
                        continue
                break  # Exit if any MX server succeeded
            except Exception as e:
                logger.debug(f"SMTP attempt {attempt} failed for {email}: {str(e)}")
        return False

    def check_catch_all(self, domain: str) -> bool:
        test_emails = [
            f'test-{datetime.now().timestamp()}@{domain}',
            f'invalid-{uuid.uuid4().hex}@{domain}'
        ]
        return all(self.check_smtp_with_retries(email, domain) for email in test_emails)

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
                self.total_rows = max(self.total_rows, 1)

            self.result_file = os.path.join(app.config['UPLOAD_FOLDER'], f'results_{self.task_id}.csv')
            
            with open(self.file_path, 'r', encoding='utf-8') as infile, \
                 open(self.result_file, 'w', newline='', encoding='utf-8', buffering=1) as outfile:

                if self.has_headers:
                    csv_reader = DictReader(infile)
                    get_email = lambda row: row.get(self.email_column, '')
                else:
                    csv_reader = reader(infile)
                    col_index = int(self.email_column)
                    get_email = lambda row: row[col_index] if len(row) > col_index else ''

                writer = csv.writer(outfile)
                writer.writerow([
                    'Email', 'Valid Syntax', 'MX Recoard', 'SMTP Valid',
                    'Disposable', 'Role Account', 'Catch-All Domain', 
                    'Is Valid', 'Errors'
                ])

                # Process in parallel batches
                with ThreadPoolExecutor(max_workers=app.config['MAX_WORKERS']) as executor:
                    batch_size = app.config['BATCH_SIZE']
                    rows = []
                    valid_emails = []

                    for row_num, row in enumerate(csv_reader):
                        if self.has_headers and row_num == 0:
                            continue  # Skip header
                        email = get_email(row).strip()
                        if email:
                            rows.append((row_num, row, email))
                            valid_emails.append(email)

                    # Process in complete batches
                    for i in range(0, len(valid_emails), batch_size):
                        batch = valid_emails[i:i + batch_size]
                        results = list(executor.map(validator.validate, batch))
                        
                        # Write results
                        for result in results:
                            writer.writerow([
                                result['email'],
                                result['syntax_valid'],
                                result['domain_valid'],
                                result['smtp_valid'],
                                result['is_disposable'],
                                result['is_role'],
                                result['is_catch_all'],
                                result['is_valid'],
                                '; '.join(result['errors'])
                            ])
                            self.processed_rows += 1
                            self.progress = min(100, int((self.processed_rows / self.total_rows) * 100))

                    # Process remaining emails
                    remaining = valid_emails[i + batch_size:]
                    if remaining:
                        results = list(executor.map(validator.validate, remaining))
                        for result in results:
                            writer.writerow([
                                result['email'],
                                result['syntax_valid'],
                                result['domain_valid'],
                                result['smtp_valid'],
                                result['is_disposable'],
                                result['is_role'],
                                result['is_catch_all'],
                                result['is_valid'],
                                '; '.join(result['errors'])
                            ])
                            self.processed_rows += 1
                            self.progress = min(100, int((self.processed_rows / self.total_rows) * 100))

            self.progress = 100
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

        filename = secure_filename(file.filename)
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"upload_{uuid.uuid4()}.csv")
        file.save(temp_path)

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
        download_name=f'validation_results_{task_id}.csv'
    )

def allowed_file(filename: str) -> bool:
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)