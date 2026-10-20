"""Database-backed opaque sessions and shared Flask protections."""
import json
import re
import secrets
import time
from datetime import datetime, timezone
from flask import request, session, jsonify, current_app, abort, g
from flask.sessions import SessionInterface, SessionMixin
from flask_wtf.csrf import generate_csrf, CSRFError
from werkzeug.datastructures import CallbackDict
from werkzeug.exceptions import HTTPException
from markupsafe import escape
from storage import connect_database


class DatabaseSession(CallbackDict, SessionMixin):
    def __init__(self, data=None, sid=None):
        super().__init__(data, lambda obj: setattr(obj, 'modified', True))
        self.sid = sid
        self.modified = False
        self.rotate = False

    def clear(self):
        super().clear()
        self.rotate = True
        self.modified = True


class DatabaseSessionInterface(SessionInterface):
    def __init__(self, config):
        self.config = config

    def open_session(self, app, req):
        sid = req.cookies.get(self.get_cookie_name(app), '')
        if re.fullmatch(r'[A-Za-z0-9_-]{43}', sid):
            db = connect_database(self.config)
            try:
                row = db.execute('SELECT data FROM web_sessions WHERE id=? AND expires_at>?',
                                 (sid, time.time())).fetchone()
                if row:
                    return DatabaseSession(json.loads(row[0]), sid)
            finally:
                db.close()
        return DatabaseSession()

    def save_session(self, app, sess, response):
        if not sess.modified and sess.sid:
            return
        name = self.get_cookie_name(app)
        db = connect_database(self.config)
        try:
            if sess.rotate and sess.sid:
                db.execute('DELETE FROM web_sessions WHERE id=?', (sess.sid,))
                sess.sid = None
            if not sess:
                if sess.sid:
                    db.execute('DELETE FROM web_sessions WHERE id=?', (sess.sid,))
                db.commit()
                response.delete_cookie(name, path=self.get_cookie_path(app))
                return
            sess.sid = sess.sid or secrets.token_urlsafe(32)
            expires = time.time() + app.permanent_session_lifetime.total_seconds()
            db.execute('''INSERT INTO web_sessions(id,data,expires_at) VALUES(?,?,?)
                          ON CONFLICT(id) DO UPDATE SET
                          data=excluded.data,expires_at=excluded.expires_at''',
                       (sess.sid, json.dumps(dict(sess)), expires))
            db.execute('DELETE FROM web_sessions WHERE expires_at<?', (time.time(),))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        response.set_cookie(name, sess.sid, expires=datetime.fromtimestamp(expires, timezone.utc),
                            httponly=True, secure=self.get_cookie_secure(app),
                            samesite=self.get_cookie_samesite(app), path=self.get_cookie_path(app))
        response.vary.add('Cookie')


def configure_security(app):
    @app.before_request
    def throttle_auth():
        if request.path == '/py/login' and request.method == 'POST':
            db = connect_database(app.config)
            # Per client session + account; account quota also blocks cookie rotation.
            email = request.form.get('email', '').strip().lower()
            key = 'account:' + email[:254]
            now = time.time()
            try:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT attempts,window_start FROM auth_throttle WHERE key=?',
                                 (key,)).fetchone()
                if row and now - row[1] < 300 and row[0] >= 20:
                    db.rollback()
                    abort(429, description='Слишком много попыток входа. Подождите 5 минут.')
                db.execute(
                    '''INSERT INTO auth_throttle(key,attempts,window_start) VALUES(?,1,?)
                       ON CONFLICT(key) DO UPDATE SET
                       attempts=CASE WHEN ?-auth_throttle.window_start>=300
                                     THEN 1 ELSE auth_throttle.attempts+1 END,
                       window_start=CASE WHEN ?-auth_throttle.window_start>=300
                                         THEN ? ELSE auth_throttle.window_start END''',
                    (key, now, now, now, now),
                )
                db.execute('DELETE FROM auth_throttle WHERE window_start<?', (now - 86400,))
                db.commit()
            except HTTPException:
                raise
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    @app.after_request
    def protect_response(response):
        db = g.get('db')
        if db is not None and db.in_transaction:
            db.rollback()
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        if response.mimetype == 'text/html':
            token = escape(generate_csrf())
            html = response.get_data(as_text=True)
            def inject(match):
                form = match.group(0)
                if re.search(r'method\s*=\s*[\'"]?post\b', form, re.I):
                    return form + f'<input type="hidden" name="csrf_token" value="{token}">'
                return form
            response.set_data(re.sub(r'<form\b[^>]*>', inject, html, flags=re.I))
            response.headers['Cache-Control'] = 'no-store'
        if request.path.startswith('/py/') and response.mimetype == 'application/json':
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        message = 'Защитный токен устарел. Обновите страницу и повторите действие.'
        if request.is_json or request.headers.get('X-CSRFToken'):
            return jsonify(error=message), 400
        return f'<html lang="ru"><meta charset="UTF-8"><h1>{message}</h1><a href="/py/">На главную</a></html>', 400

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.is_json or request.path.startswith('/py/api/'):
            return jsonify(error=error.description), error.code
        return f'<html lang="ru"><meta charset="UTF-8"><h1>{error.code}</h1><p>{escape(error.description)}</p><a href="/py/">На главную</a></html>', error.code

    @app.errorhandler(Exception)
    def server_error(error):
        current_app.logger.exception('Unhandled request error')
        if request.is_json:
            return jsonify(error='Ошибка сервера. Попробуйте позже.'), 500
        return '<html lang="ru"><meta charset="UTF-8"><h1>Ошибка сервера</h1><a href="/py/">На главную</a></html>', 500
