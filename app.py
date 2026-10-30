import os
from datetime import datetime
from zoneinfo import ZoneInfo
from functools import wraps
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, jsonify, render_template, request, session, g, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

def format_brasilia_datetime(value):
    if not value:
        return ''

    value = value.replace(tzinfo=ZoneInfo('UTC'))
    return value.astimezone(
        ZoneInfo('America/Sao_Paulo')
    ).strftime('%d/%m/%Y %H:%M')
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / 'uploads'
UPLOAD_DIR.mkdir(exist_ok=True)
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt', 'png', 'jpg', 'jpeg', 'webp'}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'chave-apenas-para-teste-local')
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_BYTES
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

DATABASE_URL = os.getenv('DATABASE_URL')

def init_db():
    schema_path = BASE_DIR / 'schema.sql'

    with open(schema_path, 'r', encoding='utf-8') as file:
        schema = file.read()

    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(schema)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

init_db()

def db():
    if 'db' not in g:
        if not DATABASE_URL:
            raise RuntimeError('A variável DATABASE_URL não foi configurada.')
        g.db = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    conn = g.pop('db', None)
    if conn is not None:
        conn.close()


def query(sql, params=(), one=False, commit=False):
    conn = db()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchone() if one else cur.fetchall()
        if commit:
            conn.commit()
        return rows


def execute(sql, params=()):
    conn = db()
    statement = sql.strip().rstrip(';')
    wants_id = statement[:6].upper() == 'INSERT' and 'RETURNING' not in statement.upper()
    if wants_id:
        statement += ' RETURNING id'
    with conn.cursor() as cur:
        cur.execute(statement, params)
        last_id = cur.fetchone()['id'] if wants_id else None
    conn.commit()
    return last_id


def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    return query('SELECT id, name, email, profession, bio, location, portfolio_url, avatar FROM users WHERE id=%s', (uid,), one=True)


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return jsonify({'error': 'Entre na sua conta para continuar.'}), 401
        return fn(*args, **kwargs)
    return wrapped


def clean_text(value, limit=2000):
    return str(value or '').strip()[:limit]


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.get('/')
def index():
    return render_template('index.html')


@app.get('/api/me')
def me():
    user = current_user()
    return jsonify({'user': user})


@app.post('/api/register')
def register():
    data = request.get_json(silent=True) or {}
    name = clean_text(data.get('name'), 80)
    email = clean_text(data.get('email'), 190).lower()
    password = str(data.get('password') or '')
    if len(name) < 2 or '@' not in email or len(password) < 8:
        return jsonify({'error': 'Informe nome, e-mail válido e senha com pelo menos 8 caracteres.'}), 400
    if query('SELECT id FROM users WHERE email=%s', (email,), one=True):
        return jsonify({'error': 'Esse e-mail já está cadastrado.'}), 409
    uid = execute('INSERT INTO users (name,email,password_hash) VALUES (%s,%s,%s)',
                  (name, email, generate_password_hash(password)))
    session.clear()
    session['user_id'] = uid
    return jsonify({'user': current_user()}), 201


@app.post('/api/login')
def login():
    data = request.get_json(silent=True) or {}
    email = clean_text(data.get('email'), 190).lower()
    password = str(data.get('password') or '')
    user = query('SELECT id,password_hash FROM users WHERE email=%s', (email,), one=True)
    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'error': 'E-mail ou senha incorretos.'}), 401
    session.clear()
    session['user_id'] = user['id']
    return jsonify({'user': current_user()})


@app.post('/api/logout')
@login_required
def logout():
    session.clear()
    return jsonify({'ok': True})


