"""Regression checks against a temporary copy, never the user's live SQLite file."""
import importlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from storage import PostgresCursor

TEMP = tempfile.TemporaryDirectory()
DATABASE = Path(TEMP.name) / 'test.db'
shutil.copy2(ROOT / 'ege_trainer.db', DATABASE)
os.environ['EGE_DB_PATH'] = str(DATABASE)
module = importlib.import_module('app')
app = module.app


class StorageCompatibilityTests(unittest.TestCase):
    def test_qmark_translation_skips_quoted_question_marks(self):
        sql = """SELECT '?' AS literal, "?" AS identifier WHERE value=?"""
        self.assertEqual(
            PostgresCursor._translate(sql),
            """SELECT '?' AS literal, "?" AS identifier WHERE value=%s""",
        )

    def test_begin_immediate_becomes_postgres_begin(self):
        class Cursor:
            sql = None

            def execute(self, sql):
                self.sql = sql

        cursor = Cursor()
        PostgresCursor(cursor).execute('BEGIN IMMEDIATE')
        self.assertEqual(cursor.sql, 'BEGIN')

    def test_short_timestamp_accepts_postgres_datetime_and_sqlite_text(self):
        moment = datetime(2026, 10, 14, 12, 54, 4)
        self.assertEqual(module.short_timestamp(moment), '2026-10-14')
        self.assertEqual(module.short_timestamp(moment, 16), '2026-10-14 12:54')
        self.assertEqual(module.short_timestamp('2026-10-14 12:54:04'), '2026-10-14')
        self.assertEqual(module.short_timestamp(None), '')


class TrainerTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.serial = self.id().split('.')[-1]
        self.email = self.serial + '@example.test'
        self.token = self.csrf(self.client)
        response = self.client.post('/py/login', data={
            'csrf_token': self.token, 'action': 'register', 'name': 'Тестовый ученик',
            'email': self.email, 'password': 'test-only-strong-password',
        })
        self.assertEqual(response.status_code, 302, response.text)
        self.refresh_csrf()
        with sqlite3.connect(DATABASE) as db:
            self.uid = db.execute('SELECT id FROM users WHERE email=?', (self.email,)).fetchone()[0]

    def csrf(self, client):
        html = client.get('/py/login').text
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def refresh_csrf(self):
        self.token = re.search(r'window.csrfToken = "([^"]+)"', self.client.get('/py/').text).group(1)

    def post(self, path, payload, client=None, token=None):
        return (client or self.client).post(path, json=payload, headers={'X-CSRFToken': token or self.token})

    def value(self, sql, params=()):
        with sqlite3.connect(DATABASE) as db:
            return db.execute(sql, params).fetchone()[0]

    def practice(self, path):
        html = self.client.get(path).text
        token = re.search(r'data-practice-id="([^"]+)"', html).group(1)
        with sqlite3.connect(DATABASE) as db:
            ids = json.loads(db.execute('SELECT question_ids_json FROM practice_sessions WHERE id=?',
                                        (token,)).fetchone()[0])
        return token, ids

    def test_all_pages(self):
        dashboard = self.client.get('/py/').text
        self.assertIn('navbar-links', dashboard)
        for label in ('Предметы', 'Аналитика', 'Мои ошибки', 'Рейтинг', 'Профиль'):
            self.assertIn(label, dashboard)
        exam_html = self.client.get('/py/subjects/math/exam/start').text
        self.assertNotIn('</script>tarts[qid])', exam_html)
        paths = ['/py/', '/py/analytics', '/py/mistakes', '/py/my-essays', '/py/arguments',
                 '/py/news', '/py/leaderboard', '/py/profile', '/healthz']
        for subject in module.SUBJECTS:
            for suffix in ['', '/theory', '/quiz', '/quiz?part=part2', '/exam',
                           '/exam/start', '/drill', '/adaptive', '/essay', '/analyses', '/guides']:
                paths.append('/py/subjects/' + subject + suffix)
            if subject == 'russian':
                paths.append('/py/subjects/russian/final-essay')
            with sqlite3.connect(DATABASE) as db:
                task = db.execute('SELECT task_number FROM questions WHERE subject=? LIMIT 1', (subject,)).fetchone()[0]
            paths.append(f'/py/subjects/{subject}/drill/{task}')
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=True)
                self.assertEqual(response.status_code, 200, response.text[:400])

    def test_mobile_navigation_wraps_all_links_without_horizontal_scrolling(self):
        css = (ROOT / 'static' / 'css' / 'style.css').read_text()
        mobile_start = css.index('/* Узкий экран:')
        mobile_end = css.index('@media (max-width: 420px)', mobile_start)
        mobile_nav = css[mobile_start:mobile_end]
        self.assertIn('flex-wrap: wrap;', mobile_nav)
        self.assertIn('overflow: visible;', mobile_nav)
        self.assertNotIn('overflow-x: auto;', mobile_nav)

    def test_mobile_layouts_stack_and_wide_history_scrolls(self):
        css = (ROOT / 'static' / 'css' / 'style.css').read_text()
        self.assertIn('.analytics-layout, .essay-layout-grid {', css)
        self.assertIn('.essay-checklist-panel { position: static !important;', css)
        self.assertIn('.admin-criteria-grid { grid-template-columns: repeat(3, minmax(0, 1fr)) !important; }', css)
        self.assertIn('.news-item { flex-direction: column; gap: 8px; }', css)
        self.assertIn('.analytics-history-scroll { max-width: 100%; overflow-x: auto; }', css)

        analytics_html = self.client.get('/py/analytics').get_data(as_text=True)
        essay_html = self.client.get('/py/subjects/math/essay').get_data(as_text=True)
        self.assertIn('class="analytics-layout"', analytics_html)
        self.assertIn('class="essay-layout-grid"', essay_html)
        self.assertIn('class="card essay-checklist-panel"', essay_html)

    def test_dark_theme_answer_fields_have_dark_surfaces_and_light_text(self):
        css = (ROOT / 'static' / 'css' / 'style.css').read_text()
        self.assertRegex(
            css,
            r'html\[data-theme="dark"\] \.short-answer-input\s*\{[^}]*background-color:\s*#101a2a;[^}]*color:\s*#f8fafc;',
        )
        self.assertIn('html[data-theme="dark"] .short-answer-input.correct-answer', css)
        self.assertIn('html[data-theme="dark"] .short-answer-input.wrong-answer', css)

    def test_dark_theme_white_surfaces_and_hover_text_stay_contrasted(self):
        css = (ROOT / 'static' / 'css' / 'style.css').read_text()
        self.assertIn('html[data-theme="dark"] .theory-section-header,', css)
        self.assertIn('html[data-theme="dark"] .theory-section-header:hover,', css)
        self.assertIn('html[data-theme="dark"] .argument-details summary:hover {', css)
        self.assertIn('color: var(--text) !important;', css)
        self.assertIn('html[data-theme="dark"] .argument-rubric thead,', css)
        self.assertIn('background: var(--bg);', css)
        self.assertIn('html[data-theme="dark"] .argument-rubric tfoot th { color: var(--text); }', css)
        self.assertIn('html[data-theme="dark"] .argument-bank .cliche-list li:hover,', css)

    def test_dark_theme_rubric_score_digits_are_visible_in_white_circles(self):
        css = (ROOT / 'static' / 'css' / 'style.css').read_text()
        self.assertRegex(
            css,
            r'html\[data-theme="dark"\] \.score-btn:not\(\.score-btn-active\)\s*\{[^}]*background-color:\s*#fff;[^}]*color:\s*#0f172a;',
        )
        self.assertIn('html[data-theme="dark"] .score-btn:not(.score-btn-active):hover,', css)
        self.assertIn('html[data-theme="dark"] .score-btn-active {', css)

    def test_dark_theme_practice_button_label_has_high_contrast(self):
        css = (ROOT / 'static' / 'css' / 'style.css').read_text()
        self.assertIn('html[data-theme="dark"] a.btn-teal { color: #062c2b; }', css)
        self.assertIn('html[data-theme="dark"] a.btn-teal:hover', css)

    def test_argument_bank_research_content_and_no_source_links(self):
        response = self.client.get('/py/arguments')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for phrase in (
            'Задание 27: главное на 2026 год',
            'не менее 150 слов',
            '22 балла',
            'смысловой связи',
            'Уроки французского',
            'Вишнёвый сад',
            'Царь-рыба',
            'Производная и исследование функции',
            'Теорема синусов',
            'Стереометрия',
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, html)
        self.assertNotIn('href="https://fipi.ru', html)
        self.assertNotIn('href="https://foxford.ru', html)
        self.assertNotIn('href="https://examer.ru', html)

    def test_profile_without_avatars_keeps_subject_comparison(self):
        with sqlite3.connect(DATABASE) as db:
            db.executemany(
                'INSERT INTO test_results(user_id,subject,score,questions_count,mode) VALUES(?,?,?,?,?)',
                [(self.uid, 'math', 86, 10, 'quiz'), (self.uid, 'russian', 42, 10, 'quiz')],
            )
        html = self.client.get('/py/profile').get_data(as_text=True)
        self.assertNotIn('Аватар профиля', html)
        self.assertNotIn('class="profile-avatar"', html)
        self.assertNotIn('avatar-upload-form', html)
        self.assertNotIn('Сохранить фото', html)
        self.assertIn('Прогресс и результаты по предметам', html)
        self.assertIn('class="profile-top-grid profile-top-grid-single"', html)
        self.assertIn('Лучший результат', html)
        self.assertIn('Математика', html)
        self.assertIn('Нужно больше практики', html)
        self.assertIn('Русский язык', html)

    def test_profile_photo_upload_validation_and_avatar_views(self):
        image = b'\x89PNG\r\n\x1a\n' + b'avatar-test-content'
        uploaded = self.client.post('/py/profile', data={
            'csrf_token': self.token,
            'avatar_image': (io.BytesIO(image), 'profile.png'),
        }, content_type='multipart/form-data')
        self.assertEqual(uploaded.status_code, 302)
        self.assertEqual(
            self.value('SELECT avatar_image_mime FROM users WHERE id=?', (self.uid,)),
            'image/png',
        )
        with sqlite3.connect(DATABASE) as db:
            stored_image = db.execute(
                'SELECT avatar_image FROM users WHERE id=?', (self.uid,)
            ).fetchone()[0]
        self.assertEqual(stored_image, image)

        profile_html = self.client.get('/py/profile').get_data(as_text=True)
        self.assertIn('Фото аватара загружено.', profile_html)
        self.assertNotIn(f'<img src="/py/avatar/{self.uid}" alt="">', profile_html)
        avatar_response = self.client.get(f'/py/avatar/{self.uid}')
        self.assertEqual(avatar_response.status_code, 200)
        self.assertEqual(avatar_response.mimetype, 'image/png')
        self.assertEqual(avatar_response.data, image)
        self.assertEqual(avatar_response.headers.get('X-Content-Type-Options'), 'nosniff')

        with sqlite3.connect(DATABASE) as db:
            db.execute('UPDATE users SET xp=1000000 WHERE id=?', (self.uid,))
        leaderboard_html = self.client.get('/py/leaderboard').get_data(as_text=True)
        self.assertIn(f'<img src="/py/avatar/{self.uid}" alt="">', leaderboard_html)

        invalid = self.client.post('/py/profile', data={
            'csrf_token': self.token,
            'avatar_image': (io.BytesIO(b'not-an-image'), 'profile.jpg'),
        }, content_type='multipart/form-data')
        self.assertEqual(invalid.status_code, 302)
        self.assertIn('Поддерживаются изображения JPEG, PNG и WebP.', self.client.get('/py/profile').text)
        with sqlite3.connect(DATABASE) as db:
            self.assertEqual(
                db.execute('SELECT avatar_image FROM users WHERE id=?', (self.uid,)).fetchone()[0],
                image,
            )

        removed = self.client.post('/py/profile', data={
            'csrf_token': self.token,
            'remove_avatar': '1',
        })
        self.assertEqual(removed.status_code, 302)
        self.assertIsNone(self.value('SELECT avatar_image FROM users WHERE id=?', (self.uid,)))
        self.assertEqual(self.client.get(f'/py/avatar/{self.uid}').status_code, 404)

    def test_leaderboard_shows_selected_and_default_avatars(self):
        with sqlite3.connect(DATABASE) as db:
            db.execute(
                'UPDATE users SET avatar_emoji=?,avatar_color=?,xp=999999 WHERE id=?',
                ('🐼', '#7c3aed', self.uid),
            )
        html = self.client.get('/py/leaderboard').get_data(as_text=True)
        self.assertIn('class="leader-avatar" style="background-color:#7c3aed"', html)
        self.assertIn('Аватар Тестовый ученик', html)
        self.assertRegex(html, r'class="leader-avatar"[^>]*>\s*Т\s*</div>')
        self.assertNotIn('🐼', html)

        with sqlite3.connect(DATABASE) as db:
            db.execute(
                "UPDATE users SET avatar_emoji='',avatar_color='' WHERE id=?",
                (self.uid,),
            )
        html = self.client.get('/py/leaderboard').get_data(as_text=True)
        self.assertIn('background-color:#2563eb', html)
        self.assertRegex(html, r'class="leader-avatar"[^>]*>\s*Т\s*</div>')
        self.assertNotIn('🦊', html)

    def test_csrf_and_access_controls(self):
        response = self.client.post('/py/subjects/math/essay/submit', json={'text': 'x'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get('/py/admin').status_code, 403)
        self.assertEqual(self.client.get('/py/logout').status_code, 405)
        anon = app.test_client()
        token = self.csrf(anon)
        self.assertEqual(self.post('/py/subjects/math/quiz/submit', {}, anon, token).status_code, 401)
        self.assertEqual(self.client.post('/py/logout', data={'csrf_token': self.token}).status_code, 302)
        self.assertEqual(self.client.get('/py/profile').status_code, 302)

    def test_theme_toggle_is_available_before_and_after_login(self):
        authenticated_html = self.client.get('/py/').get_data(as_text=True)
        self.assertIn('data-theme-toggle', authenticated_html)
        self.assertIn('/py/static/js/theme.js', authenticated_html)

        guest = app.test_client()
        guest_html = guest.get('/py/login').get_data(as_text=True)
        self.assertIn('data-theme-toggle', guest_html)
        self.assertIn('theme-toggle-floating', guest_html)
        register_html = guest.get('/py/register').get_data(as_text=True)
        self.assertIn('data-theme-toggle', register_html)
        theme_script = (ROOT / 'static' / 'js' / 'theme.js').read_text()
        self.assertIn("localStorage.setItem('ege-trainer-theme'", theme_script)
        self.assertIn("html[data-theme=\"dark\"]", (ROOT / 'static' / 'css' / 'style.css').read_text())

    def test_subject_modes_use_neutral_borders_in_both_themes(self):
        html = self.client.get('/py/subjects/math').get_data(as_text=True)
        self.assertIn('class="subject-card mode-card mode-card-exam"', html)
        self.assertIn('class="subject-card mode-card mode-card-test"', html)
        self.assertIn('class="subject-card mode-card mode-card-drill"', html)
        self.assertIn('class="badge mode-badge" style="margin-top:8px">По номеру задания', html)
        css = (ROOT / 'static' / 'css' / 'style.css').read_text()
        self.assertIn('html[data-theme="dark"] .mode-card {', css)
        self.assertIn('border-color: var(--border) !important;', css)
        self.assertIn('.mode-card-adaptive { border-color: var(--border); background: var(--card); }', css)
        self.assertIn('border-radius: 3px !important;', css)

    def test_site_uses_consistent_arial_typography(self):
        css = (ROOT / 'static' / 'css' / 'style.css').read_text()
        self.assertIn('--font-body: Arial, Helvetica, sans-serif;', css)
        self.assertIn('--font-heading: Arial, Helvetica, sans-serif;', css)
        self.assertIn('button, input, select, textarea { font-family: var(--font-body); }', css)
        self.assertIn('h1, h2, h3, h4, h5, h6, .page-title {', css)
        self.assertIn('ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', css)

    def test_guest_landing_has_plain_brand_and_neutral_feature_cards(self):
        guest = app.test_client()
        response = guest.get('/py/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('class="landing-simple-brand">ЕГЭ Тренажёр</a>', html)
        self.assertNotIn('<span>Е</span>', html)
        self.assertIn('class="theme-toggle landing-theme-toggle" type="button" data-theme-toggle', html)
        self.assertNotIn('theme-toggle-floating', html)
        css = (ROOT / 'static' / 'css' / 'style.css').read_text()
        self.assertIn('.mode-blue, .mode-purple, .mode-orange, .mode-green { background:#eef1f5; color:#475569; }', css)
        self.assertIn('.landing-simple-modes article { min-height:148px;', css)

    def test_dashboard_uses_neutral_badges_and_quick_start_actions(self):
        html = self.client.get('/py/').get_data(as_text=True)
        self.assertIn('class="container dashboard-page"', html)
        self.assertEqual(html.count('class="subject-card dashboard-subject-card"'), 4)
        self.assertEqual(html.count('class="dashboard-action"'), 12)
        self.assertIn('class="dashboard-subject-meta"', html)
        self.assertIn('class="dashboard-summary" aria-label="Краткая статистика"', html)
        self.assertEqual(html.count('class="dashboard-stat"'), 4)
        self.assertNotIn('dashboard-badge', html)
        self.assertNotIn('[:10]', html)
        self.assertIn('class="dashboard-panel-title">Динамика баллов', html)
        self.assertIn('class="dashboard-panel-title">Быстрый старт', html)
        self.assertNotIn('btn-teal btn-sm', html)
        self.assertNotIn('background:#f3e8ff;color:#7c3aed', html)
        css = (ROOT / 'static' / 'css' / 'style.css').read_text()
        self.assertIn('.dashboard-summary {', css)
        self.assertIn('.dashboard-action:hover {', css)

    def test_all_component_borders_use_theme_neutral_color(self):
        css = (ROOT / 'static' / 'css' / 'style.css').read_text()
        self.assertIn('body * { border-color: var(--border) !important; }', css)
        self.assertIn('--border: #e2e8f0;', css)
        self.assertIn('--border: #344256;', css)

    def test_quiz_server_denominator_and_idempotence(self):
        token, ids = self.practice('/py/subjects/math/quiz')
        with sqlite3.connect(DATABASE) as db:
            row = db.execute('SELECT answer_type,correct_index,correct_answer FROM questions WHERE id=?',
                             (ids[0],)).fetchone()
        answer = row[2] if row[0] == 'short' else row[1]
        payload = {'practice_id': token, 'answers': {str(ids[0]): answer}}
        first = self.post('/py/subjects/math/quiz/submit', payload)
        self.assertEqual(first.status_code, 200, first.text)
        data = first.json
        self.assertEqual(data['total'], len(ids))
        self.assertEqual(data['correct'], 1)
        self.assertEqual(data['score'], round(100 / len(ids)))
        again = self.post('/py/subjects/math/quiz/submit', payload)
        self.assertEqual(again.json, data)
        self.assertEqual(self.value('SELECT xp FROM users WHERE id=?', (self.uid,)), 10)
        self.assertEqual(self.value('SELECT COUNT(*) FROM question_attempts WHERE user_id=?', (self.uid,)), len(ids))

    def test_foreign_questions_and_atomic_rollback(self):
        token, ids = self.practice('/py/subjects/math/quiz')
        foreign = self.value("SELECT id FROM questions WHERE subject='physics' LIMIT 1")
        response = self.post('/py/subjects/math/quiz/submit',
                             {'practice_id': token, 'answers': {str(foreign): 0}})
        self.assertEqual(response.status_code, 400)
        response = self.post('/py/subjects/math/quiz/submit', {
            'practice_id': token, 'answers': {str(ids[0]): 0}, 'times': {str(ids[-1]): -10},
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.value('SELECT COUNT(*) FROM question_attempts WHERE user_id=?', (self.uid,)), 0)
        self.assertEqual(self.post('/py/subjects/math/quiz/submit', {'practice_id': token, 'answers': {}}).status_code, 200)

    def test_adaptive_and_bad_payloads(self):
        token, ids = self.practice('/py/subjects/russian/adaptive')
        for bad in [{'answers': []}, {'answers': 'x'}, {'answers': {}, 'times': []}]:
            bad['practice_id'] = token
            self.assertEqual(self.post('/py/subjects/russian/quiz/submit', bad).status_code, 400)
        response = self.post('/py/subjects/russian/quiz/submit', {'practice_id': token, 'answers': {}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['correct'], 0)
        self.assertEqual(self.value('SELECT mode FROM test_results WHERE user_id=?', (self.uid,)), 'adaptive')

    def test_exam_resume_empty_submit_and_idempotence(self):
        html = self.client.get('/py/subjects/math/exam/start').text
        sid = int(re.search(r'data-sess="(\d+)"', html).group(1))
        stored = json.loads(self.value('SELECT answers_json FROM exam_sessions WHERE id=?', (sid,)))
        question_ids = stored['question_ids']
        task_numbers = [
            self.value('SELECT task_number FROM questions WHERE id=?', (question_id,))
            for question_id in question_ids
        ]
        candidate_count = self.value(
            "SELECT COUNT(*) FROM questions WHERE subject='math' "
            "AND (part='part1' OR difficulty='part2_bank')"
        )
        self.assertGreater(len(question_ids), 0)
        self.assertEqual(len(task_numbers), len(set(task_numbers)))
        self.assertLess(len(question_ids), candidate_count)

        resumed = self.client.get('/py/subjects/math/exam/start').text
        self.assertIn(f'data-sess="{sid}"', resumed)
        self.assertEqual(
            json.loads(self.value('SELECT answers_json FROM exam_sessions WHERE id=?', (sid,))),
            stored,
        )
        response = self.post('/py/subjects/math/exam/submit', {'sess_id': sid, 'answers': {}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertGreater(response.json['total'], 0)
        self.assertEqual(response.json['correct'], 0)
        self.assertEqual(self.post('/py/subjects/math/exam/submit', {'sess_id': sid}).json, response.json)
        self.assertEqual(self.value('SELECT tests_completed FROM users WHERE id=?', (self.uid,)), 1)

    def test_material_pages_show_latest_duplicate_title_once(self):
        with sqlite3.connect(DATABASE) as db:
            db.execute(
                'INSERT INTO theory_sections(subject,title,content,order_index) VALUES(?,?,?,?)',
                ('math', 'Проверка актуальной версии', 'OLD_THEORY_VERSION', 999),
            )
            db.execute(
                'INSERT INTO theory_sections(subject,title,content,order_index) VALUES(?,?,?,?)',
                ('math', 'Проверка актуальной версии', 'NEW_THEORY_VERSION', 999),
            )
            db.execute(
                'INSERT INTO task_analyses(subject,task_number,title,content) VALUES(?,?,?,?)',
                ('math', 99, 'Проверка актуального разбора', 'OLD_ANALYSIS_VERSION'),
            )
            db.execute(
                'INSERT INTO task_analyses(subject,task_number,title,content) VALUES(?,?,?,?)',
                ('math', 99, 'Проверка актуального разбора', 'NEW_ANALYSIS_VERSION'),
            )
            db.execute(
                'INSERT INTO guides(subject,category,title,content,url) VALUES(?,?,?,?,?)',
                ('math', 'Версии', 'Проверка актуальной памятки', 'OLD_GUIDE_VERSION', None),
            )
            db.execute(
                'INSERT INTO guides(subject,category,title,content,url) VALUES(?,?,?,?,?)',
                ('math', 'Версии', 'Проверка актуальной памятки', 'NEW_GUIDE_VERSION', None),
            )

        theory_html = self.client.get('/py/subjects/math/theory').get_data(as_text=True)
        analysis_html = self.client.get('/py/subjects/math/analyses').get_data(as_text=True)
        guides_html = self.client.get('/py/subjects/math/guides').get_data(as_text=True)
        for html, new_marker, old_marker in (
            (theory_html, 'NEW_THEORY_VERSION', 'OLD_THEORY_VERSION'),
            (analysis_html, 'NEW_ANALYSIS_VERSION', 'OLD_ANALYSIS_VERSION'),
            (guides_html, 'NEW_GUIDE_VERSION', 'OLD_GUIDE_VERSION'),
        ):
            self.assertIn(new_marker, html)
            self.assertNotIn(old_marker, html)

    def test_exam_ownership(self):
        other_id = self.value("SELECT id FROM users WHERE id<>? LIMIT 1", (self.uid,))
        with sqlite3.connect(DATABASE) as db:
            result = db.execute("INSERT INTO exam_sessions(user_id,subject) VALUES(?,?)", (other_id, 'math'))
            sid = result.lastrowid
        self.assertEqual(self.post('/py/subjects/math/exam/submit', {'sess_id': sid}).status_code, 404)

    def test_drill_saves_once(self):
        task = self.value("SELECT task_number FROM questions WHERE subject='math' LIMIT 1")
        html = self.client.get(f'/py/subjects/math/drill/{task}').text
        public = json.loads(re.search(r'var allQuestions = (\[.*?\]);', html).group(1))
        self.assertTrue(all('correct_index' not in q and 'explanation' not in q for q in public))
        with sqlite3.connect(DATABASE) as db:
            row = db.execute("SELECT id,question_ids_json FROM practice_sessions WHERE user_id=? AND mode='drill'",
                             (self.uid,)).fetchone()
        ids = json.loads(row[1])
        for qid in ids:
            with sqlite3.connect(DATABASE) as db:
                question = db.execute('SELECT answer_type,correct_index,correct_answer FROM questions WHERE id=?',
                                      (qid,)).fetchone()
            payload = {'practice_id': row[0], 'question_id': qid, 'time_sec': 10}
            if question[0] == 'short':
                payload['answer_text'] = question[2]
            else:
                payload['answer_idx'] = question[1]
            response = self.post('/py/subjects/math/drill/answer', payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json['correct'])
            self.assertEqual(self.post('/py/subjects/math/drill/answer', payload).json, response.json)
            saved = json.loads(self.value('SELECT result_json FROM practice_sessions WHERE id=?', (row[0],)))
            if saved.get('_complete'):
                break
        self.assertEqual(self.value('SELECT COUNT(*) FROM question_attempts WHERE user_id=?', (self.uid,)), 3)
        self.assertEqual(self.value('SELECT tests_completed FROM users WHERE id=?', (self.uid,)), 1)

    def test_drill_setup_groups_sections_by_task_number(self):
        html = self.client.get('/py/subjects/math/drill').get_data(as_text=True)
        cards = re.findall(r'<a href="/py/subjects/math/drill/(\d+)"[^>]*>(.*?)</a>', html, re.S)
        numbers = [int(number) for number, _ in cards]
        self.assertEqual(len(numbers), len(set(numbers)))
        with sqlite3.connect(DATABASE) as db:
            duplicate = db.execute(
                '''SELECT task_number FROM questions WHERE subject='math'
                   GROUP BY task_number HAVING COUNT(DISTINCT section)>1 LIMIT 1'''
            ).fetchone()
            self.assertIsNotNone(duplicate, 'Test data should include multiple sections under one EGE number')
            sections = [
                row[0] for row in db.execute(
                    '''SELECT DISTINCT section FROM questions
                       WHERE subject='math' AND task_number=? AND section<>''
                       ORDER BY section''',
                    (duplicate[0],),
                ).fetchall()
            ]
        grouped_card = next(card for number, card in cards if int(number) == duplicate[0])
        plain_card = re.sub(r'<[^>]+>', ' ', grouped_card)
        for section in sections:
            self.assertIn(section, plain_card)

    def test_drill_client_handles_saved_answers_without_false_network_error(self):
        template = (ROOT / 'templates' / 'drill.html').read_text()
        send_start = template.index('function send()')
        send_end = template.index('function fail(msg)', send_start)
        send_handler = template[send_start:send_end]
        self.assertIn('var q = allQuestions[currentIdx];', send_handler)
        self.assertIn('answeredSet[p.question_id] = true;', send_handler)
        self.assertIn('pending = null;', send_handler)
        self.assertIn('повтор не засчитает его дважды', send_handler)
        self.assertLess(
            send_handler.index('answeredSet[p.question_id] = true;'),
            send_handler.index('pending = null;'),
        )

    def test_russian_final_essay_is_separate_from_ege_essay(self):
        subject_page = self.client.get('/py/subjects/russian').get_data(as_text=True)
        self.assertIn('href="/py/subjects/russian/final-essay"', subject_page)
        self.assertIn('Итоговое сочинение — декабрь', subject_page)
        self.assertIn('href="/py/subjects/russian/essay?from=part2"', subject_page)
        self.assertIn('Сочинение ЕГЭ — задание 27', subject_page)

        final_essay = self.client.get('/py/subjects/russian/final-essay')
        self.assertEqual(final_essay.status_code, 200)
        html = final_essay.get_data(as_text=True)
        self.assertIn('Минимальный объём — 250 слов', html)
        self.assertIn('литературный аргумент', html)
        self.assertIn('тренировочные, это не официальный перечень', html)
        self.assertIn('ege-trainer-final-essay-drafts-v1', html)
        self.assertIn('data-final-criterion="5"', html)
        self.assertIn('Отправить на проверку', html)

    def test_final_essay_submission_is_identified_and_admin_can_grade_it(self):
        topic = module.DECEMBER_ESSAY_TOPICS[0]
        text = 'Герой произведения показывает, как важно отвечать за свои поступки. ' * 60
        response = self.post('/py/subjects/russian/final-essay/submit', {
            'text': text,
            'topic': topic,
            'checklist': {'1': True, '2': True, '3': False, '4': True, '5': True},
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json['ok'])
        essay_id = self.value(
            'SELECT id FROM essay_submissions WHERE user_id=? AND essay_type=?',
            (self.uid, 'final'),
        )
        with sqlite3.connect(DATABASE) as db:
            row = db.execute(
                'SELECT essay_type,essay_topic,word_count,self_score,teacher_result '
                'FROM essay_submissions WHERE id=?',
                (essay_id,),
            ).fetchone()
        self.assertEqual(row[0], 'final')
        self.assertEqual(row[1], topic)
        self.assertEqual(row[2], len(text.split()))
        self.assertEqual(row[3], 4)
        self.assertIsNone(row[4])

        student_html = self.client.get('/py/my-essays').get_data(as_text=True)
        self.assertIn('Итоговое сочинение — декабрь', student_html)
        self.assertIn(topic, student_html)
        self.assertIn('Самопроверка:', student_html)
        self.assertNotIn(topic, self.client.get('/py/subjects/russian/essay').get_data(as_text=True))

        with sqlite3.connect(DATABASE) as db:
            db.execute('UPDATE users SET is_admin=1 WHERE id=?', (self.uid,))
        admin_html = self.client.get('/py/admin/essays').get_data(as_text=True)
        self.assertIn('Итоговое сочинение — декабрь', admin_html)
        self.assertIn(topic, admin_html)
        self.assertIn('name="teacher_result"', admin_html)
        grade_response = self.client.post(
            f'/py/admin/essays/{essay_id}/grade',
            data={
                'csrf_token': self.token,
                'teacher_result': 'pass',
                'teacher_comment': 'Есть ответ на тему и литературный аргумент.',
            },
        )
        self.assertEqual(grade_response.status_code, 302)
        with sqlite3.connect(DATABASE) as db:
            graded = db.execute(
                'SELECT teacher_score,teacher_result,teacher_comment '
                'FROM essay_submissions WHERE id=?',
                (essay_id,),
            ).fetchone()
        self.assertIsNone(graded[0])
        self.assertEqual(graded[1], 'pass')
        self.assertEqual(graded[2], 'Есть ответ на тему и литературный аргумент.')
        self.assertEqual(self.client.get('/py/admin').status_code, 200)

        with sqlite3.connect(DATABASE) as db:
            db.execute('UPDATE users SET is_admin=0 WHERE id=?', (self.uid,))
        updated_student_html = self.client.get('/py/my-essays').get_data(as_text=True)
        self.assertIn('Результат: Зачёт', updated_student_html)
        self.assertEqual(self.post(f'/py/essay/{essay_id}/resubmit', {'text': text}).status_code, 400)

    def test_essay_grade_resubmit_news_and_backup(self):
        payload = {'text': 'Проверка сочинения ' * 100, 'checklist': {'К1': 1}}
        self.assertEqual(self.post('/py/subjects/russian/essay/submit', {'text': ''}).status_code, 400)
        self.assertEqual(self.post('/py/subjects/russian/essay/submit', dict(payload, checklist={'К1': 999})).status_code, 400)
        self.assertEqual(self.post('/py/subjects/russian/essay/submit', payload).status_code, 200)
        essay_id = self.value('SELECT id FROM essay_submissions WHERE user_id=?', (self.uid,))
        self.assertEqual(self.client.get('/py/my-essays').status_code, 200)
        with sqlite3.connect(DATABASE) as db:
            db.execute('UPDATE users SET is_admin=1 WHERE id=?', (self.uid,))
        for path in ['/py/admin', '/py/admin/essays', '/py/admin/news']:
            self.assertEqual(self.client.get(path).status_code, 200)
        admin_html = self.client.get('/py/admin').get_data(as_text=True)
        self.assertNotIn('Скачать резервную копию SQLite', admin_html)
        self.assertNotIn('локальные файлы опубликованного сайта могут быть сброшены', admin_html)
        response = self.client.post(f'/py/admin/essays/{essay_id}/grade',
                                    data={'csrf_token': self.token, 'teacher_score': '20', 'teacher_comment': 'Проверено'})
        self.assertEqual(response.status_code, 302, response.text)
        self.assertEqual(self.client.get('/py/admin/essays').status_code, 200)
        backup = self.client.post('/py/admin/backup', data={'csrf_token': self.token})
        self.assertEqual(backup.status_code, 200, backup.text[:100] if backup.mimetype == 'text/html' else '')
        self.assertTrue(backup.data.startswith(b'SQLite format 3'))
        response = self.client.post('/py/admin/news/add', data={
            'csrf_token': self.token, 'title': 'Тестовая новость', 'content': 'Тестовый текст',
            'subject': 'math', 'year': '2026',
        })
        self.assertEqual(response.status_code, 302)
        news_id = self.value("SELECT id FROM news_items WHERE title='Тестовая новость'")
        self.assertEqual(self.client.post(f'/py/admin/news/delete/{news_id}',
                                         data={'csrf_token': self.token}).status_code, 302)
        with sqlite3.connect(DATABASE) as db:
            db.execute('UPDATE users SET is_admin=0 WHERE id=?', (self.uid,))
        self.assertEqual(self.client.get('/py/my-essays').status_code, 200)
        self.assertEqual(self.post(f'/py/essay/{essay_id}/resubmit', payload).status_code, 200)
        self.assertEqual(self.client.get('/py/my-essays').status_code, 200)
        self.assertEqual(self.post(f'/py/essay/{essay_id}/resubmit', payload).status_code, 400)

    def test_news_suggestions_require_admin_approval_or_rejection(self):
        suggestion_data = {
            'csrf_token': self.token,
            'title': 'Предложение ученика',
            'content': 'Полезная новость о подготовке к экзамену.',
            'subject': 'math',
            'year': '2027',
        }
        response = self.client.post('/py/news/suggest', data=suggestion_data)
        self.assertEqual(response.status_code, 302)
        suggestion_id = self.value(
            "SELECT id FROM news_suggestions WHERE user_id=? AND title=?",
            (self.uid, suggestion_data['title']),
        )
        self.assertEqual(
            self.value("SELECT COUNT(*) FROM news_items WHERE title='Предложение ученика'"),
            0,
        )
        news_html = self.client.get('/py/news').get_data(as_text=True)
        self.assertIn('На рассмотрении', news_html)
        self.assertIn('Предложение ученика', news_html)
        self.assertEqual(
            self.client.post(
                f'/py/admin/news/suggestions/{suggestion_id}/publish',
                data={'csrf_token': self.token},
            ).status_code,
            403,
        )

        with sqlite3.connect(DATABASE) as db:
            db.execute('UPDATE users SET is_admin=1 WHERE id=?', (self.uid,))
        admin_html = self.client.get('/py/admin/news').get_data(as_text=True)
        self.assertIn('Предложения учеников (1)', admin_html)
        self.assertIn(self.email, admin_html)
        response = self.client.post(
            f'/py/admin/news/suggestions/{suggestion_id}/publish',
            data={'csrf_token': self.token},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.value('SELECT status FROM news_suggestions WHERE id=?', (suggestion_id,)),
            'published',
        )
        self.assertEqual(
            self.value("SELECT COUNT(*) FROM news_items WHERE title='Предложение ученика'"),
            1,
        )
        public_html = self.client.get('/py/news').get_data(as_text=True)
        self.assertIn('Математика', public_html)
        self.assertEqual(
            self.value("SELECT year FROM news_items WHERE title='Предложение ученика'"),
            2027,
        )
        self.client.post(
            f'/py/admin/news/suggestions/{suggestion_id}/publish',
            data={'csrf_token': self.token},
        )
        self.assertEqual(
            self.value("SELECT COUNT(*) FROM news_items WHERE title='Предложение ученика'"),
            1,
        )

        with sqlite3.connect(DATABASE) as db:
            db.execute('UPDATE users SET is_admin=0 WHERE id=?', (self.uid,))
        rejected_data = dict(suggestion_data, title='Предложение для отклонения')
        self.assertEqual(
            self.client.post('/py/news/suggest', data=rejected_data).status_code,
            302,
        )
        rejected_id = self.value(
            'SELECT id FROM news_suggestions WHERE user_id=? AND title=?',
            (self.uid, rejected_data['title']),
        )
        with sqlite3.connect(DATABASE) as db:
            db.execute('UPDATE users SET is_admin=1 WHERE id=?', (self.uid,))
        response = self.client.post(
            f'/py/admin/news/suggestions/{rejected_id}/reject',
            data={'csrf_token': self.token},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.value('SELECT status FROM news_suggestions WHERE id=?', (rejected_id,)),
            'rejected',
        )
        self.assertEqual(
            self.value("SELECT COUNT(*) FROM news_items WHERE title='Предложение для отклонения'"),
            0,
        )

    def test_support_question_is_private_and_admin_can_reply(self):
        self.assertEqual(self.client.get('/py/support').status_code, 200)
        response = self.client.post('/py/support/ask', data={
            'csrf_token': self.token,
            'subject': 'Не открывается задание',
            'question': 'После нажатия на кнопку страница остаётся пустой.',
        })
        self.assertEqual(response.status_code, 302)
        ticket_id = self.value(
            'SELECT id FROM support_tickets WHERE user_id=?',
            (self.uid,),
        )
        self.assertEqual(
            self.value('SELECT status FROM support_tickets WHERE id=?', (ticket_id,)),
            'open',
        )
        self.assertEqual(self.client.get('/py/admin/support').status_code, 403)
        self.assertEqual(
            self.client.post(
                f'/py/admin/support/{ticket_id}/reply',
                data={'csrf_token': self.token, 'reply': 'Проверим.'},
            ).status_code,
            403,
        )

        with sqlite3.connect(DATABASE) as db:
            db.execute('UPDATE users SET is_admin=1 WHERE id=?', (self.uid,))
        admin_html = self.client.get('/py/admin/support').get_data(as_text=True)
        self.assertIn('Не открывается задание', admin_html)
        self.assertIn(self.email, admin_html)
        dashboard_html = self.client.get('/py/admin').get_data(as_text=True)
        self.assertIn('Вопросы учеников', dashboard_html)
        self.assertIn('1 ждут ответа', dashboard_html)
        self.assertIn('class="admin-summary"', dashboard_html)
        self.assertEqual(dashboard_html.count('class="admin-section"'), 3)
        self.assertIn('Сочинения, новости и обращения учеников', dashboard_html)
        self.assertNotIn('style="border-color:#fca5a5"', dashboard_html)
        self.assertNotIn('color:#047857', dashboard_html)
        response = self.client.post(
            f'/py/admin/support/{ticket_id}/reply',
            data={'csrf_token': self.token, 'reply': 'Попробуйте обновить страницу.'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.value('SELECT status FROM support_tickets WHERE id=?', (ticket_id,)),
            'answered',
        )
        self.assertEqual(
            self.value('SELECT replied_by FROM support_tickets WHERE id=?', (ticket_id,)),
            self.uid,
        )

        with sqlite3.connect(DATABASE) as db:
            db.execute('UPDATE users SET is_admin=0 WHERE id=?', (self.uid,))
        own_html = self.client.get('/py/support').get_data(as_text=True)
        self.assertIn('Ответ получен', own_html)
        self.assertIn('Попробуйте обновить страницу.', own_html)

        other = app.test_client()
        other_token = self.csrf(other)
        other.post('/py/login', data={
            'csrf_token': other_token,
            'action': 'register',
            'name': 'Другой ученик',
            'email': self.serial + '-other@example.test',
            'password': 'test-only-strong-password',
        })
        other_html = other.get('/py/support').get_data(as_text=True)
        self.assertNotIn('Не открывается задание', other_html)
        self.assertNotIn('Попробуйте обновить страницу.', other_html)

    def test_init_idempotent_and_bank_valid(self):
        before = self.value('SELECT COUNT(*) FROM guides')
        question_count = self.value('SELECT COUNT(*) FROM questions')
        module.init_sqlite_db()
        self.assertEqual(self.value('SELECT COUNT(*) FROM guides'), before)
        self.assertEqual(self.value('SELECT COUNT(*) FROM questions'), question_count)
        self.assertGreaterEqual(question_count, 800)
        with sqlite3.connect(DATABASE) as db:
            for subject in module.SUBJECTS:
                short_count = db.execute(
                    "SELECT COUNT(*) FROM questions WHERE subject=? AND part='part1' AND answer_type='short'",
                    (subject,)
                ).fetchone()[0]
                self.assertEqual(short_count, 100, subject)
                new_count = db.execute(
                    "SELECT COUNT(*) FROM questions WHERE subject=? AND part='part1' AND correct_answer<>''",
                    (subject,)
                ).fetchone()[0]
                self.assertEqual(new_count, 200, subject)
            for options, correct, answer_type, answer, accepted in db.execute(
                'SELECT options,correct_index,answer_type,correct_answer,accepted_answers FROM questions'
            ):
                option_list = json.loads(options)
                if answer_type == 'short':
                    self.assertEqual(correct, -1)
                    self.assertTrue(answer)
                    self.assertTrue(json.loads(accepted))
                    self.assertEqual(option_list, [])
                else:
                    self.assertGreaterEqual(correct, 0)
                    self.assertLess(correct, len(option_list))
                    if answer:
                        self.assertEqual(option_list[correct], answer)

    def test_generated_bank_keys_duplicates_and_ege_positions(self):
        from question_bank import build_question_bank

        questions = list(build_question_bank())
        expected_counts = {'math': 200, 'russian': 200, 'physics': 200, 'informatics': 200}
        self.assertEqual(len(questions), 800)
        for subject, expected_count in expected_counts.items():
            subset = [question for question in questions if question['subject'] == subject]
            self.assertEqual(len(subset), expected_count, subject)
            self.assertEqual(len({question['text'] for question in subset}), expected_count, subject)
            self.assertEqual(
                sum(question['answer_type'] == 'short' for question in subset), 100, subject
            )
            self.assertTrue(all(question['part'] == 'part1' for question in subset), subject)

        # FIPI 2026 maps root spelling to task 9 and suffix spelling to task 11.
        math_positions = {
            'Вычисления': 7, 'Линейные уравнения': 6, 'Проценты': 10, 'Планиметрия': 1,
            'Вероятность': 4, 'Арифметическая прогрессия': 7, 'Степени': 7,
            'Производная': 8, 'Квадратные уравнения': 6, 'Текстовые задачи': 10,
        }
        physics_positions = {
            'Кинематика': 1, 'Динамика': 2, 'Электрический ток': 11, 'Мощность': 11,
            'Работа': 3, 'Плотность': 4, 'Кинетическая энергия': 3,
            'Потенциальная энергия': 3, 'Электрические цепи': 11, 'Колебания': 4,
        }
        informatics_positions = {
            'Системы счисления': 14, 'Объём информации': 7, 'Единицы информации': 8,
            'Логика': 2, 'Python: арифметика': 5, 'Python: циклы': 6,
            'Последовательности': 5, 'Алгоритмы': 6, 'Двоичная запись': 14, 'Кодирование': 8,
        }
        for q in questions:
            positions = {
                'math': math_positions,
                'physics': physics_positions,
                'informatics': informatics_positions,
            }.get(q['subject'])
            if positions:
                self.assertEqual(q['task_number'], positions[q['section']], q['text'])
            if q['answer_type'] == 'short':
                self.assertEqual(q['correct_index'], -1, q['text'])
                self.assertEqual(json.loads(q['options']), [], q['text'])
                self.assertIn(q['correct_answer'], json.loads(q['accepted_answers']), q['text'])
            else:
                options = json.loads(q['options'])
                self.assertEqual(options[q['correct_index']], q['correct_answer'], q['text'])
            self.assertTrue(q['explanation'].strip(), q['text'])
            self.assertIn(q['correct_answer'], q['explanation'], q['text'])
            self.assertNotIn('{', q['explanation'], q['text'])
            self.assertNotIn('}', q['explanation'], q['text'])

        russian_keys = {
            'заг□реть': 'о', 'выг□реть': 'о', 'гор□ние': 'е', 'заг□р': 'а',
            'з□ря': 'а', 'з□рница': 'а', 'з□рька': 'о', 'кас□ться': 'а',
            'к□снуться': 'о', 'прик□сновение': 'о', 'кас□тельная': 'а',
            'предл□гать': 'а', 'предл□жение': 'о', 'изл□гать': 'а', 'изл□жение': 'о',
            'выращ□вать': 'и', 'раст□ние': 'е', 'р□сток': 'о', 'в□зраст': 'о',
            'выр□сти': 'а', 'выр□сший': 'о', 'подр□сток': 'о', 'отр□сль': 'а',
            'зар□сли': 'о', 'прораст□ть': 'а', 'соб□рать': 'и', 'соб□ру': 'е',
            'выб□рать': 'и', 'выб□ру': 'е', 'заб□рать': 'и', 'заб□ру': 'е',
            'расст□лать': 'и', 'заст□лить': 'е', 'выт□рать': 'и', 'выт□реть': 'е',
            'зам□рать': 'и', 'зам□реть': 'е', 'отд□рать': 'и', 'отд□ру': 'е',
            'бл□стать': 'и', 'бл□стеть': 'е', 'проб□раться': 'и', 'проб□русь': 'е',
            'расст□латься': 'и', 'заст□лать': 'и', 'выж□гать': 'и', 'выж□г': 'е',
            'переб□рать': 'и', 'переб□ру': 'е', 'соб□ратель': 'и',
        }
        russian_questions = [q for q in questions if q['subject'] == 'russian']
        self.assertEqual(len({q['text'].split('«')[1].split('»')[0] for q in russian_questions}), 50)
        for q in russian_questions:
            mask = q['text'].split('«')[1].split('»')[0]
            self.assertEqual(q['correct_answer'], russian_keys[mask], q['text'])
            expected_position = 11 if q['section'] == 'Правописание суффиксов' else 9
            self.assertEqual(q['task_number'], expected_position, q['text'])

        def captures(pattern, text):
            match = re.search(pattern, text)
            self.assertIsNotNone(match, text)
            return tuple(map(int, match.groups()))

        for q in questions:
            text = q['text']
            answer = q['correct_answer']
            section = q['section']
            if q['subject'] == 'math':
                if section == 'Вычисления':
                    a, b, c = captures(r'Вычислите: (\d+) \+ (\d+) · (\d+)', text)
                    expected = a + b * c
                elif section == 'Линейные уравнения':
                    a, b, result = captures(r'(\d+)x \+ (\d+) = (\d+)', text)
                    expected = (result - b) // a
                elif section == 'Проценты':
                    total, percent = captures(r'Товар стоил (\d+) рублей.*снизили на (\d+)%', text)
                    expected = total * percent // 100
                elif section == 'Планиметрия':
                    a, b = captures(r'сторонами (\d+) см и (\d+) см', text)
                    expected = a * b
                elif section == 'Вероятность':
                    outcomes, favorable = captures(r'опыте (\d+) равновозможных исходов, (\d+)', text)
                    expected = favorable * 100 // outcomes
                elif section == 'Арифметическая прогрессия':
                    first, step, position = captures(r'равен (\d+), разность равна (\d+).*номером (\d+)', text)
                    expected = first + (position - 1) * step
                elif section == 'Степени':
                    base, power = captures(r'значение выражения (\d+)\^(\d+)', text)
                    expected = base ** power
                elif section == 'Производная':
                    a, b, x = captures(r'f\(x\) = (\d+)x² \+ (\d+)x в точке x = (\d+)', text)
                    expected = 2 * a * x + b
                elif section == 'Квадратные уравнения':
                    square = captures(r'x² − (\d+) = 0', text)[0]
                    expected = int(square ** 0.5)
                else:
                    distance, speed = captures(r'проехал (\d+) км со скоростью (\d+) км/ч', text)
                    self.assertEqual(distance % speed, 0, text)
                    expected = distance // speed
                self.assertEqual(answer, str(expected), text)
            elif q['subject'] == 'physics':
                if section == 'Кинематика':
                    a, b = captures(r'скоростью (\d+) м/с в течение (\d+) с', text)
                    expected = a * b
                elif section == 'Динамика':
                    a, b = captures(r'массой (\d+) кг.*Ускорение равно (\d+) м/с²', text)
                    expected = a * b
                elif section in ('Электрический ток', 'Мощность', 'Электрические цепи'):
                    if section == 'Электрический ток':
                        a, b = captures(r'Напряжение на резисторе (\d+) В, сопротивление (\d+) Ом', text)
                        expected = a // b
                    elif section == 'Мощность':
                        a, b = captures(r'напряжении (\d+) В.*ток (\d+) А', text)
                        expected = a * b
                    else:
                        a, b = captures(r'сопротивлениями (\d+) Ом и (\d+) Ом', text)
                        expected = a + b
                elif section == 'Работа':
                    a, b = captures(r'Сила (\d+) Н перемещает тело на (\d+) м', text)
                    expected = a * b
                elif section == 'Плотность':
                    a, b = captures(r'Масса однородного тела (\d+) кг, объём (\d+) м³', text)
                    expected = a // b
                elif section == 'Кинетическая энергия':
                    a, b = captures(r'массой (\d+) кг движется со скоростью (\d+) м/с', text)
                    expected = a * b * b // 2
                elif section == 'Потенциальная энергия':
                    a, b = captures(r'массой (\d+) кг находится на высоте (\d+) м', text)
                    expected = a * 10 * b
                else:
                    period, duration = captures(r'Период колебаний равен (\d+) с.*за (\d+) с', text)
                    expected = duration // period
                self.assertEqual(answer, str(expected), text)
            elif q['subject'] == 'informatics':
                if section in ('Системы счисления', 'Двоичная запись'):
                    number = captures(r'число (\d+)₁₀', text)[0]
                    expected = format(number, 'b')
                elif section == 'Объём информации':
                    width, height, depth = captures(r'размером (\d+) × (\d+) пикселей.*?(\d+) битами', text)
                    expected = width * height * depth
                elif section == 'Единицы информации':
                    kib = captures(r'в (\d+) КиБ', text)[0]
                    expected = kib * 1024
                elif section == 'Логика':
                    a, b, c, d, e = captures(r'\((\d) AND (\d)\) OR \((\d) AND (\d)\) OR (\d)', text)
                    expected = int((a and b) or (c and d) or e)
                elif section == 'Python: арифметика':
                    a, b, c, d = captures(r'print\((\d+) // (\d+) \+ (\d+) % (\d+)\)', text)
                    expected = a // b + c % d
                elif section == 'Python: циклы':
                    count = captures(r'от 1 до (\d+) включительно', text)[0]
                    expected = count * (count + 1) // 2
                elif section == 'Последовательности':
                    first, step, position = captures(r'начинается с (\d+),.*на (\d+) больше.*номером (\d+)', text)
                    expected = first + step * (position - 1)
                elif section == 'Алгоритмы':
                    expected = captures(r'массива из (\d+) элементов', text)[0]
                else:
                    symbols, bits = captures(r'В сообщении (\d+) символа.*длиной (\d+) бит', text)
                    expected = symbols * bits
                self.assertEqual(answer, str(expected), text)

    def test_part2_bank_has_200_free_response_tasks_per_subject(self):
        from part2_bank import build_part2_question_bank

        questions = list(build_part2_question_bank())
        self.assertEqual(len(questions), 600)
        for subject in ('math', 'physics', 'informatics'):
            subset = [q for q in questions if q['subject'] == subject]
            self.assertEqual(len(subset), 200, subject)
            self.assertEqual(len({q['text'] for q in subset}), 200, subject)
            self.assertTrue(all(q['part'] == 'part2' for q in subset), subject)
            self.assertTrue(all(q['difficulty'] == 'part2_bank' for q in subset), subject)
            self.assertTrue(all(q['answer_type'] == 'short' for q in subset), subject)
            self.assertTrue(all(q['correct_index'] == -1 for q in subset), subject)
            self.assertTrue(all(json.loads(q['options']) == [] for q in subset), subject)
            self.assertTrue(all(q['correct_answer'] in q['explanation'] for q in subset), subject)

        self.assertEqual(
            {q['task_number'] for q in questions if q['subject'] == 'math'},
            {13, 14, 15, 16, 17, 18, 19},
        )
        self.assertEqual(
            {q['task_number'] for q in questions if q['subject'] == 'physics'},
            set(range(21, 27)),
        )
        self.assertEqual(
            {q['task_number'] for q in questions if q['subject'] == 'informatics'},
            {24, 25, 26, 27},
        )

    def test_russian_part2_prompts_are_original_and_seeded(self):
        from essay_bank import build_essay_prompt_bank

        prompts = build_essay_prompt_bank()
        self.assertEqual(len(prompts), 200)
        self.assertEqual(len({prompt['title'] for prompt in prompts}), 200)
        self.assertTrue(all(prompt['source_text'].strip() for prompt in prompts))
        self.assertTrue(all('позицию автора' in prompt['problem'] for prompt in prompts))
        self.assertEqual(self.value('SELECT COUNT(*) FROM essay_prompts'), 200)

    def test_short_answers_are_checked_and_saved(self):
        with sqlite3.connect(DATABASE) as db:
            row = db.execute(
                "SELECT id,correct_answer FROM questions WHERE subject='russian' AND answer_type='short' LIMIT 1"
            ).fetchone()
            qid, answer = row
            token = 'short-answer-' + self.serial
            db.execute(
                'INSERT INTO practice_sessions(id,user_id,subject,mode,question_ids_json) VALUES(?,?,?,?,?)',
                (token, self.uid, 'russian', 'quiz', json.dumps([qid])),
            )
        response = self.post('/py/subjects/russian/quiz/submit', {
            'practice_id': token, 'answers': {str(qid): answer.upper()},
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json['correct'], 1)
        self.assertEqual(response.json['results'][0]['answer_type'], 'short')
        self.assertEqual(
            self.value('SELECT answer_text FROM question_attempts WHERE question_id=? AND user_id=?',
                       (qid, self.uid)),
            answer.upper(),
        )
        with sqlite3.connect(DATABASE) as db:
            wrong_qid, correct_answer = db.execute(
                "SELECT id,correct_answer FROM questions WHERE subject='russian' AND answer_type='short' AND id<>? LIMIT 1",
                (qid,),
            ).fetchone()
            db.execute(
                'INSERT INTO practice_sessions(id,user_id,subject,mode,question_ids_json) VALUES(?,?,?,?,?)',
                (token + '-wrong', self.uid, 'russian', 'quiz', json.dumps([wrong_qid])),
            )
        wrong = self.post('/py/subjects/russian/quiz/submit', {
            'practice_id': token + '-wrong', 'answers': {str(wrong_qid): 'неверно'},
        })
        self.assertFalse(wrong.json['results'][0]['correct'])
        self.assertEqual(
            self.value('SELECT wrong_answer_text FROM mistake_bank WHERE question_id=? AND user_id=?',
                       (wrong_qid, self.uid)),
            'неверно',
        )
        mistake_page = self.client.get('/py/mistakes').text
        self.assertIn(correct_answer, mistake_page)

    def test_drill_accepts_free_text(self):
        with sqlite3.connect(DATABASE) as db:
            qid, task_num, answer = db.execute(
                "SELECT id,task_number,correct_answer FROM questions WHERE subject='math' AND answer_type='short' LIMIT 1"
            ).fetchone()
            token = 'short-drill-' + self.serial
            db.execute(
                'INSERT INTO practice_sessions(id,user_id,subject,mode,question_ids_json) VALUES(?,?,?,?,?)',
                (token, self.uid, 'math', 'drill', json.dumps([qid])),
            )
        html = self.client.get(f'/py/subjects/math/drill/{task_num}').text
        self.assertIn("q.answer_type === 'short'", html)
        response = self.post('/py/subjects/math/drill/answer', {
            'practice_id': token, 'question_id': qid, 'answer_text': answer, 'time_sec': 5,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json['correct'])

    def test_exam_accepts_free_text(self):
        with sqlite3.connect(DATABASE) as db:
            qid, answer = db.execute(
                "SELECT id,correct_answer FROM questions WHERE subject='math' AND answer_type='short' LIMIT 1"
            ).fetchone()
            cursor = db.execute(
                '''INSERT INTO exam_sessions(user_id,subject,mode,time_limit_min,answers_json)
                   VALUES(?,?,?,?,?)''',
                (self.uid, 'math', 'exam', 235, json.dumps({'question_ids': [qid]})),
            )
            session_id = cursor.lastrowid
        response = self.post('/py/subjects/math/exam/submit', {
            'sess_id': session_id, 'answers': {str(qid): answer},
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json['correct'], 1)

    def test_russian_rubric_2026(self):
        self.assertEqual(sum(criterion[3] for criterion in module.CHECKLIST_RUSSIAN), 22)
        self.assertEqual(len(module.CHECKLIST_RUSSIAN), 10)
        _, criteria, score = module.validate_essay(
            {'text':'Слово '*200,'checklist':{'К1':0,'К2':3,'К3':2}},'russian')
        self.assertEqual(score, 0)
        self.assertEqual(criteria['К2'], 0)
        _, _, score = module.validate_essay({'text':'Коротко','checklist':{'К1':1,'К7':3}},'russian')
        self.assertEqual(score, 0)


if __name__ == '__main__':
    unittest.main()
