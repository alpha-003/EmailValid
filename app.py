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
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Application configuration
app.config.update({
    'MAX_CONTENT_LENGTH': 500 * 1024 * 1024,
    'UPLOAD_FOLDER': tempfile.gettempdir(),
    'ALLOWED_EXTENSIONS': {'csv'},
    'DISPOSABLE_DOMAINS_PATH': 'disposable_domains.txt',
    'ROLE_PREFIXES': ['admin', 'support', 'info', 'sales', 'contact'],
    'CACHE_TIMEOUT': 3600,
    'MAX_WORKERS': 20,
    'DNS_SERVERS': ['8.8.8.8', '8.8.4.4'],
    'SMTP_TIMEOUT': 10
})

tasks = {}

class EmailValidator:
    # Shared resources with thread-safe access
    EMAIL_REGEX = re.compile(r'^[\w\.\+\-]+\@[a-zA-Z0-9\-]+\.[a-zA-Z0-9\-\.]+$')
    _disposable_domains = None
    _domain_cache = {}
    _catch_all_cache = {}
    _cache_lock = threading.Lock()
    _catch_all_lock = threading.Lock()

    def __init__(self):
        self._load_disposable_domains()
        self.resolver = dns.resolver.Resolver()
        self.resolver.nameservers = app.config['DNS_SERVERS']

    def _load_disposable_domains(self):
        """Load disposable domains once during initialization"""
        if self.__class__._disposable_domains is None:
            try:
                with open(app.config['DISPOSABLE_DOMAINS_PATH']) as f:
                    self.__class__._disposable_domains = {line.strip() for line in f}
            except FileNotFoundError:
                logger.warning("Disposable domains file not found")
                self.__class__._disposable_domains = set()

    def validate(self, email: str) -> dict:
        """Validate email with optimized checks and early exits"""
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
            # Fast syntax validation
            if not self.EMAIL_REGEX.match(email):
                raise ValueError("Invalid email syntax")
            
            result['syntax_valid'] = True
            local_part, domain = email.split('@', 1)

            # Early exit for disposable domains
            if domain in self._disposable_domains:
                result['is_disposable'] = True
                return result

            # Role-based account detection
            result['is_role'] = any(
                local_part.lower().startswith(prefix)
                for prefix in app.config['ROLE_PREFIXES']
            )

            # Domain validation with caching
            result['domain_valid'] = self.check_domain(domain)
            if not result['domain_valid']:
                raise ValueError("Domain validation failed")

            # SMTP validation
            result['smtp_valid'] = self.check_smtp(email, domain)
            
            # Catch-all domain check
            result['is_catch_all'] = self.check_catch_all(domain)

        except Exception as e:
            result['errors'].append(str(e))

        return result

    def check_domain(self, domain: str) -> bool:
        """Check domain MX records with caching"""
        now = time.time()
        with self._cache_lock:
            cached = self._domain_cache.get(domain)
            if cached and (now - cached[1]) < app.config['CACHE_TIMEOUT']:
                return cached[0]

        try:
            mx_records = self.resolver.resolve(domain, 'MX', lifetime=5)
            valid = len(mx_records) > 0
            with self._cache_lock:
                self._domain_cache[domain] = (valid, now)
            return valid
        except Exception as e:
            logger.debug(f"Domain check failed: {str(e)}")
            with self._cache_lock:
                self._domain_cache[domain] = (False, now)
            return False

    def check_smtp(self, email: str, domain: str) -> bool:
        """Perform SMTP check with timeout"""
        try:
            mx_records = self.resolver.resolve(domain, 'MX', lifetime=5)
            mx_server = str(mx_records[0].exchange)
            
            with smtplib.SMTP(mx_server, timeout=app.config['SMTP_TIMEOUT']) as server:
                server.docmd('HELO example.com')
                server.docmd(f'MAIL FROM:<verify@{domain}>')
                code, _ = server.docmd(f'RCPT TO:<{email}>')
                return code == 250
        except Exception as e:
            logger.debug(f"SMTP check failed: {str(e)}")
            return False

    def check_catch_all(self, domain: str) -> bool:
        """Check catch-all status with caching"""
        now = time.time()
        with self._catch_all_lock:
            cached = self._catch_all_cache.get(domain)
            if cached and (now - cached[1]) < app.config['CACHE_TIMEOUT']:
                return cached[0]

        test_email = f'test-{datetime.now().timestamp()}@{domain}'
        is_catch_all = self.check_smtp(test_email, domain)
        with self._catch_all_lock:
            self._catch_all_cache[domain] = (is_catch_all, now)
        return is_catch_all

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

    def process(self):
        """Process CSV file with parallel validation"""
        try:
            self.status = 'processing'
            validator = EmailValidator()
            emails = []

            # Collect emails from CSV
            with open(self.file_path, 'r', encoding='utf-8') as f:
                csv_reader = DictReader(f) if self.has_headers else reader(f)
                if self.has_headers:
                    next(csv_reader)  # Skip header row
                
                for row in csv_reader:
                    email = (row[self.email_column] if self.has_headers 
                            else row[int(self.email_column)]).strip()
                    if email:
                        emails.append(email)

            self.total_rows = len(emails)
            if self.total_rows == 0:
                raise ValueError("No valid emails found")

            # Parallel validation
            with ThreadPoolExecutor(max_workers=app.config['MAX_WORKERS']) as executor:
                results = list(executor.map(validator.validate, emails))

            # Write results to CSV
            self.result_file = os.path.join(app.config['UPLOAD_FOLDER'], f'results_{self.task_id}.csv')
            with open(self.result_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'Email', 'Valid Syntax', 'Valid Domain', 'SMTP Valid',
                    'Disposable', 'Role Account', 'Catch-All Domain', 'Errors'
                ])
                
                for idx, result in enumerate(results):
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
                    self.processed_rows = idx + 1
                    self.progress = min(100, int((self.processed_rows / self.total_rows) * 100))

            self.status = 'completed'
            logger.info(f"Task {self.task_id} completed successfully")

        except Exception as e:
            logger.error(f"Task {self.task_id} failed: {str(e)}")
            self.status = 'failed'
            self.error = str(e)
        finally:
            try:
                os.remove(self.file_path)
            except Exception as e:
                logger.error(f"Error cleaning up input file: {str(e)}")

# Flask Routes
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

        # Validate CSV structure
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