@app.patch('/api/profile')
@login_required
def update_profile():
    data = request.get_json(silent=True) or {}
    name = clean_text(data.get('name'), 80)
    profession = clean_text(data.get('profession'), 100)
    bio = clean_text(data.get('bio'), 500)
    location = clean_text(data.get('location'), 120)
    portfolio = clean_text(data.get('portfolio_url'), 250)
    if len(name) < 2:
        return jsonify({'error': 'O nome precisa ter pelo menos 2 caracteres.'}), 400
    execute('UPDATE users SET name=%s, profession=%s, bio=%s, location=%s, portfolio_url=%s WHERE id=%s',
            (name, profession, bio, location, portfolio, session['user_id']))
    return jsonify({'user': current_user()})


@app.post('/api/avatar')
@login_required
def upload_avatar():
    file = request.files.get('avatar')
    if not file or not file.filename or '.' not in file.filename or file.filename.rsplit('.', 1)[1].lower() not in {'png', 'jpg', 'jpeg', 'webp'}:
        return jsonify({'error': 'Escolha uma imagem PNG, JPG ou WEBP.'}), 400
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"avatar_{session['user_id']}.{ext}"
    file.save(UPLOAD_DIR / filename)
    url = f'/uploads/{filename}'
    execute('UPDATE users SET avatar=%s WHERE id=%s', (url, session['user_id']))
    return jsonify({'avatar': url})


