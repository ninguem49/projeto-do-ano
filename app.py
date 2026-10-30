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