@app.get('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=False)


@app.get('/api/channels')
@login_required
def channels():
    rows = query('SELECT id,name,created_by FROM channels ORDER BY id')
    return jsonify({'channels': rows})


@app.post('/api/channels')
@login_required
def create_channel():
    data = request.get_json(silent=True) or {}
    name = clean_text(data.get('name'), 50).strip().lower().replace(' ', '-')
    if len(name) < 2 or not all(c.isalnum() or c in '-_' for c in name):
        return jsonify({'error': 'Use pelo menos 2 caracteres: letras, números, hífen ou underline.'}), 400
    if query('SELECT id FROM channels WHERE name=%s', (name,), one=True):
        return jsonify({'error': 'Esse canal já existe.'}), 409
    cid = execute('INSERT INTO channels (name,created_by) VALUES (%s,%s)', (name, session['user_id']))
    return jsonify({'channel': {'id': cid, 'name': name, 'created_by': session['user_id']}}), 201


@app.get('/api/channels/<int:channel_id>/messages')
@login_required
def get_messages(channel_id):
    if not query('SELECT id FROM channels WHERE id=%s', (channel_id,), one=True):
        return jsonify({'error': 'Canal não encontrado.'}), 404
    after = request.args.get('after', type=int, default=0)
    rows = query('''SELECT m.id,m.channel_id,m.user_id,m.body,m.attachment,m.created_at,m.pinned,u.name AS user_name,u.avatar
                    FROM messages m JOIN users u ON u.id=m.user_id
                    WHERE m.channel_id=%s AND m.id>%s ORDER BY m.id ASC LIMIT 200''', (channel_id, after))
    for row in rows:
        row['created_at'] = row['created_at'].strftime('%d/%m/%Y %H:%M') if row.get('created_at') else ''
        row['pinned'] = bool(row['pinned'])
    return jsonify({'messages': rows})


@app.post('/api/channels/<int:channel_id>/messages')
@login_required
def send_message(channel_id):
    if not query('SELECT id FROM channels WHERE id=%s', (channel_id,), one=True):
        return jsonify({'error': 'Canal não encontrado.'}), 404
    body = clean_text((request.form.get('body') if request.form else None) or ((request.get_json(silent=True) or {}).get('body')), 2000)
    attachment_url = None
    file = request.files.get('file')
    if file and file.filename:
        if not allowed_file(file.filename):
            return jsonify({'error': 'Tipo de arquivo não permitido.'}), 400
        ext = file.filename.rsplit('.', 1)[1].lower()
        safe_name = secure_filename(file.filename)[:100]
        filename = f"msg_{session['user_id']}_{int(datetime.now().timestamp()*1000)}_{safe_name}"
        file.save(UPLOAD_DIR / filename)
        attachment_url = f'/uploads/{filename}'
    if not body and not attachment_url:
        return jsonify({'error': 'Escreva uma mensagem ou anexe um arquivo.'}), 400
    mid = execute('INSERT INTO messages (channel_id,user_id,body,attachment) VALUES (%s,%s,%s,%s)',
                  (channel_id, session['user_id'], body, attachment_url))
    return jsonify({'id': mid}), 201


@app.post('/api/messages/<int:message_id>/pin')
@login_required
def pin_message(message_id):
    row = query('SELECT id,pinned FROM messages WHERE id=%s', (message_id,), one=True)
    if not row:
        return jsonify({'error': 'Mensagem não encontrada.'}), 404
    new_value = 0 if row['pinned'] else 1
    execute('UPDATE messages SET pinned=%s WHERE id=%s', (new_value, message_id))
    return jsonify({'pinned': bool(new_value)})


@app.get('/api/search')
@login_required
def search_messages():
    term = clean_text(request.args.get('q'), 100)
    if not term:
        return jsonify({'results': []})
    like = '%' + term + '%'
    rows = query('''SELECT m.id,m.channel_id,m.body,m.created_at,c.name AS channel_name,u.name AS user_name
                    FROM messages m JOIN channels c ON c.id=m.channel_id JOIN users u ON u.id=m.user_id
                    WHERE m.body LIKE %s OR u.name LIKE %s ORDER BY m.id DESC LIMIT 50''', (like, like))
    for row in rows:
        row['created_at'] = row['created_at'].strftime('%d/%m/%Y %H:%M') if row.get('created_at') else ''
    return jsonify({'results': rows})


@app.get('/api/pinned')
@login_required
def pinned_messages():
    rows = query('''SELECT m.id,m.channel_id,m.body,m.created_at,c.name AS channel_name,u.name AS user_name
                    FROM messages m JOIN channels c ON c.id=m.channel_id JOIN users u ON u.id=m.user_id
                    WHERE m.pinned=1 ORDER BY m.id DESC LIMIT 100''')
    for row in rows:
        row['created_at'] = row['created_at'].strftime('%d/%m/%Y %H:%M') if row.get('created_at') else ''
    return jsonify({'results': rows})


@app.get('/api/members')
@login_required
def members():
    # Lista de membros cadastrados. Presença em tempo real exigiria heartbeat/websocket.
    rows = query('SELECT id,name,profession,avatar FROM users ORDER BY name LIMIT 100')
    return jsonify({'members': rows})


@app.get('/api/jobs')
@login_required
def jobs():
    term = clean_text(request.args.get('q'), 100)
    params = []
    sql = '''SELECT j.id,j.title,j.company,j.area,j.description,j.location,j.work_type,j.pay,j.deadline,j.created_at,j.user_id,u.name AS author,
             EXISTS(SELECT 1 FROM saved_jobs s WHERE s.job_id=j.id AND s.user_id=%s) AS saved
             FROM jobs j JOIN users u ON u.id=j.user_id WHERE j.status='open' '''
    params.append(session['user_id'])
    if term:
        like = '%' + term + '%'
        sql += ' AND (j.title LIKE %s OR j.area LIKE %s OR j.location LIKE %s OR j.description LIKE %s)'
        params.extend([like, like, like, like])
    sql += ' ORDER BY j.id DESC'
    rows = query(sql, tuple(params))
    for row in rows:
        row['saved'] = bool(row['saved'])
        row['created_at'] = row['created_at'].strftime('%d/%m/%Y') if row.get('created_at') else ''
        if row.get('deadline'):
            row['deadline'] = row['deadline'].strftime('%Y-%m-%d')
    return jsonify({'jobs': rows})


@app.post('/api/jobs')
@login_required
def create_job():
    data = request.get_json(silent=True) or {}
    title = clean_text(data.get('title'), 120)
    company = clean_text(data.get('company'), 120)
    area = clean_text(data.get('area'), 80)
    description = clean_text(data.get('description'), 4000)
    location = clean_text(data.get('location'), 150)
    work_type = clean_text(data.get('work_type'), 40)
    pay = clean_text(data.get('pay'), 100)
    deadline = clean_text(data.get('deadline'), 10) or None
    if not title or not area or not description:
        return jsonify({'error': 'Preencha título, área e descrição.'}), 400
    if deadline:
        try:
            datetime.strptime(deadline, '%Y-%m-%d')
        except ValueError:
            return jsonify({'error': 'Data limite inválida.'}), 400
    jid = execute('''INSERT INTO jobs (user_id,title,company,area,description,location,work_type,pay,deadline)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                  (session['user_id'], title, company, area, description, location, work_type, pay, deadline))
    return jsonify({'id': jid}), 201


@app.get('/api/jobs/mine')
@login_required
def my_jobs():
    rows = query('''SELECT j.*, (SELECT COUNT(*) FROM applications a WHERE a.job_id=j.id) AS applicants,
                    (SELECT COUNT(*) FROM saved_jobs s WHERE s.job_id=j.id) AS saves
                    FROM jobs j WHERE j.user_id=%s ORDER BY j.id DESC''', (session['user_id'],))
    for row in rows:
        row['created_at'] = row['created_at'].strftime('%d/%m/%Y') if row.get('created_at') else ''
        if row.get('deadline'):
            row['deadline'] = row['deadline'].strftime('%Y-%m-%d')
    return jsonify({'jobs': rows})


@app.patch('/api/jobs/<int:job_id>')
@login_required
def close_job(job_id):
    job = query('SELECT id,status FROM jobs WHERE id=%s AND user_id=%s', (job_id, session['user_id']), one=True)
    if not job:
        return jsonify({'error': 'Vaga não encontrada ou você não é o responsável.'}), 404
    data = request.get_json(silent=True) or {}
    status = data.get('status', 'closed')
    if status not in ('open', 'closed'):
        return jsonify({'error': 'Status inválido.'}), 400
    execute('UPDATE jobs SET status=%s WHERE id=%s', (status, job_id))
    return jsonify({'ok': True})


@app.post('/api/jobs/<int:job_id>/save')
@login_required
def save_job(job_id):
    if not query('SELECT id FROM jobs WHERE id=%s', (job_id,), one=True):
        return jsonify({'error': 'Vaga não encontrada.'}), 404
    existing = query('SELECT id FROM saved_jobs WHERE job_id=%s AND user_id=%s', (job_id, session['user_id']), one=True)
    if existing:
        execute('DELETE FROM saved_jobs WHERE id=%s', (existing['id'],))
        return jsonify({'saved': False})
    execute('INSERT INTO saved_jobs (job_id,user_id) VALUES (%s,%s)', (job_id, session['user_id']))
    return jsonify({'saved': True})


@app.get('/api/jobs/saved')
@login_required
def saved_jobs():
    rows = query('''SELECT j.id,j.title,j.company,j.area,j.description,j.location,j.work_type,j.pay,j.deadline,j.created_at,j.user_id,u.name AS author
                    FROM saved_jobs s JOIN jobs j ON j.id=s.job_id JOIN users u ON u.id=j.user_id
                    WHERE s.user_id=%s ORDER BY s.id DESC''', (session['user_id'],))
    for row in rows:
        row['created_at'] = row['created_at'].strftime('%d/%m/%Y') if row.get('created_at') else ''
        if row.get('deadline'):
            row['deadline'] = row['deadline'].strftime('%Y-%m-%d')
    return jsonify({'jobs': rows})


@app.post('/api/jobs/<int:job_id>/apply')
@login_required
def apply_job(job_id):
    job = query('SELECT id,user_id,status FROM jobs WHERE id=%s', (job_id,), one=True)
    if not job or job['status'] != 'open':
        return jsonify({'error': 'Essa vaga não está mais disponível.'}), 404
    if job['user_id'] == session['user_id']:
        return jsonify({'error': 'Você não pode se candidatar à sua própria vaga.'}), 400
    data = request.get_json(silent=True) or {}
    message = clean_text(data.get('message'), 1000)
    existing = query('SELECT id FROM applications WHERE job_id=%s AND user_id=%s', (job_id, session['user_id']), one=True)
    if existing:
        return jsonify({'error': 'Você já se candidatou a essa vaga.'}), 409
    aid = execute('INSERT INTO applications (job_id,user_id,message) VALUES (%s,%s,%s)', (job_id, session['user_id'], message))
    return jsonify({'id': aid}), 201


@app.get('/api/applications/mine')
@login_required
def my_applications():
    rows = query('''SELECT a.id,a.status,a.message,a.created_at,j.id AS job_id,j.title,j.company,j.area,u.name AS employer
                    FROM applications a JOIN jobs j ON j.id=a.job_id JOIN users u ON u.id=j.user_id
                    WHERE a.user_id=%s ORDER BY a.id DESC''', (session['user_id'],))
    for row in rows:
        row['created_at'] = row['created_at'].strftime('%d/%m/%Y %H:%M') if row.get('created_at') else ''
    return jsonify({'applications': rows})


@app.get('/api/jobs/<int:job_id>/applications')
@login_required
def job_applications(job_id):
    job = query('SELECT id FROM jobs WHERE id=%s AND user_id=%s', (job_id, session['user_id']), one=True)
    if not job:
        return jsonify({'error': 'Você não tem permissão para ver essas candidaturas.'}), 403
    rows = query('''SELECT a.id,a.status,a.message,a.created_at,u.name,u.email,u.profession,u.bio,u.location,u.portfolio_url,u.avatar
                    FROM applications a JOIN users u ON u.id=a.user_id WHERE a.job_id=%s ORDER BY a.id DESC''', (job_id,))
    for row in rows:
        row['created_at'] = row['created_at'].strftime('%d/%m/%Y %H:%M') if row.get('created_at') else ''
    return jsonify({'applications': rows})


@app.patch('/api/applications/<int:application_id>')
@login_required
def update_application(application_id):
    data = request.get_json(silent=True) or {}
    status = data.get('status')
    if status not in ('received', 'reviewing', 'selected', 'rejected'):
        return jsonify({'error': 'Status inválido.'}), 400
    row = query('''SELECT a.id FROM applications a JOIN jobs j ON j.id=a.job_id
                   WHERE a.id=%s AND j.user_id=%s''', (application_id, session['user_id']), one=True)
    if not row:
        return jsonify({'error': 'Candidatura não encontrada ou sem permissão.'}), 404
    execute('UPDATE applications SET status=%s WHERE id=%s', (status, application_id))
    return jsonify({'ok': True})


@app.get('/api/jobs/<int:job_id>/savers')
@login_required
def job_savers(job_id):
    job = query('SELECT id FROM jobs WHERE id=%s AND user_id=%s', (job_id, session['user_id']), one=True)
    if not job:
        return jsonify({'error': 'Você não tem permissão para ver esses dados.'}), 403
    # Privacidade: apenas a contagem é exposta, não os nomes dos usuários que salvaram.
    row = query('SELECT COUNT(*) AS total FROM saved_jobs WHERE job_id=%s', (job_id,), one=True)
    return jsonify({'total': row['total']})


@app.errorhandler(413)
def too_large(_error):
    return jsonify({'error': 'O arquivo é muito grande. O limite é 8 MB.'}), 413


@app.errorhandler(500)
def server_error(_error):
    app.logger.exception('Erro interno')
    return jsonify({'error': 'Ocorreu um erro no servidor. Confira o terminal para mais detalhes.'}), 500


if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
