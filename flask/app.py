import os, re, sqlite3, json, bcrypt
from io import BytesIO
from datetime import datetime, timedelta
from collections import OrderedDict
from flask import Flask, render_template, redirect, request, session, jsonify, g, abort, send_file
from flask_wtf.csrf import CSRFProtect, CSRFError
from security import DatabaseSessionInterface, configure_security
from assessment import start_practice, submit_practice, submit_exam, submit_drill, public_questions
from argument_content import BOOKS, CATEGORIES, MATH_REFERENCE, PROBLEMS, RUBRIC
from storage import connect_database

app = Flask(__name__, static_url_path='/py/static', static_folder='static')
app.secret_key = os.environ.get('SESSION_SECRET')
if not app.secret_key:
    raise RuntimeError('SESSION_SECRET необходимо задать в Secrets.')
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('APP_ENV') == 'production',
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=1024 * 1024,
    WTF_CSRF_TIME_LIMIT=None,
)
CSRFProtect(app)

DATABASE_URL = os.environ.get('DATABASE_URL', '')
SQLITE_PATH = os.environ.get('EGE_DB_PATH') or os.path.join(os.path.dirname(__file__), 'ege_trainer.db')
USE_SQLITE = bool(os.environ.get('EGE_DB_PATH')) or os.environ.get('EGE_DB_DRIVER') == 'sqlite'
if not USE_SQLITE and not DATABASE_URL:
    raise RuntimeError('Replit SQL Database is not connected (DATABASE_URL is missing).')
app.config.update(
    SQLITE_PATH=SQLITE_PATH,
    DATABASE_URL=DATABASE_URL,
    USE_SQLITE=USE_SQLITE,
)
configure_security(app)

SUBJECTS = {
    'math':       {'id':'math',       'title':'Математика (Профиль)', 'icon':'','description':'Алгебра, геометрия, теория вероятностей','color':'#2563eb','time_min':235,'tasks':19},
    'russian':    {'id':'russian',    'title':'Русский язык',          'icon':'','description':'Орфография, пунктуация, языковые нормы',  'color':'#16a34a','time_min':210,'tasks':27},
    'physics':    {'id':'physics',    'title':'Физика',                'icon':'','description':'Механика, электродинамика, оптика',      'color':'#9333ea','time_min':235,'tasks':30},
    'informatics':{'id':'informatics','title':'Информатика',           'icon':'','description':'Алгоритмы, программирование, информация',  'color':'#ea580c','time_min':235,'tasks':27},
}

DECEMBER_ESSAY_TOPICS = [
    'Что помогает человеку не отступать перед трудностями?',
    'Почему важно сохранять верность своим нравственным принципам?',
    'Может ли один поступок изменить жизнь человека?',
    'Какую роль в жизни человека играет память о прошлом?',
    'Почему милосердие требует внутренней силы?',
    'Что значит быть ответственным за другого человека?',
    'Всегда ли человек должен следовать голосу совести?',
    'Может ли книга повлиять на жизненный выбор человека?',
    'Что помогает поколениям понимать друг друга?',
    'В чём проявляется истинная любовь к Родине?',
]

FINAL_ESSAY_CHECKS = {
    '1': 'Ответ на тему и тезис',
    '2': 'Литературный аргумент и его связь с темой',
    '3': 'Вступление, основная часть и вывод',
    '4': 'Логика рассуждения без подмены пересказом',
    '5': 'Проверка речи, орфографии и пунктуации',
}

AVATAR_COLORS = ('#2563eb', '#7c3aed', '#db2777', '#ea580c', '#059669', '#0891b2', '#475569', '#ca8a04')
MAX_AVATAR_BYTES = 768 * 1024


def detect_avatar_mime(image_bytes):
    if image_bytes.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if image_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if len(image_bytes) >= 12 and image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
        return 'image/webp'
    return None

NEWS_SUBJECT_LABELS = {
    'math': 'Математика',
    'russian': 'Русский язык',
    'physics': 'Физика',
    'informatics': 'Информатика',
}

EXAM_TIMES = {'math':235,'russian':210,'physics':235,'informatics':235}

CHECKLIST_RUSSIAN = [
    ('К1','Позиция автора','Позиция автора по указанной проблеме сформулирована верно',1),
    ('К2','Комментарий к позиции автора','Два примера с пояснением, смысловая связь и её пояснение',3),
    ('К3','Собственное отношение','Позиция обоснована и приведён пример-аргумент',2),
    ('К4','Фактическая точность','Фактических ошибок нет',1),
    ('К5','Логичность речи','Нет логических ошибок — 2; одна-две — 1',2),
    ('К6','Этические нормы','Этические ошибки отсутствуют',1),
    ('К7','Орфографические нормы','Нет ошибок — 3; одна-две — 2; три-четыре — 1',3),
    ('К8','Пунктуационные нормы','Нет ошибок — 3; одна-две — 2; три-четыре — 1',3),
    ('К9','Грамматические нормы','Нет ошибок — 3; одна-две — 2; три-четыре — 1',3),
    ('К10','Речевые нормы','Нет ошибок — 3; одна-две — 2; три-четыре — 1',3),
]

@app.context_processor
def rubric_context():
    return {'checklist_caps':{key:cap for key,title,description,cap in CHECKLIST_RUSSIAN},
            'checklist_names':{key:title for key,title,description,cap in CHECKLIST_RUSSIAN}}

# Обёртка курсора SQLite
class SQLiteCursor:
    def __init__(self, cur):
        self._cur = cur
        self._lastrowid = None

    def execute(self, sql, params=None):
        has_ret = bool(re.search(r'\bRETURNING\b', sql, re.IGNORECASE))
        if has_ret:
            sql = re.sub(r'\s+RETURNING\s+\w+', '', sql, flags=re.IGNORECASE)
        sql = sql.replace('%s', '?')
        self._cur.execute(sql, params or [])
        self._lastrowid = self._cur.lastrowid
        self._returning = has_ret

    def fetchone(self):
        if getattr(self, '_returning', False):
            return {'id': self._lastrowid}
        row = self._cur.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(r) for r in self._cur.fetchall()]

    @property
    def rowcount(self):
        return self._cur.rowcount

def get_db():
    if 'db' not in g:
        g.db = connect_database(app.config)
        g.use_sqlite = USE_SQLITE
    return g.db

def get_cursor():
    db = get_db()
    return SQLiteCursor(db.cursor()) if g.get('use_sqlite') else db.cursor()

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db:
        try: db.close()
        except: pass

def parse_date(val):
    if val is None: return None
    if isinstance(val, datetime): return val
    for fmt in ('%Y-%m-%d %H:%M:%S','%Y-%m-%d %H:%M:%S.%f','%Y-%m-%d'):
        try: return datetime.strptime(str(val), fmt)
        except ValueError: pass
    return None

@app.template_filter('short_timestamp')
def short_timestamp(value, length=10):
    if value is None:
        return ''
    if isinstance(value, datetime):
        value = value.strftime('%Y-%m-%d %H:%M:%S')
    return str(value)[:int(length)]

# Инициализация базы данных
def init_sqlite_db():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, xp INTEGER NOT NULL DEFAULT 0,
            tests_completed INTEGER NOT NULL DEFAULT 0,
            avatar_emoji TEXT NOT NULL DEFAULT '',
            avatar_color TEXT NOT NULL DEFAULT '#2563eb',
            avatar_image BLOB,
            avatar_image_mime TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL, part TEXT NOT NULL,
            task_number INTEGER NOT NULL DEFAULT 1,
            section TEXT NOT NULL DEFAULT '',
            difficulty TEXT NOT NULL DEFAULT 'base',
            text TEXT NOT NULL, options TEXT NOT NULL,
            correct_index INTEGER NOT NULL,
            answer_type TEXT NOT NULL DEFAULT 'choice',
            correct_answer TEXT NOT NULL DEFAULT '',
            accepted_answers TEXT NOT NULL DEFAULT '[]',
            explanation TEXT,
            wrong_explanations TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS test_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            subject TEXT NOT NULL, score INTEGER NOT NULL,
            questions_count INTEGER NOT NULL DEFAULT 0,
            mode TEXT NOT NULL DEFAULT 'quiz',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS question_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            question_id INTEGER NOT NULL REFERENCES questions(id),
            answer_idx INTEGER NOT NULL,
            answer_text TEXT NOT NULL DEFAULT '',
            is_correct INTEGER NOT NULL DEFAULT 0,
            time_sec INTEGER NOT NULL DEFAULT 0,
            mode TEXT NOT NULL DEFAULT 'quiz',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS exam_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            subject TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'exam',
            time_limit_min INTEGER NOT NULL DEFAULT 235,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMP,
            score INTEGER, correct INTEGER, total INTEGER,
            answers_json TEXT DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS mistake_bank (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            question_id INTEGER NOT NULL REFERENCES questions(id),
            wrong_answer_idx INTEGER NOT NULL,
            wrong_answer_text TEXT NOT NULL DEFAULT '',
            review_count INTEGER NOT NULL DEFAULT 0,
            next_review TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, question_id)
        );
        CREATE TABLE IF NOT EXISTS essay_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            subject TEXT NOT NULL,
            essay_type TEXT NOT NULL DEFAULT 'ege',
            essay_prompt_id INTEGER,
            essay_topic TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL,
            word_count INTEGER NOT NULL DEFAULT 0,
            checklist_json TEXT DEFAULT '{}',
            self_score INTEGER DEFAULT 0,
            teacher_score INTEGER,
            teacher_result TEXT,
            teacher_comment TEXT,
            teacher_criteria_json TEXT DEFAULT '{}',
            teacher_graded_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS essay_prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL UNIQUE,
            source_text TEXT NOT NULL,
            problem TEXT NOT NULL,
            analysis TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS theory_sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL, title TEXT NOT NULL,
            content TEXT NOT NULL, order_index INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS task_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL, task_number INTEGER NOT NULL,
            title TEXT NOT NULL, content TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS guides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL, category TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL, content TEXT NOT NULL, url TEXT
        );
        CREATE TABLE IF NOT EXISTS news_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, content TEXT NOT NULL,
            year INTEGER NOT NULL DEFAULT 2026,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS news_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            subject TEXT NOT NULL DEFAULT '',
            year INTEGER NOT NULL DEFAULT 2026,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','published','rejected')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TIMESTAMP,
            reviewed_by INTEGER REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_news_suggestions_user
            ON news_suggestions(user_id, id);
        CREATE INDEX IF NOT EXISTS idx_news_suggestions_status
            ON news_suggestions(status, id);
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            subject TEXT NOT NULL,
            question TEXT NOT NULL,
            admin_reply TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open'
                CHECK(status IN ('open','answered')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            replied_at TIMESTAMP,
            replied_by INTEGER REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_support_tickets_user
            ON support_tickets(user_id, id);
        CREATE INDEX IF NOT EXISTS idx_support_tickets_status
            ON support_tickets(status, updated_at);
        CREATE TABLE IF NOT EXISTS practice_sessions (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            subject TEXT NOT NULL, mode TEXT NOT NULL,
            question_ids_json TEXT NOT NULL,
            result_json TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS web_sessions (
            id TEXT PRIMARY KEY, data TEXT NOT NULL, expires_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_throttle (
            key TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0,
            window_start REAL NOT NULL
        );
    ''')

    # Обновление схемы старых баз данных
    for col_def in [
        ('questions','task_number','INTEGER NOT NULL DEFAULT 1'),
        ('questions','section','TEXT NOT NULL DEFAULT ""'),
        ('questions','difficulty','TEXT NOT NULL DEFAULT "base"'),
        ('questions','wrong_explanations','TEXT DEFAULT "{}"'),
        ('questions','answer_type','TEXT NOT NULL DEFAULT "choice"'),
        ('questions','correct_answer','TEXT NOT NULL DEFAULT ""'),
        ('questions','accepted_answers','TEXT NOT NULL DEFAULT "[]"'),
        ('question_attempts','answer_text','TEXT NOT NULL DEFAULT ""'),
        ('mistake_bank','wrong_answer_text','TEXT NOT NULL DEFAULT ""'),
        ('test_results','mode','TEXT NOT NULL DEFAULT "quiz"'),
        ('guides','category','TEXT NOT NULL DEFAULT ""'),
        ('users','is_admin','INTEGER NOT NULL DEFAULT 0'),
        ('users','disabled','INTEGER NOT NULL DEFAULT 0'),
        ('users','avatar_emoji',"TEXT NOT NULL DEFAULT ''"),
        ('users','avatar_color',"TEXT NOT NULL DEFAULT '#2563eb'"),
        ('users','avatar_image','BLOB'),
        ('users','avatar_image_mime',"TEXT NOT NULL DEFAULT ''"),
        ('news_items','subject','TEXT NOT NULL DEFAULT ""'),
        ('essay_submissions','teacher_score','INTEGER'),
        ('essay_submissions','teacher_comment','TEXT'),
        ('essay_submissions','teacher_criteria_json','TEXT DEFAULT "{}"'),
        ('essay_submissions','teacher_graded_at','TIMESTAMP'),
        ('essay_submissions','resubmit_count','INTEGER NOT NULL DEFAULT 0'),
        ('essay_submissions','essay_prompt_id','INTEGER'),
        ('essay_submissions','essay_type',"TEXT NOT NULL DEFAULT 'ege'"),
        ('essay_submissions','essay_topic',"TEXT NOT NULL DEFAULT ''"),
        ('essay_submissions','teacher_result','TEXT'),
    ]:
        columns = {row[1] for row in conn.execute(f'PRAGMA table_info({col_def[0]})')}
        if col_def[1] not in columns:
            conn.execute(f'ALTER TABLE {col_def[0]} ADD COLUMN {col_def[1]} {col_def[2]}')

    cur = conn.cursor()
    from content_fixes import correct_question_bank
    correct_question_bank(conn)
    from question_bank import seed_question_bank
    added_questions = seed_question_bank(conn)
    if added_questions:
        app.logger.info('Added %s supplementary practice questions', added_questions)
    from part2_bank import seed_part2_question_bank
    added_part2 = seed_part2_question_bank(conn)
    if added_part2:
        app.logger.info('Added %s extended-response practice questions', added_part2)
    from essay_bank import seed_essay_prompt_bank
    added_essay_prompts = seed_essay_prompt_bank(conn)
    if added_essay_prompts:
        app.logger.info('Added %s original Russian essay practice prompts', added_essay_prompts)

    cur.execute('SELECT COUNT(*) FROM questions')
    if cur.fetchone()[0] == 0:
        raise RuntimeError('В базе данных нет заданий. Восстановите файл ege_trainer.db.')

    # Разделы теории
    cur.execute('SELECT COUNT(*) FROM theory_sections')
    if cur.fetchone()[0] == 0:
        conn.executemany('INSERT INTO theory_sections(subject,title,content,order_index) VALUES(?,?,?,?)', [
            ('math','Степени и логарифмы','aⁿ = a·a·…·a (n раз). logₐb=c ⟺ aᶜ=b.\nlogₐ(mn)=logₐm+logₐn. log перехода: logₐb=lgb/lga.',1),
            ('math','Производная и применения','(xⁿ)′=n·xⁿ⁻¹, (eˣ)′=eˣ, (ln x)′=1/x, (sin x)′=cos x, (cos x)′=−sin x.\nТочка максимума: f′=0, f″<0. Минимума: f″>0.',2),
            ('math','Геометрия: формулы','Круг: S=πr², L=2πr. Шар: V=4/3·πr³. Цилиндр: V=πr²h. Конус: V=1/3·πr²h.\nПифагор: a²+b²=c². Косинус: c²=a²+b²−2ab·cosC.',3),
            ('russian','Орфография: корни','Гар-/гор-: без уд. → О. Зар-/зор-: без уд. → А. Кас-/кос-: перед -а- → А.\nЛаг-/лож-: перед г→А, перед ж→О. Бир/бер, дир/дер, тир/тер: перед -а-→И.',1),
            ('russian','Пунктуация: запятая','ССП: [ ], и [ ] — запятая. СПП: [ ], (что/который). Деепричастный оборот: , ДО ,.\nОднородные члены с повт. союзом: О, и О, и О.',2),
            ('physics','Механика','v=v₀+at, s=v₀t+at²/2, v²=v₀²+2as. F=ma. Закон сохр. импульса: Σmv=const.\nРабота: A=Fs·cosα. Энергия: Eₖ=mv²/2, Ep=mgh.',1),
            ('physics','Электричество','Закон Ома: I=U/R. Мощность: P=UI=I²R. Последовательно: R=R₁+R₂.\nПараллельно: 1/R=1/R₁+1/R₂. Заряд: q=It.',2),
            ('informatics','Системы счисления','2¹⁰=1024 (1КиБ). Перевод: делить на основание, остатки снизу вверх.\n8 бит=1 байт, 1024 байт=1 КиБ, 1024 КиБ=1 МиБ.',1),
            ('informatics','Алгоритмы и сложность','Линейный поиск O(n). Двоичный поиск O(log n). Сортировка слиянием O(n·log n).\nРекурсия: функция вызывает себя с меньшим аргументом до базового случая.',2),
        ])

    # Новости
    cur.execute('SELECT COUNT(*) FROM news_items')
    if cur.fetchone()[0] == 0:
        conn.executemany('INSERT INTO news_items(title,content,year) VALUES(?,?,?)', [
            ('ЕГЭ 2026: расписание основного периода','Основной период: с 23 мая по 19 июня 2026 года. Резервные дни: 23–28 июня.',2026),
            ('Новые демоверсии ФИПИ 2026','На сайте ФИПИ размещены КИМ 2026 года по всем предметам. Скачать можно на fipi.ru.',2026),
            ('Изменения в ЕГЭ по математике 2026','В задании 15 (профиль) уточнены критерии оценивания. Максимум по части 2 — 32 первичных балла.',2026),
            ('Минимальные баллы ЕГЭ 2026','Для поступления: математика профиль — 39, русский — 36, физика — 39, информатика — 44.',2026),
        ])

    # Разбор заданий
    cur.execute('SELECT COUNT(*) FROM task_analyses')
    if cur.fetchone()[0] == 0:
        conn.executemany('INSERT INTO task_analyses(subject,task_number,title,content) VALUES(?,?,?,?)', [
            ('math',1,'Задание 1: Вычисления и преобразования','Типичная ошибка: путают порядок операций. Всегда сначала скобки, потом степени, потом умножение/деление.\nСтратегия: если ответ не сходится, проверьте вычисление каждого шага отдельно.\nВремя: не более 2 минут.'),
            ('math',4,'Задание 4: Теория вероятностей','Ключевая формула: P = (число благоприятных исходов) / (общее число исходов).\nЧасто встречаются задачи на статистику (относительная частота) и комбинаторику.\nВремя: 3–4 минуты.'),
            ('math',13,'Задание 13: Производная (профиль)','Алгоритм: 1) Найти f′(x). 2) Приравнять к нулю. 3) Найти знак f″ в критических точках.\nНе забывайте область определения! Время: 5–7 минут.'),
            ('russian',7,'Задание 7: Морфологические нормы','Частые ошибки: 1) Падеж после предлогов (благодаря — Д.п., согласно — Д.п.).\n2) Степени прилагательных (нельзя «более красивее»). 3) Числительные (двухсот, а не двухста).'),
            ('russian',8,'Задание 8: Синтаксические нормы','Проверяйте: 1) Согласование подлежащего и сказуемого. 2) Деепричастный оборот (субъект действия).\n3) Причастный оборот (место определяемого слова).'),
            ('informatics',2,'Задание 2: Системы счисления','Выучите степени двойки до 2¹⁰=1024. Алгоритм перевода: деление на основание, запись остатков снизу вверх.\nДля перевода из 2 в 16: группируйте по 4 бита справа.'),
        ])

    # Материалы для подготовки
    guides_data = [
        ('math','Стратегия','Стратегия на экзамене',
         'Часть 1 (12 заданий — 1 балл каждое = 12 первичных):\n• Задания 1–12 — с кратким ответом\n• Не тратьте >5 мин на одно задание\n• Перепроверьте все ответы\n\nЧасть 2 (7 заданий):\n• 13, 14 — 2 балла\n• 15, 16, 17 — 3 балла  \n• 18, 19 — 4 балла\n• Пишите полное решение с обоснованием\n• Если не знаете — напишите хоть что-то: за частичное решение дают баллы',''),
        ('math','Формулы','Степени и корни',
         '√a · √b = √(ab)       √a / √b = √(a/b)\naⁿ · aᵐ = aⁿ⁺ᵐ         aⁿ / aᵐ = aⁿ⁻ᵐ\n(aⁿ)ᵐ = aⁿᵐ             a⁰ = 1  (a ≠ 0)\na⁻ⁿ = 1/aⁿ              a^(1/n) = ⁿ√a\na^(m/n) = ⁿ√(aᵐ)        (√a)² = a  (a≥0)',''),
        ('math','Формулы','Логарифмы',
         'logₐ(mn) = logₐm + logₐn\nlogₐ(m/n) = logₐm − logₐn\nlogₐ(mⁿ) = n·logₐm\nlogₐb = lgb / lga  (формула перехода)\nlogₐa = 1\nlogₐ1 = 0\nln = log_e ≈ log₂.₇₁₈\nlg = log₁₀\n\nСвойство: a^(logₐb) = b',''),
        ('math','Формулы','Тригонометрия',
         'Основное тождество: sin²x + cos²x = 1\ntg x = sin x/cos x   ctg x = cos x/sin x\n1+tg²x = 1/cos²x     1+ctg²x = 1/sin²x\n\nФормулы сложения:\nsin(α±β) = sinα·cosβ ± cosα·sinβ\ncos(α±β) = cosα·cosβ ∓ sinα·sinβ\n\nДвойной угол:\nsin 2α = 2·sinα·cosα\ncos 2α = cos²α − sin²α = 1−2sin²α',''),
        ('math','Формулы','Производные',
         '(c)′ = 0               (xⁿ)′ = n·xⁿ⁻¹\n(√x)′ = 1/(2√x)        (eˣ)′ = eˣ\n(ln x)′ = 1/x          (aˣ)′ = aˣ·ln a\n(sin x)′ = cos x       (cos x)′ = −sin x\n(tg x)′ = 1/cos²x      (ctg x)′ = −1/sin²x\n\nПравила:\n(u+v)′ = u′+v′\n(u·v)′ = u′v + uv′\n(u/v)′ = (u′v − uv′)/v²\n(f(g(x)))′ = f′(g(x))·g′(x)  — цепное правило',''),
        ('math','Формулы','Геометрия: площади и объёмы',
         'Площади:\nПрямоугольник: S = ab\nТреугольник: S = ½·a·h = ½·a·b·sinC\nКруг: S = πr²   Сектор: S = ½r²φ\nТрапеция: S = ½·(a+b)·h\nПараллелограмм: S = a·h\n\nОбъёмы:\nПрямоугольный параллелепипед: V = abc\nЦилиндр: V = πr²h\nКонус: V = ⅓πr²h, S бок = πrl\nШар: V = ⁴⁄₃πr³, S = 4πr²\nПирамида: V = ⅓·S осн·h',''),
        ('math','Алгоритмы','Решение квадратного уравнения',
         'ax² + bx + c = 0\n\nД = b² − 4ac\n\nЕсли Д > 0: два корня\n  x₁,₂ = (−b ± √Д) / 2a\n\nЕсли Д = 0: один корень (двукратный)\n  x = −b / 2a\n\nЕсли Д < 0: действительных корней нет\n\nТеорема Виета (для приведённого: x²+px+q=0):\n  x₁+x₂ = −p\n  x₁·x₂ = q',''),
        ('math','Алгоритмы','Исследование функции на экстремум',
         'Алгоритм нахождения экстремумов f(x):\n1. Найти область определения\n2. Вычислить f′(x)\n3. Найти критические точки: f′(x) = 0 или ∄\n4. Исследовать знак f′ около критических точек:\n   — минус → плюс: минимум\n   — плюс → минус: максимум\n5. Или: f″(x) в критической точке:\n   f″ < 0 → максимум\n   f″ > 0 → минимум',''),


        ('russian','Стратегия','Стратегия на экзамене',
         'Часть 1 (26 заданий = 33 первичных балла):\n• Задания 1–26 — тест и краткий ответ\n• Читайте текст внимательно ПЕРЕД заданиями\n• Время на часть 1: ~90 минут\n\nЧасть 2 (задание 27 = 25 первичных баллов):\n• Сочинение-рассуждение по прочитанному тексту\n• Минимум 150 слов (иначе — 0 за К1–К4)\n• Оптимально: 200–250 слов\n• Время: 90–120 минут\n\nОбщее время: 3 ч 30 мин. Оставьте 15 мин на проверку.',''),
        ('russian','Орфография','Чередующиеся гласные в корне',
         'ГАР-/ГОР-: без ударения → О\n  загорать, пригореть (НО: гарь — под ударением)\n\nЗАР-/ЗОР-: без ударения → А\n  заря, зарница (НО: зорька — под ударением)\n\nКАС-/КОС-: перед -А- → А, иначе → О\n  касаться, но коснуться\n\nЛАГ-/ЛОЖ-: перед Г → А, перед Ж → О\n  предлагать, но предложить\n\nРАСТ-/РАЩ-/РОС-: перед СТ и Щ → А\n  расти, выращивать, НО: выросший\n  Исключения: росток, отрасль, Ростов\n\nБИР/БЕР, МИР/МЕР, ТИР/ТЕР: перед -А- → И\n  собирать — соберу, замирать — замереть',''),
        ('russian','Пунктуация','Запятая: основные случаи',
         '1. Однородные члены (без союза): О, О, О\n2. Однородные с повторяющимся союзом: О, и О, и О\n3. Противительный союз: О, а/но/да О\n4. ССП (два подлежащих): [ ], и [ ]\n   НО: [ и ] — одно подлежащее, запятой нет\n\n5. СПП: главное отделяется от придаточного\n   [Я знаю], (что ты придёшь.)\n   (Когда ты придёшь), [я буду дома.]\n\n6. Деепричастный оборот: ,ДО,\n7. Причастный оборот после определяемого: ,ПО,\n8. Вводные слова: ,однако, ,во-первых, ,кажется,',''),
        ('russian','Нормы','Трудные ударения (частые на ЕГЭ)',
         'ГЛАГОЛЫ — прошедшее время:\nбрАла, взялА, далА, жилА, лгалА, рвалА, спалА\nпонялА, нАчал, началА, нАчали\n\nГЛАГОЛЫ — настоящее/будущее:\nзвонИть → звонИшь, звонИт (не звОнит!)\nвключИть → включИт\n\nСУЩЕСТВИТЕЛЬНЫЕ:\nжалюзИ, катАлог, квартАл, нОвости\nтОрты, шАрфы, сирОты, бАнты\nдоговОр (разг. дОговор — нежелательно)\n\nПРИЛАГАТЕЛЬНЫЕ:\nкрасИвее, красИвейший (не красивЕе)',''),
        ('russian','Нормы','Морфологические нормы: частые ошибки',
         'СУЩЕСТВИТЕЛЬНЫЕ в Р.п. мн.ч.:\nносков (носок), чулок (чулка), сапог (сапога)\nяблок (яблоко), мест (место), дел (дело)\n\nЧИСЛИТЕЛЬНЫЕ:\nпятьюстами, шестьюстами (не пятистами!)\nоколо двухсот, двухтысячный\n\nПРЕДЛОГИ + падеж:\nБЛАГОДАРЯ — Д.п. (благодаря другу)\nСОГЛАСНО — Д.п. (согласно приказу)\nВОПРЕКИ — Д.п. (вопреки ожиданиям)\nПО ОКОНЧАНИИ — не «по окончанию»\nВ СИЛУ — Р.п. (в силу обстоятельств)',''),
        ('russian','Сочинение','Структура сочинения (задание 27)',
         '1. ВСТУПЛЕНИЕ (2–3 предложения)\n   Подведение к проблеме через тему, цитату, риторический вопрос\n\n2. ПРОБЛЕМА\n   «В тексте [автор] поднимает проблему …»\n   «Автор задаётся вопросом: …?»\n\n3. КОММЕНТАРИЙ (2 примера из текста)\n   Пример 1 → пояснение (что это значит)\n   Пример 2 → пояснение\n   Смысловая связь: «Эти примеры противопоставлены / дополняют друг друга / …»\n\n4. ПОЗИЦИЯ АВТОРА\n   «Автор убеждён, что…» / «Позиция автора такова: …»\n\n5. СВОЯ ПОЗИЦИЯ + обоснование\n   Согласие/несогласие + аргумент (пример из жизни, литературы)\n\n6. ЗАКЛЮЧЕНИЕ\n   Вывод, перекликающийся со вступлением\n\nМинимум: 150 слов. Оптимально: 200–250 слов.',''),
        ('russian','Сочинение','Речевые клише для сочинения',
         'ДЛЯ ФОРМУЛИРОВКИ ПРОБЛЕМЫ:\n«Автор текста [ФИО] обращается к проблеме…»\n«В центре внимания автора — вопрос о…»\n«Текст заставляет задуматься о…»\n\nДЛЯ КОММЕНТАРИЯ:\n«Чтобы привлечь внимание читателя, автор…»\n«Автор не случайно описывает / акцентирует / сравнивает…»\n«Этот пример показывает, что…»\n«Оба примера связаны: они [противопоставлены / дополняют / подтверждают]…»\n\nДЛЯ ПОЗИЦИИ АВТОРА:\n«Автор убеждён, что…» / «По мнению автора,…»\n«Позиция автора выражена чётко:…»\n\nДЛЯ СВОЕЙ ПОЗИЦИИ:\n«Я согласен с позицией автора и считаю, что…»\n«Трудно не согласиться с тем, что…»',''),


        ('physics','Стратегия','Стратегия на экзамене',
         'Часть 1 (24 задания):\n• 1–4: вычисление по формуле (1 балл)\n• 5–22: тест с выбором / множественный выбор (2 балла)\n• 23–24: соответствие графиков (2 балла)\n\nЧасть 2 (8 заданий = 34 балла):\n• Полное решение с физическим смыслом\n• Записывайте все законы ПЕРЕД подстановкой\n• Единицы должны быть в СИ!\n\nАлгоритм решения задачи:\n1. Дано: запишите все величины с единицами\n2. Перевести в СИ\n3. Нарисуйте схему/график\n4. Запишите закон(ы)\n5. Выразите искомое, подставьте числа\n6. Проверьте размерность',''),
        ('physics','Формулы','Механика: кинематика',
         'Равномерное:\nv = s/t   →   s = v·t\n\nРавноускоренное:\nv = v₀ + a·t\ns = v₀t + ½at²\nv² = v₀² + 2as\n(v+v₀)/2 = s/t\n\nСвободное падение (a = g ≈ 10 м/с², v₀=0):\nv = g·t\nh = ½·g·t²\nv² = 2gh\n\nДвижение по окружности:\nv = 2πr/T = 2πrn\naцс = v²/r = ω²r\nω = 2π/T, ω = 2πn',''),
        ('physics','Формулы','Механика: динамика',
         'II закон Ньютона: F⃗ = m·a⃗\nIII закон Ньютона: F₁₂ = −F₂₁\n\nСила тяжести: Fg = mg  (g ≈ 10 м/с²)\nСила трения: Fтр = μ·N\nСила упругости: F = k·x  (закон Гука)\n\nВсемирное тяготение:\nF = G·m₁m₂/r²   (G = 6,67·10⁻¹¹)\n\nИмпульс: p = m·v\nЗСИ: Σp = const  (замкнутая система)\n\nРабота: A = F·s·cosα\nЭнергия: Eₖ = mv²/2, Ep = mgh\nЗСЭ: Eₖ + Ep = const  (замкнутая)',''),
        ('physics','Формулы','Электричество и магнетизм',
         'Закон Кулона: F = kq₁q₂/r²  (k=9·10⁹)\nЭ. поле: E = F/q = kQ/r²\nРабота: A = q(φ₁−φ₂) = qU\n\nЗакон Ома: I = U/R\nПоследовательно: R = R₁+R₂, I = const\nПараллельно: 1/R = 1/R₁+1/R₂, U = const\n\nМощность: P = UI = I²R = U²/R\nЭнергия: W = Pt = UIt\n\nЭДС: ε = A/q, I = ε/(R+r)\nМагн. поле: F = qvB·sinα (сила Лоренца)\nСила Ампера: F = BIl·sinα',''),
        ('physics','Формулы','Термодинамика',
         'Идеальный газ: pV = νRT = NkT\nR = 8,314 Дж/(моль·К)\nk = 1,38·10⁻²³ Дж/К, NA = 6,02·10²³\n\nИзопроцессы (m=const):\n• Изотерма (T=const): p₁V₁ = p₂V₂\n• Изобара (p=const): V₁/T₁ = V₂/T₂\n• Изохора (V=const): p₁/T₁ = p₂/T₂\n\nI начало термодинамики:\nΔU = Q − A (теплота − работа газа)\n\nКПД тепловой машины:\nη = (Q₁−Q₂)/Q₁ = 1 − T₂/T₁\nη ≤ η_Карно',''),


        ('informatics','Стратегия','Стратегия на экзамене',
         'Часть 1 (23 задания = 23 балла):\n• Задания 1–23 — тест и краткий ответ\n• Компьютер разрешён для заданий 9–23!\n• Время: ≈2 часа\n\nЧасть 2 (4 задания = 14 баллов):\n• 24: работа с файлами/данными (2 балла)\n• 25, 26: алгоритм/программа (3 балла)\n• 27: оптимизирующая программа (4 балла)\n\nОбщее время: 3 ч 55 мин\n\nТактика:\n1. Сначала решите лёгкие (1–16)\n2. Потом средние (17–23)\n3. В конце — программирование (24–27)\nИспользуйте Python для заданий 24–27',''),
        ('informatics','Системы счисления','Степени двойки — обязательно наизусть',
         '2⁰ = 1       2¹ = 2       2² = 4\n2³ = 8       2⁴ = 16      2⁵ = 32\n2⁶ = 64      2⁷ = 128     2⁸ = 256\n2⁹ = 512     2¹⁰ = 1024   2¹¹ = 2048\n2¹² = 4096   2¹³ = 8192   2¹⁶ = 65536\n\nДесятичное → Двоичное:\nДели на 2, пиши остатки снизу вверх\n\nПример: 25 ÷ 2\n25 → 12 ост.1\n12 → 6  ост.0\n6  → 3  ост.0\n3  → 1  ост.1\n1  → 0  ост.1\nЧитаем снизу: 11001₂',''),
        ('informatics','Системы счисления','Единицы информации',
         '1 байт = 8 бит\n1 КиБ = 1024 байт = 2¹⁰ байт\n1 МиБ = 1024 КиБ = 2²⁰ байт\n1 ГиБ = 1024 МиБ = 2³⁰ байт\n1 ТиБ = 1024 ГиБ = 2⁴⁰ байт\n\nКоличество информации:\nI = log₂N (бит), где N — число равновероятных событий\n\nОбъём изображения:\nV = ширина × высота × глубина цвета (бит)\nПример: 800×600 × 24 бит = 14 400 000 бит = 1 800 000 байт ≈ 1,72 МиБ\n\nОбъём звука:\nV = частота × разрядность × каналы × время',''),
        ('informatics','Алгоритмы','Python: шпаргалка для задания 27',
         'ВВОД:\nn = int(input())\na, b = map(int, input().split())\narr = list(map(int, input().split()))\n\nВЫВОД:\nprint(result)\nprint(*arr)  # элементы через пробел\n\nСПИСКИ:\narr.sort()              # сортировка по возрастанию\narr.sort(reverse=True)  # убывание\nmin(arr), max(arr)\nsum(arr)\nlen(arr)\narr.append(x)\narr.count(x)            # количество вхождений\n\nСЛОВАРЬ:\nd = {}\nfor x in arr:\n    d[x] = d.get(x, 0) + 1  # подсчёт частоты\n\nЦИКЛЫ:\nfor i in range(n):      # 0..n-1\nfor i in range(1,n+1):  # 1..n\nfor x in arr:\nwhile условие:',''),
        ('informatics','Логика','Логические операции и законы',
         'Таблицы истинности:\nAND: 1∧1=1, остальное 0\nOR:  0∨0=0, остальное 1\nNOT: ¬0=1, ¬1=0\nXOR: 0⊕0=0, 0⊕1=1, 1⊕0=1, 1⊕1=0\n\nЗАКОНЫ ДЕ МОРГАНА:\n¬(A∧B) = ¬A∨¬B\n¬(A∨B) = ¬A∧¬B\n\nИМПЛИКАЦИЯ:\nA→B = ¬A∨B\nА→В ложь только при: A=1, B=0\n\nЭКВИВАЛЕНТНОСТЬ:\nA≡B = (A→B)∧(B→A)\n\nПОРЯДОК ОПЕРАЦИЙ:\n¬ (NOT) > ∧ (AND) > ∨ (OR) > → (IMPL) > ≡ (EQ)',''),
    ]
    for material in guides_data:
        exists = conn.execute(
            'SELECT id FROM guides WHERE subject=? AND category=? AND title=?',
            material[:3]
        ).fetchone()
        if not exists:
            conn.execute('INSERT INTO guides(subject,category,title,content,url) VALUES(?,?,?,?,?)', material)
    from study_materials import seed_learning_content
    seed_learning_content(conn)

    # Старый опубликованный в исходнике пароль не должен давать доступ к админке.
    row = conn.execute("SELECT id,password_hash FROM users WHERE email=?", ('admin@ege-trainer.ru',)).fetchone()
    if row:
        try:
            compromised = bcrypt.checkpw(b'Admin2026!', row[1].encode())
        except (ValueError, TypeError):
            compromised = True
        if compromised:
            conn.execute('UPDATE users SET disabled=1,is_admin=0 WHERE id=?', (row[0],))

    conn.commit()
    conn.close()
    app.logger.info('SQLite database ready')


def seed_postgres_content():
    """Merge only shared study content from the bundled SQLite snapshot.

    Student accounts, scores, essays, sessions, and other user data are never
    copied from the source file by this startup path.
    """
    from urllib.parse import quote

    if not os.path.isfile(SQLITE_PATH):
        raise RuntimeError('Не найден источник учебных материалов для PostgreSQL.')

    source_uri = 'file:' + quote(os.path.abspath(SQLITE_PATH)) + '?mode=ro'
    source = sqlite3.connect(source_uri, uri=True)
    source.row_factory = sqlite3.Row
    db = connect_database(app.config)
    content_keys = {
        'questions': ('subject', 'part', 'task_number', 'section', 'text'),
        'essay_prompts': ('title',),
        'theory_sections': ('subject', 'title', 'content', 'order_index'),
        'task_analyses': ('subject', 'task_number', 'title', 'content'),
        'guides': ('subject', 'category', 'title', 'content', 'url'),
        'news_items': ('title', 'content', 'year', 'subject'),
    }
    try:
        db.execute('SELECT pg_advisory_xact_lock(481927604)')
        inserted_counts = {}
        for table, key_columns in content_keys.items():
            rows = source.execute(f'SELECT * FROM {table}').fetchall()
            if not rows:
                inserted_counts[table] = 0
                continue
            source_columns = [column[0] for column in source.execute(
                f'SELECT * FROM {table} LIMIT 0'
            ).description]
            target_columns = {
                row['column_name'] for row in db.execute(
                    '''SELECT column_name FROM information_schema.columns
                       WHERE table_schema=current_schema() AND table_name=?''',
                    (table,),
                ).fetchall()
            }
            if not target_columns or not set(key_columns).issubset(target_columns):
                raise RuntimeError(f'В PostgreSQL отсутствует нужная схема таблицы {table}.')
            columns = [column for column in source_columns
                       if column != 'id' and column in target_columns]
            if not set(key_columns).issubset(columns):
                raise RuntimeError(f'В SQLite не хватает ключевых полей таблицы {table}.')
            selected_keys = ','.join(f'"{column}"' for column in key_columns)
            existing_keys = {
                tuple(row[column] for column in key_columns)
                for row in db.execute(f'SELECT {selected_keys} FROM {table}').fetchall()
            }
            column_sql = ','.join(f'"{column}"' for column in columns)
            values_sql = ','.join('?' for _ in columns)
            insert_sql = f'INSERT INTO {table} ({column_sql}) VALUES ({values_sql})'
            inserted_counts[table] = 0
            for row in rows:
                key = tuple(row[column] for column in key_columns)
                if key in existing_keys:
                    continue
                db.execute(insert_sql, tuple(row[column] for column in columns))
                existing_keys.add(key)
                inserted_counts[table] += 1

        if not db.execute('SELECT COUNT(*) FROM questions').fetchone()[0]:
            raise RuntimeError('В базе PostgreSQL нет заданий; содержимое SQLite не перенесено.')

        for table in content_keys:
            db.execute(
                f"""SELECT setval(pg_get_serial_sequence(?, 'id'),
                      COALESCE((SELECT MAX(id) FROM {table}), 1),
                      EXISTS(SELECT 1 FROM {table}))""",
                (table,),
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        source.close()

    app.logger.info('PostgreSQL study content is ready; missing rows added: %s', inserted_counts)


if USE_SQLITE:
    init_sqlite_db()
else:
    seed_postgres_content()
app.session_interface = DatabaseSessionInterface(app.config)

# Вспомогательные функции
def get_current_user():
    uid = session.get('user_id')
    if not uid: return None
    try:
        cur = get_cursor()
        cur.execute('SELECT id,name,email,xp,tests_completed,is_admin,avatar_color,avatar_image_mime FROM users WHERE id=%s AND disabled=0',(uid,))
        return cur.fetchone()
    except Exception:
        app.logger.exception('Cannot load current user')
        abort(503)

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not get_current_user():
            session.clear()
            if request.is_json:
                return jsonify({'error':'Войдите в аккаунт'}),401
            return redirect('/py/login')
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not get_current_user():
            session.clear()
            if request.is_json:
                return jsonify({'error':'Войдите в аккаунт'}),401
            return redirect('/py/login')
        user = get_current_user()
        if not user or not user.get('is_admin'):
            abort(403)
        return f(*args, **kwargs)
    return decorated

def add_to_mistake_bank(user_id, question_id, wrong_idx):
    cur = get_cursor()
    cur.execute('''INSERT INTO mistake_bank(user_id,question_id,wrong_answer_idx)
                   VALUES(%s,%s,%s)
                   ON CONFLICT(user_id,question_id) DO UPDATE SET
                   wrong_answer_idx=excluded.wrong_answer_idx,
                   review_count=mistake_bank.review_count+1,
                   next_review=CURRENT_TIMESTAMP''', (user_id,question_id,wrong_idx))

# Маршруты приложения
@app.route('/py/')
@app.route('/py')
def dashboard():
    if session.get('user_id') and not get_current_user():
        session.clear()
    if not session.get('user_id'):
        return render_template('landing.html')
    user = get_current_user()
    try:
        cur = get_cursor()
        cur.execute('SELECT subject,COUNT(*) as c FROM test_results WHERE user_id=%s GROUP BY subject',(user['id'],))
        stats = {r['subject']:r['c'] for r in cur.fetchall()}
        cur.execute('SELECT subject,AVG(score) as avg FROM test_results WHERE user_id=%s GROUP BY subject',(user['id'],))
        scores = {r['subject']:round(float(r['avg'])) if r['avg'] else 0 for r in cur.fetchall()}
        cur.execute('SELECT COUNT(*) as c FROM mistake_bank WHERE user_id=%s',(user['id'],))
        mistake_count = cur.fetchone()['c']
        cur.execute('SELECT subject,COUNT(*) as c FROM questions GROUP BY subject')
        question_counts={r['subject']:r['c'] for r in cur.fetchall()}
    except Exception:
        app.logger.exception('Cannot load dashboard')
        abort(503)
    return render_template('dashboard.html',user=user,subjects=SUBJECTS,stats=stats,scores=scores,
                           mistake_count=mistake_count,question_counts=question_counts)

@app.route('/py/login', methods=['GET','POST'])
def login():
    if session.get('user_id'): return redirect('/py/')
    error=None; tab=request.args.get('tab','login')
    if request.method == 'GET' and tab == 'register':
        return render_template('register.html', error=None)
    if request.method=='POST':
        action=request.form.get('action')
        if action=='login':
            email=request.form.get('email','').strip().lower(); pwd=request.form.get('password','')
            try:
                cur=get_cursor()
                cur.execute('SELECT id,name,email,password_hash FROM users WHERE lower(email)=%s AND disabled=0',(email,))
                u=cur.fetchone()
                if len(pwd.encode()) <= 72 and u and bcrypt.checkpw(pwd.encode(),u['password_hash'].encode()):
                    session.clear()
                    session['user_id']=u['id']
                    session.permanent=True
                    return redirect('/py/')
                else: error='Неверный email или пароль'; tab='login'
            except Exception:
                app.logger.exception('Login failed')
                error='Не удалось войти. Попробуйте позже.'; tab='login'
        elif action=='register':
            name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower()
            pwd=request.form.get('password',''); tab='register'
            if len(name)<2: error='Имя минимум 2 символа'
            elif len(name)>100: error='Имя максимум 100 символов'
            elif len(pwd)<6: error='Пароль минимум 6 символов'
            elif len(pwd.encode())>72: error='Пароль слишком длинный (максимум 72 байта)'
            elif len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email): error='Некорректный email'
            else:
                try:
                    db=get_db(); cur=get_cursor()
                    cur.execute('SELECT id FROM users WHERE lower(email)=%s',(email,))
                    if cur.fetchone(): error='Email уже используется'
                    else:
                        h=bcrypt.hashpw(pwd.encode(),bcrypt.gensalt()).decode()
                        cur.execute('INSERT INTO users(name,email,password_hash) VALUES(%s,%s,%s) RETURNING id',(name,email,h))
                        uid=cur.fetchone()['id']; db.commit()
                        session.clear()
                        session['user_id']=uid
                        session.permanent=True
                        return redirect('/py/')
                except Exception as e:
                    try: get_db().rollback()
                    except: pass
                    app.logger.exception('Registration failed')
                    error='Не удалось зарегистрироваться. Попробуйте позже.'
    if tab == 'register':
        return render_template('register.html', error=error)
    return render_template('login.html',error=error,tab=tab)

@app.route('/py/register')
def register_page():
    if session.get('user_id'): return redirect('/py/')
    return render_template('register.html', error=None)

@app.route('/py/logout', methods=['POST'])
def logout(): session.clear(); return redirect('/py/login')

@app.route('/py/subjects/<subject>')
@login_required
def subject_hub(subject):
    if subject not in SUBJECTS: return redirect('/py/')
    user=get_current_user()
    try:
        cur=get_cursor()
        cur.execute('SELECT COUNT(*) as c FROM questions WHERE subject=%s AND part=%s',(subject,'part1')); q1=cur.fetchone()['c']
        if subject == 'russian':
            cur.execute('SELECT COUNT(*) as c FROM essay_prompts')
        else:
            cur.execute(
                "SELECT COUNT(*) as c FROM questions WHERE subject=%s AND part=%s AND difficulty='part2_bank'",
                (subject,'part2')
            )
        q2=cur.fetchone()['c']
        cur.execute('SELECT AVG(score) as avg FROM test_results WHERE user_id=%s AND subject=%s',(user['id'],subject))
        r=cur.fetchone(); avg=round(float(r['avg'])) if r and r['avg'] else 0
        cur.execute(
            "SELECT DISTINCT task_number FROM questions WHERE subject=%s AND (part='part1' OR difficulty='part2_bank') ORDER BY task_number",
            (subject,)
        )
        task_numbers=[r['task_number'] for r in cur.fetchall()]
    except Exception:
        app.logger.exception('Cannot load subject')
        abort(503)
    return render_template('subject.html',user=user,subj=SUBJECTS[subject],subject=subject,q1_count=q1,q2_count=q2,avg_score=avg,task_numbers=task_numbers)

@app.route('/py/subjects/<subject>/theory')
@login_required
def theory(subject):
    if subject not in SUBJECTS: return redirect('/py/')
    user=get_current_user()
    try:
        cur=get_cursor()
        cur.execute(
            '''SELECT section.* FROM theory_sections section
               WHERE section.subject=%s
                 AND section.id=(
                     SELECT MAX(latest.id) FROM theory_sections latest
                     WHERE latest.subject=section.subject
                       AND latest.title=section.title
                       AND latest.order_index=section.order_index
                 )
               ORDER BY section.order_index,section.id''',
            (subject,)
        )
        sections=cur.fetchall()
    except Exception:
        app.logger.exception('Cannot load theory')
        abort(503)
    return render_template('theory.html',user=user,subj=SUBJECTS[subject],subject=subject,sections=sections)

@app.route('/py/subjects/<subject>/quiz')
@login_required
def quiz(subject):
    if subject not in SUBJECTS: return redirect('/py/')
    user=get_current_user()
    part=request.args.get('part','part1')
    if part not in ('part1','part2'): abort(400)
    if subject == 'russian' and part == 'part2':
        return redirect('/py/subjects/russian/essay?from=part2')
    try:
        cur=get_cursor()
        if part == 'part2':
            cur.execute(
                "SELECT * FROM questions WHERE subject=%s AND part=%s AND difficulty='part2_bank' ORDER BY RANDOM() LIMIT 10",
                (subject,part)
            )
        else:
            cur.execute(
                'SELECT * FROM questions WHERE subject=%s AND part=%s ORDER BY RANDOM() LIMIT 10',
                (subject,part)
            )
        questions=[]
        for q in cur.fetchall():
            qd=dict(q); qd['options_list']=json.loads(qd.get('options','[]'))
            try: qd['wrong_expl']=json.loads(qd.get('wrong_explanations') or '{}')
            except: qd['wrong_expl']={}
            questions.append(qd)
    except Exception:
        app.logger.exception('Cannot load quiz')
        abort(503)
    practice_id=start_practice(get_db(),user['id'],subject,'quiz',questions)
    return render_template('quiz.html',user=user,subj=SUBJECTS[subject],subject=subject,questions=public_questions(questions),part=part,mode='quiz',practice_id=practice_id)

@app.route('/py/subjects/<subject>/quiz/submit', methods=['POST'])
@login_required
def quiz_submit(subject):
    if subject not in SUBJECTS: abort(404)
    user=get_current_user()
    return jsonify(submit_practice(get_db(),user['id'],subject,request.get_json()))

# Режим экзамена
@app.route('/py/subjects/<subject>/exam')
@login_required
def exam_setup(subject):
    if subject not in SUBJECTS: return redirect('/py/')
    user=get_current_user()
    subj=SUBJECTS[subject]
    cur=get_cursor()
    cur.execute(
        "SELECT COUNT(*) as c FROM questions WHERE subject=%s AND (part='part1' OR difficulty='part2_bank')",
        (subject,)
    )
    question_count=cur.fetchone()['c']
    return render_template('exam_setup.html',user=user,subj=subj,subject=subject,question_count=question_count)

@app.route('/py/subjects/<subject>/exam/start')
@login_required
def exam_start(subject):
    if subject not in SUBJECTS: return redirect('/py/')
    user=get_current_user()
    try:
        cur=get_cursor(); db=get_db()
        cur.execute('''SELECT * FROM exam_sessions WHERE user_id=%s AND subject=%s
                       AND finished_at IS NULL ORDER BY id DESC LIMIT 1''',(user['id'],subject))
        active=cur.fetchone()
        if active:
            stored=json.loads(active.get('answers_json') or '{}')
            remaining=max(0,active['time_limit_min']*60-int((datetime.now()-parse_date(active['started_at'])).total_seconds()))
            if stored.get('question_ids'):
                ids=stored['question_ids']
                ph=','.join(['%s']*len(ids))
                cur.execute(f'SELECT * FROM questions WHERE id IN ({ph})',ids)
                found={q['id']:q for q in cur.fetchall()}
                questions=[dict(found[qid],options_list=json.loads(found[qid]['options'])) for qid in ids if qid in found]
                return render_template('exam.html',user=user,subj=SUBJECTS[subject],subject=subject,
                                       questions=public_questions(questions),time_min=active['time_limit_min'],
                                       sess_id=active['id'],remaining_sec=remaining)

        cur.execute(
            '''SELECT * FROM (
                   SELECT q.*,
                          ROW_NUMBER() OVER (
                              PARTITION BY q.task_number ORDER BY RANDOM()
                          ) AS _task_pick
                   FROM questions q
                   WHERE q.subject=%s AND (q.part='part1' OR q.difficulty='part2_bank')
               ) AS task_picks
               WHERE _task_pick=1 ORDER BY task_number''',
            (subject,)
        )
        questions=[]
        for q in cur.fetchall():
            qd=dict(q); qd['options_list']=json.loads(qd.get('options','[]'))
            questions.append(qd)
        if len(questions)<5:
            cur.execute('SELECT * FROM questions WHERE subject=%s ORDER BY RANDOM() LIMIT 15',(subject,))
            questions=[]
            for q in cur.fetchall():
                qd=dict(q); qd['options_list']=json.loads(qd.get('options','[]'))
                questions.append(qd)
        if not questions: abort(404,description='Для экзамена нет заданий')
        cur.execute('INSERT INTO exam_sessions(user_id,subject,mode,time_limit_min) VALUES(%s,%s,%s,%s) RETURNING id',
                   (user['id'],subject,'exam',EXAM_TIMES.get(subject,235)))
        sess_id=cur.fetchone()['id']
        cur.execute('UPDATE exam_sessions SET answers_json=%s WHERE id=%s',
                    (json.dumps({'question_ids':[q['id'] for q in questions]}),sess_id))
        db.commit()
        time_min=EXAM_TIMES.get(subject,235)
    except Exception:
        get_db().rollback()
        app.logger.exception('Cannot start exam')
        abort(503)
    return render_template('exam.html',user=user,subj=SUBJECTS[subject],subject=subject,
                          questions=public_questions(questions),time_min=time_min,sess_id=sess_id,remaining_sec=time_min*60)

@app.route('/py/subjects/<subject>/exam/submit', methods=['POST'])
@login_required
def exam_submit(subject):
    if subject not in SUBJECTS: abort(404)
    user=get_current_user()
    return jsonify(submit_exam(get_db(),user['id'],subject,request.get_json()))

# Режим тренировки
@app.route('/py/subjects/<subject>/drill')
@login_required
def drill_setup(subject):
    if subject not in SUBJECTS: return redirect('/py/')
    user=get_current_user()
    try:
        cur=get_cursor()
        cur.execute('SELECT DISTINCT task_number,section FROM questions WHERE subject=%s ORDER BY task_number,section',(subject,))
        sections_by_task={}
        for row in cur.fetchall():
            task_number=row['task_number']
            section=(row['section'] or '').strip()
            sections=sections_by_task.setdefault(task_number,[])
            if section and section not in sections:
                sections.append(section)
        task_rows=[
            {'task_number':task_number,'section':' · '.join(sections) or 'Темы не указаны'}
            for task_number,sections in sections_by_task.items()
        ]
    except Exception:
        app.logger.exception('Cannot load drill setup')
        abort(503)
    return render_template('drill_setup.html',user=user,subj=SUBJECTS[subject],subject=subject,task_rows=task_rows)

@app.route('/py/subjects/<subject>/drill/<int:task_num>')
@login_required
def drill(subject, task_num):
    if subject not in SUBJECTS: return redirect('/py/')
    user=get_current_user()
    try:
        cur=get_cursor()
        cur.execute('SELECT * FROM questions WHERE subject=%s AND task_number=%s ORDER BY RANDOM() LIMIT 20',(subject,task_num))
        questions=[]
        for q in cur.fetchall():
            qd=dict(q); qd['options_list']=json.loads(qd.get('options','[]'))
            try: qd['wrong_expl']=json.loads(qd.get('wrong_explanations') or '{}')
            except: qd['wrong_expl']={}
            questions.append(qd)
    except Exception:
        app.logger.exception('Cannot load drill')
        abort(503)
    practice_id=start_practice(get_db(),user['id'],subject,'drill',questions)
    return render_template('drill.html',user=user,subj=SUBJECTS[subject],subject=subject,
                          questions=public_questions(questions),task_num=task_num,practice_id=practice_id)

@app.route('/py/subjects/<subject>/drill/answer', methods=['POST'])
@login_required
def drill_answer(subject):
    if subject not in SUBJECTS: abort(404)
    return jsonify(submit_drill(get_db(),get_current_user()['id'],subject,request.get_json()))

# Адаптивный режим
@app.route('/py/subjects/<subject>/adaptive')
@login_required
def adaptive(subject):
    if subject not in SUBJECTS: return redirect('/py/')
    user=get_current_user()
    try:
        cur=get_cursor()

        cur.execute('''SELECT q.task_number, q.section,
                       SUM(CASE WHEN qa.is_correct=0 THEN 1 ELSE 0 END) as wrong,
                       COUNT(*) as total
                       FROM question_attempts qa
                       JOIN questions q ON q.id=qa.question_id
                       WHERE qa.user_id=%s AND q.subject=%s
                       GROUP BY q.task_number, q.section
                       HAVING SUM(CASE WHEN qa.is_correct=0 THEN 1 ELSE 0 END)>0
                       ORDER BY wrong DESC LIMIT 5''',(user['id'],subject))
        weak_tasks=cur.fetchall()
        if weak_tasks:
            task_nums=[w['task_number'] for w in weak_tasks]
            ph=','.join(['%s']*len(task_nums))
            cur.execute(f'SELECT * FROM questions WHERE subject=%s AND task_number IN ({ph}) ORDER BY RANDOM() LIMIT 15',
                       [subject]+task_nums)
        else:
            cur.execute('SELECT * FROM questions WHERE subject=%s ORDER BY RANDOM() LIMIT 15',(subject,))
        questions=[]
        for q in cur.fetchall():
            qd=dict(q); qd['options_list']=json.loads(qd.get('options','[]'))
            try: qd['wrong_expl']=json.loads(qd.get('wrong_explanations') or '{}')
            except: qd['wrong_expl']={}
            questions.append(qd)
    except Exception:
        app.logger.exception('Cannot load adaptive practice')
        abort(503)
    practice_id=start_practice(get_db(),user['id'],subject,'adaptive',questions)
    return render_template('adaptive.html',user=user,subj=SUBJECTS[subject],subject=subject,
                          questions=public_questions(questions),weak_tasks=weak_tasks,practice_id=practice_id)

# Банк ошибок
@app.route('/py/mistakes')
@login_required
def mistakes():
    user=get_current_user()
    try:
        cur=get_cursor()
        cur.execute('''SELECT mb.id, mb.wrong_answer_idx, mb.wrong_answer_text, mb.review_count, mb.next_review,
                       q.id as qid, q.subject, q.task_number, q.section, q.text, q.options,
                       q.correct_index, q.answer_type, q.correct_answer, q.explanation, q.wrong_explanations
                       FROM mistake_bank mb
                       JOIN questions q ON q.id=mb.question_id
                       WHERE mb.user_id=%s
                       ORDER BY mb.next_review ASC, q.subject''',(user['id'],))
        raw=cur.fetchall()
        mistakes_list=[]
        for m in raw:
            md=dict(m)
            md['options_list']=json.loads(md.get('options','[]'))
            try: md['wrong_expl']=json.loads(md.get('wrong_explanations') or '{}')
            except: md['wrong_expl']={}
            md['subj_title']=SUBJECTS.get(md['subject'],{}).get('title',md['subject'])
            mistakes_list.append(md)
    except Exception:
        app.logger.exception('Cannot load mistakes')
        abort(503)
    return render_template('mistakes.html',user=user,mistakes=mistakes_list,subjects=SUBJECTS)

@app.route('/py/api/remove-mistake/<int:mb_id>', methods=['POST'])
@login_required
def remove_mistake(mb_id):
    user=get_current_user()
    try:
        db=get_db(); cur=get_cursor()
        cur.execute('DELETE FROM mistake_bank WHERE id=%s AND user_id=%s',(mb_id,user['id']))
        db.commit()
        return jsonify({'ok':True})
    except Exception:
        get_db().rollback()
        app.logger.exception('Cannot remove mistake')
        abort(503)

# Работа с сочинениями
@app.route('/py/my-essays')
@login_required
def my_essays():
    user=get_current_user()
    if user and user.get('is_admin'): return redirect('/py/admin/essays')
    submissions=[]
    try:
        db=get_db(); cur=get_cursor()

        cur.execute('''SELECT es.id,es.subject,es.essay_type,es.essay_topic,
                              es.teacher_result,es.text,es.word_count,es.self_score,
                              es.checklist_json,es.teacher_score,es.teacher_comment,
                              es.teacher_criteria_json,es.teacher_graded_at,es.created_at,
                              es.resubmit_count,ep.title AS prompt_title,
                              ep.source_text AS prompt_source_text
                       FROM essay_submissions es
                       LEFT JOIN essay_prompts ep ON ep.id=es.essay_prompt_id
                       WHERE es.user_id=%s
                       ORDER BY es.created_at DESC''',(user['id'],))
        raw=cur.fetchall()
        for s in raw:
            sd=dict(s)
            sd['is_graded'] = (
                sd.get('teacher_result') is not None
                if sd.get('essay_type') == 'final'
                else sd.get('teacher_score') is not None
            )
            try: sd['checklist_dict']=json.loads(sd.get('checklist_json') or '{}')
            except: sd['checklist_dict']={}
            try: sd['teacher_criteria']=json.loads(sd.get('teacher_criteria_json') or '{}')
            except: sd['teacher_criteria']={}
            submissions.append(sd)
    except Exception:
        app.logger.exception('Cannot load essays')
        abort(503)
    return render_template('my_essays.html',user=user,submissions=submissions,subjects=SUBJECTS,
                           checklist_labels=CHECKLIST_RUSSIAN)

@app.route('/py/subjects/<subject>/essay')
@login_required
def essay(subject):
    if subject not in SUBJECTS: return redirect('/py/')
    user=get_current_user()
    if user and user.get('is_admin'): return redirect('/py/admin/essays')
    submissions=[]
    essay_prompts=[]
    selected_prompt=None
    try:
        db=get_db(); cur=get_cursor()
        cur.execute('''SELECT es.id,es.word_count,es.self_score,es.teacher_score,es.teacher_comment,
                              es.teacher_graded_at,es.created_at,es.resubmit_count,
                              ep.title AS prompt_title
                       FROM essay_submissions es
                       LEFT JOIN essay_prompts ep ON ep.id=es.essay_prompt_id
                       WHERE es.user_id=%s AND es.subject=%s AND es.essay_type='ege'
                       ORDER BY es.created_at DESC LIMIT 5''',(user['id'],subject))
        submissions=[dict(s) for s in cur.fetchall()]
        if subject == 'russian':
            cur.execute('SELECT id,title,source_text,problem FROM essay_prompts ORDER BY id')
            essay_prompts=[dict(row) for row in cur.fetchall()]
            requested_id=request.args.get('task', type=int)
            if requested_id is not None:
                selected_prompt=next((row for row in essay_prompts if row['id']==requested_id),None)
                if selected_prompt is None:
                    abort(404,description='Тренировочный текст не найден')
            elif essay_prompts:
                selected_prompt=essay_prompts[0]
    except Exception:
        app.logger.exception('Cannot load essay history')
        abort(503)
    checklist=CHECKLIST_RUSSIAN if subject=='russian' else []
    return render_template('essay.html',user=user,subj=SUBJECTS[subject],subject=subject,
                          submissions=submissions,checklist=checklist,
                          essay_prompts=essay_prompts,selected_prompt=selected_prompt)

@app.route('/py/subjects/russian/final-essay')
@login_required
def russian_final_essay():
    user=get_current_user()
    if user and user.get('is_admin'): return redirect('/py/admin/essays')
    return render_template(
        'final_essay.html',
        user=user,
        subj=SUBJECTS['russian'],
        topics=DECEMBER_ESSAY_TOPICS,
        checklist_labels=FINAL_ESSAY_CHECKS,
    )

@app.route('/py/subjects/russian/final-essay/submit', methods=['POST'])
@login_required
def russian_final_essay_submit():
    user=get_current_user()
    if user and user.get('is_admin'):
        return jsonify({'ok':False,'error':'Администратор не может отправлять сочинения'}),403
    data=request.get_json(silent=True)
    if not isinstance(data,dict):
        return jsonify({'ok':False,'error':'Не удалось прочитать данные сочинения'}),400
    text=data.get('text')
    topic=data.get('topic')
    if not isinstance(text,str) or not text.strip() or len(text.strip())>30000:
        return jsonify({'ok':False,'error':'Текст должен содержать от 1 до 30 000 символов'}),400
    if topic not in DECEMBER_ESSAY_TOPICS:
        return jsonify({'ok':False,'error':'Выберите тему итогового сочинения'}),400
    checklist=data.get('checklist',{})
    if not isinstance(checklist,dict) or set(checklist)-set(FINAL_ESSAY_CHECKS):
        return jsonify({'ok':False,'error':'Некорректные ответы самопроверки'}),400
    if any(not isinstance(value,bool) for value in checklist.values()):
        return jsonify({'ok':False,'error':'Некорректные ответы самопроверки'}),400
    checklist={key:bool(checklist.get(key,False)) for key in FINAL_ESSAY_CHECKS}
    text=text.strip()
    word_count=len(text.split())
    try:
        cur=get_cursor()
        cur.execute(
            '''INSERT INTO essay_submissions(
                   user_id,subject,essay_type,essay_topic,text,word_count,
                   checklist_json,self_score
               ) VALUES(%s,'russian','final',%s,%s,%s,%s,%s)''',
            (
                user['id'],topic,text,word_count,json.dumps(checklist),
                sum(checklist.values()),
            ),
        )
        get_db().commit()
        return jsonify({'ok':True,'word_count':word_count})
    except Exception:
        get_db().rollback()
        app.logger.exception('Cannot save final essay')
        return jsonify({'ok':False,'error':'Не удалось сохранить сочинение. Попробуйте ещё раз.'}),503

@app.route('/py/subjects/<subject>/essay/submit', methods=['POST'])
@login_required
def essay_submit(subject):
    if subject not in SUBJECTS: abort(404)
    user=get_current_user()
    if user and user.get('is_admin'): return jsonify({'error':'Администратор не может отправлять сочинения'}),403
    data=request.get_json()
    text,checklist,self_score=validate_essay(data,subject)
    word_count=len(text.split()) if text.strip() else 0
    try:
        db=get_db(); cur=get_cursor()
        prompt_id=None
        raw_prompt_id=data.get('prompt_id') if isinstance(data,dict) else None
        if raw_prompt_id not in (None,''):
            try:
                prompt_id=int(raw_prompt_id)
            except (TypeError,ValueError):
                abort(400,description='Некорректный номер тренировочного текста')
            if subject!='russian' or prompt_id<1:
                abort(400,description='Тренировочный текст недоступен')
            cur.execute('SELECT id FROM essay_prompts WHERE id=%s',(prompt_id,))
            if not cur.fetchone():
                abort(400,description='Тренировочный текст не найден')
        cur.execute(
            'INSERT INTO essay_submissions(user_id,subject,essay_type,essay_prompt_id,text,word_count,checklist_json,self_score) VALUES(%s,%s,\'ege\',%s,%s,%s,%s,%s)',
            (user['id'],subject,prompt_id,text,word_count,json.dumps(checklist),self_score)
        )
        db.commit()
        return jsonify({'ok':True,'word_count':word_count,'self_score':self_score})
    except Exception:
        get_db().rollback()
        app.logger.exception('Cannot save essay')
        abort(503)

def validate_essay(data,subject):
    from assessment import integer
    if not isinstance(data,dict) or not isinstance(data.get('text'),str):
        abort(400,description='Некорректный текст')
    text=data['text'].strip()
    if not text or len(text)>50000:
        abort(400,description='Текст должен содержать от 1 до 50 000 символов')
    checklist=data.get('checklist',{})
    if not isinstance(checklist,dict): abort(400,description='Некорректные критерии')
    caps={key:cap for key,title,description,cap in CHECKLIST_RUSSIAN} if subject=='russian' else {}
    if set(checklist)-set(caps): abort(400,description='Неизвестный критерий')
    values={key:integer(value,0,caps[key]) for key,value in checklist.items()}
    if subject=='russian':
        if not values.get('К1',0):
            values['К2']=0
            values['К3']=0
        if len(text.split())<150:
            values={key:0 for key in values}
    return text,values,sum(values.values())

@app.route('/py/essay/<int:essay_id>/resubmit', methods=['POST'])
@login_required
def essay_resubmit(essay_id):
    user=get_current_user()
    if user and user.get('is_admin'): return jsonify({'error':'Администратор не может отправлять сочинения'}),403
    data=request.get_json()
    if not data: return jsonify({'error':'Нет данных'}),400
    try:
        db=get_db(); cur=get_cursor()
        cur.execute('SELECT subject,essay_type FROM essay_submissions WHERE id=%s AND user_id=%s',(essay_id,user['id']))
        row=cur.fetchone()
        if not row: abort(404,description='Сочинение не найдено')
        if row['essay_type']=='final':
            return jsonify({'error':'Итоговое декабрьское сочинение нельзя отправить через форму сочинения ЕГЭ'}),400
        text,checklist,self_score=validate_essay(data,row['subject'])
        word_count=len(text.split())


        cur.execute('''UPDATE essay_submissions
                       SET text=%s, word_count=%s, checklist_json=%s, self_score=%s,
                            teacher_score=NULL, teacher_result=NULL, teacher_comment=NULL,
                           teacher_criteria_json=NULL, teacher_graded_at=NULL,
                           resubmit_count=resubmit_count+1,
                           created_at=%s
                       WHERE id=%s
                         AND user_id=%s
                         AND teacher_score IS NOT NULL
                         AND resubmit_count=0''',
                   (text,word_count,json.dumps(checklist),self_score,
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),essay_id,user['id']))
        if cur.rowcount==0:
            db.rollback() if hasattr(db,'rollback') else None

            cur.execute('SELECT user_id,teacher_score,resubmit_count FROM essay_submissions WHERE id=%s',(essay_id,))
            row=cur.fetchone()
            if not row: return jsonify({'error':'Сочинение не найдено'}),404
            row=dict(row)
            if row.get('user_id')!=user['id']: return jsonify({'error':'Нет доступа'}),403
            if row.get('teacher_score') is None: return jsonify({'error':'Сочинение ещё не проверено'}),400
            return jsonify({'error':'Повторная отправка уже использована'}),400
        db.commit()
        return jsonify({'ok':True})
    except Exception as e:
        from werkzeug.exceptions import HTTPException
        if isinstance(e,HTTPException): raise
        get_db().rollback()
        app.logger.exception('Cannot resubmit essay')
        abort(503)


@app.route('/py/arguments')
@login_required
def arguments():
    user=get_current_user()
    return render_template(
        'arguments.html',
        user=user,
        cliche_sections=CATEGORIES,
        rubric=RUBRIC,
        books=BOOKS,
        problems=PROBLEMS,
        math_reference=MATH_REFERENCE,
    )

# Аналитика
@app.route('/py/analytics')
@login_required
def analytics():
    user=get_current_user()
    try:
        cur=get_cursor()
        cur.execute('SELECT subject,score,mode,created_at FROM test_results WHERE user_id=%s ORDER BY created_at DESC LIMIT 30',(user['id'],))
        results=[dict(r) for r in cur.fetchall()]
        cur.execute('''SELECT q.task_number, q.section, q.subject,
                       AVG(CASE WHEN qa.is_correct=1 THEN 100.0 ELSE 0 END) as acc,
                       COUNT(*) as attempts
                       FROM question_attempts qa JOIN questions q ON q.id=qa.question_id
                       WHERE qa.user_id=%s GROUP BY q.subject,q.task_number,q.section
                       ORDER BY acc ASC''',(user['id'],))
        task_stats=[dict(r) for r in cur.fetchall()]
        cur.execute('''SELECT q.subject, AVG(qa.time_sec) as avg_time
                       FROM question_attempts qa JOIN questions q ON q.id=qa.question_id
                       WHERE qa.user_id=%s GROUP BY q.subject''',(user['id'],))
        time_stats={r['subject']:round(float(r['avg_time'])) if r['avg_time'] else 0 for r in cur.fetchall()}
        cur.execute('SELECT COUNT(*) as c FROM mistake_bank WHERE user_id=%s',(user['id'],)); mc=cur.fetchone()['c']
    except Exception:
        app.logger.exception('Cannot load analytics')
        abort(503)
    return render_template('analytics.html',user=user,results=results,task_stats=task_stats,
                          time_stats=time_stats,mistake_count=mc,subjects=SUBJECTS)

@app.route('/py/api/analytics-data')
@login_required
def analytics_data():
    user=get_current_user()
    try:
        cur=get_cursor()
        cur.execute('SELECT subject,score,created_at FROM test_results WHERE user_id=%s ORDER BY created_at DESC LIMIT 20',(user['id'],))
        results=[dict(r) for r in cur.fetchall()]
        return jsonify({'results':results})
    except Exception:
        app.logger.exception('Cannot load analytics data')
        abort(503)

# Разбор заданий
@app.route('/py/subjects/<subject>/analyses')
@login_required
def analyses(subject):
    if subject not in SUBJECTS: return redirect('/py/')
    user=get_current_user()
    try:
        cur=get_cursor()
        cur.execute(
            '''SELECT analysis.* FROM task_analyses analysis
               WHERE analysis.subject=%s
                 AND analysis.id=(
                     SELECT MAX(latest.id) FROM task_analyses latest
                     WHERE latest.subject=analysis.subject
                       AND latest.task_number=analysis.task_number
                       AND latest.title=analysis.title
                 )
               ORDER BY analysis.task_number,analysis.id''',
            (subject,)
        )
        items=cur.fetchall()
    except Exception:
        app.logger.exception('Cannot load analyses')
        abort(503)
    return render_template('analyses.html',user=user,subj=SUBJECTS[subject],subject=subject,items=items)

@app.route('/py/subjects/<subject>/guides')
@login_required
def guides(subject):
    if subject not in SUBJECTS: return redirect('/py/')
    user=get_current_user()
    try:
        cur=get_cursor()
        cur.execute(
            '''SELECT guide.* FROM guides guide
               WHERE guide.subject=%s
                 AND guide.id=(
                     SELECT MAX(latest.id) FROM guides latest
                     WHERE latest.subject=guide.subject
                       AND latest.category=guide.category
                       AND latest.title=guide.title
                 )
               ORDER BY guide.category,guide.id''',
            (subject,)
        )
        grouped=OrderedDict()
        for item in cur.fetchall():
            cat=item.get('category') or 'Общее'
            if cat not in grouped: grouped[cat]=[]
            grouped[cat].append(dict(item))
    except Exception:
        app.logger.exception('Cannot load guides')
        abort(503)
    return render_template('guides.html',user=user,subj=SUBJECTS[subject],subject=subject,grouped=grouped)

@app.route('/py/news')
@login_required
def news():
    user=get_current_user()
    try:
        cur=get_cursor()
        cur.execute('SELECT * FROM news_items ORDER BY year DESC,id DESC')
        items=cur.fetchall()
        cur.execute(
            'SELECT * FROM news_suggestions WHERE user_id=%s ORDER BY id DESC LIMIT 20',
            (user['id'],),
        )
        suggestions=cur.fetchall()
    except Exception:
        app.logger.exception('Cannot load news')
        abort(503)
    return render_template(
        'news.html',
        user=user,
        items=items,
        suggestions=suggestions,
        news_subject_labels=NEWS_SUBJECT_LABELS,
        current_year=datetime.now().year,
        news_suggestion_notice=session.pop('news_suggestion_notice', None),
        news_suggestion_error=session.pop('news_suggestion_error', None),
    )

@app.route('/py/news/suggest', methods=['POST'])
@login_required
def news_suggest():
    user=get_current_user()
    title=request.form.get('title','').strip()
    content=request.form.get('content','').strip()
    subject=request.form.get('subject','').strip()
    year_raw=request.form.get('year',str(datetime.now().year)).strip()
    from assessment import integer

    if not title or not content:
        session['news_suggestion_error']='Заполните заголовок и текст новости.'
        return redirect('/py/news#suggest-news')
    if len(title)>200 or len(content)>5000:
        session['news_suggestion_error']='Заголовок должен быть до 200 символов, текст — до 5000.'
        return redirect('/py/news#suggest-news')
    if subject and subject not in NEWS_SUBJECT_LABELS:
        session['news_suggestion_error']='Выберите предмет из списка.'
        return redirect('/py/news#suggest-news')
    try:
        year=integer(year_raw,2000,2100)
    except ValueError:
        session['news_suggestion_error']='Укажите корректный год от 2000 до 2100.'
        return redirect('/py/news#suggest-news')

    try:
        db=get_db()
        cur=get_cursor()
        cur.execute(
            "SELECT COUNT(*) AS c FROM news_suggestions WHERE user_id=%s AND status='pending'",
            (user['id'],),
        )
        if cur.fetchone()['c']>=5:
            session['news_suggestion_error']='У вас уже есть 5 предложений на рассмотрении.'
            return redirect('/py/news#suggest-news')
        cur.execute(
            'INSERT INTO news_suggestions(user_id,title,content,subject,year) VALUES(%s,%s,%s,%s,%s)',
            (user['id'],title,content,subject,year),
        )
        db.commit()
        session['news_suggestion_notice']='Предложение отправлено администратору на рассмотрение.'
    except Exception:
        get_db().rollback()
        app.logger.exception('Cannot save news suggestion')
        abort(503)
    return redirect('/py/news#suggest-news')

@app.route('/py/support')
@login_required
def support():
    user=get_current_user()
    try:
        cur=get_cursor()
        cur.execute(
            'SELECT * FROM support_tickets WHERE user_id=%s ORDER BY id DESC',
            (user['id'],),
        )
        tickets=cur.fetchall()
    except Exception:
        app.logger.exception('Cannot load support tickets')
        abort(503)
    return render_template(
        'support.html',
        user=user,
        tickets=tickets,
        support_notice=session.pop('support_notice', None),
        support_error=session.pop('support_error', None),
    )

@app.route('/py/support/ask', methods=['POST'])
@login_required
def support_ask():
    user=get_current_user()
    subject=request.form.get('subject','').strip()
    question=request.form.get('question','').strip()
    if not subject or not question:
        session['support_error']='Укажите тему и текст вопроса.'
        return redirect('/py/support')
    if len(subject)>120 or len(question)>5000:
        session['support_error']='Тема должна быть до 120 символов, вопрос — до 5000.'
        return redirect('/py/support')
    try:
        db=get_db()
        cur=get_cursor()
        cur.execute(
            "SELECT COUNT(*) AS c FROM support_tickets WHERE user_id=%s AND status='open'",
            (user['id'],),
        )
        if cur.fetchone()['c']>=5:
            session['support_error']='У вас уже есть 5 вопросов, ожидающих ответа.'
            return redirect('/py/support')
        cur.execute(
            'INSERT INTO support_tickets(user_id,subject,question) VALUES(%s,%s,%s)',
            (user['id'],subject,question),
        )
        db.commit()
        session['support_notice']='Вопрос отправлен администратору.'
    except Exception:
        get_db().rollback()
        app.logger.exception('Cannot create support ticket')
        abort(503)
    return redirect('/py/support')

@app.route('/py/avatar/<int:user_id>')
@login_required
def serve_avatar(user_id):
    try:
        cur=get_cursor()
        cur.execute(
            'SELECT avatar_image,avatar_image_mime FROM users WHERE id=%s AND disabled=0',
            (user_id,),
        )
        row=cur.fetchone()
    except Exception:
        app.logger.exception('Cannot load avatar image')
        abort(503)
    if not row or not row['avatar_image'] or row['avatar_image_mime'] not in ('image/jpeg','image/png','image/webp'):
        abort(404)
    response=send_file(BytesIO(row['avatar_image']),mimetype=row['avatar_image_mime'],max_age=0)
    response.headers['Cache-Control']='private, no-store, max-age=0'
    response.headers['X-Content-Type-Options']='nosniff'
    return response

@app.route('/py/profile', methods=['GET','POST'])
@login_required
def profile():
    user=get_current_user()
    if request.method == 'POST':
        uploaded=request.files.get('avatar_image')
        try:
            if request.form.get('remove_avatar'):
                cur=get_cursor()
                cur.execute(
                    "UPDATE users SET avatar_image=NULL,avatar_image_mime='' WHERE id=%s",
                    (user['id'],),
                )
                get_db().commit()
                session['profile_notice']='Фото удалено. Теперь отображается первая буква имени.'
            elif uploaded and uploaded.filename:
                image_bytes=uploaded.stream.read(MAX_AVATAR_BYTES+1)
                if not image_bytes:
                    session['profile_error']='Выберите файл с фотографией.'
                elif len(image_bytes)>MAX_AVATAR_BYTES:
                    session['profile_error']='Фото слишком большое. Максимальный размер — 768 КБ.'
                else:
                    mime_type=detect_avatar_mime(image_bytes)
                    if mime_type is None:
                        session['profile_error']='Поддерживаются изображения JPEG, PNG и WebP.'
                    else:
                        cur=get_cursor()
                        cur.execute(
                            'UPDATE users SET avatar_image=%s,avatar_image_mime=%s WHERE id=%s',
                            (image_bytes,mime_type,user['id']),
                        )
                        get_db().commit()
                        session['profile_notice']='Фото аватара загружено.'
            else:
                session['profile_error']='Сначала выберите фотографию, затем нажмите «Сохранить фото».'
        except Exception:
            get_db().rollback()
            app.logger.exception('Cannot save profile avatar')
            abort(503)
        return redirect('/py/profile')

    try:
        cur=get_cursor()
        cur.execute('SELECT subject,score,questions_count,mode,created_at FROM test_results WHERE user_id=%s ORDER BY created_at DESC LIMIT 20',(user['id'],))
        raw=cur.fetchall()
        history=[{**dict(h),'created_at':parse_date(h['created_at'])} for h in raw]
        cur.execute('SELECT subject,AVG(score) as avg,COUNT(*) as cnt FROM test_results WHERE user_id=%s GROUP BY subject',(user['id'],))
        by_subject=[dict(row) for row in cur.fetchall()]
        results_by_subject={row['subject']:row for row in by_subject}
        subject_performance=[]
        for subject_id, subject_info in SUBJECTS.items():
            result=results_by_subject.get(subject_id)
            count=int(result['cnt']) if result else 0
            average=round(float(result['avg'])) if result and result['avg'] is not None else None
            subject_performance.append({
                'id':subject_id,
                'title':subject_info['title'].split('(')[0].strip(),
                'avg':average,
                'cnt':count,
            })
        attempted=sorted(
            (item for item in subject_performance if item['cnt'] > 0),
            key=lambda item: item['avg'],
            reverse=True,
        )
    except Exception:
        app.logger.exception('Cannot load profile')
        abort(503)
    return render_template(
        'profile.html',
        user=user,
        history=history,
        subject_performance=subject_performance,
        strongest_subject=attempted[0] if attempted else None,
        weakest_subject=attempted[-1] if len(attempted) > 1 else None,
        profile_notice=session.pop('profile_notice', None),
        profile_error=session.pop('profile_error', None),
        subjects=SUBJECTS,
    )

@app.route('/py/leaderboard')
@login_required
def leaderboard():
    user=get_current_user()
    try:
        cur=get_cursor()
        cur.execute(
            'SELECT id,name,xp,tests_completed,avatar_color,avatar_image_mime '
            'FROM users WHERE is_admin=0 ORDER BY xp DESC LIMIT 20'
        )
        leaders = []
        for row in cur.fetchall():
            leader = dict(row)
            name = str(leader.get('name') or '').strip()
            leader['avatar_initial'] = name[:1].upper() if name else 'У'
            leader['avatar_color'] = (
                leader.get('avatar_color')
                if leader.get('avatar_color') in AVATAR_COLORS
                else AVATAR_COLORS[0]
            )
            leaders.append(leader)
    except Exception:
        app.logger.exception('Cannot load leaderboard')
        abort(503)
    return render_template('leaderboard.html',user=user,leaders=leaders)

# Панель администратора
@app.route('/py/admin')
@admin_required
def admin_dashboard():
    user = get_current_user()
    try:
        cur = get_cursor()
        cur.execute('SELECT COUNT(*) as c FROM users WHERE is_admin=0')
        total_users = cur.fetchone()['c']
        cur.execute('''SELECT COUNT(*) as c FROM essay_submissions
                       WHERE (essay_type='final' AND teacher_result IS NULL)
                          OR (essay_type!='final' AND teacher_score IS NULL)''')
        ungraded = cur.fetchone()['c']
        cur.execute('''SELECT COUNT(*) as c FROM essay_submissions
                       WHERE (essay_type='final' AND teacher_result IS NOT NULL)
                          OR (essay_type!='final' AND teacher_score IS NOT NULL)''')
        graded = cur.fetchone()['c']
        cur.execute('SELECT COUNT(*) as c FROM news_items')
        news_count = cur.fetchone()['c']
        cur.execute("SELECT COUNT(*) as c FROM news_suggestions WHERE status='pending'")
        pending_news_suggestions = cur.fetchone()['c']
        cur.execute("SELECT COUNT(*) as c FROM support_tickets WHERE status='open'")
        open_support_tickets = cur.fetchone()['c']
    except Exception:
        app.logger.exception('Cannot load admin dashboard')
        abort(503)
    return render_template('admin_dashboard.html', user=user,
                           total_users=total_users, ungraded=ungraded,
                           graded=graded, news_count=news_count,
                           pending_news_suggestions=pending_news_suggestions,
                           open_support_tickets=open_support_tickets)

@app.route('/py/admin/support')
@admin_required
def admin_support():
    user=get_current_user()
    try:
        cur=get_cursor()
        cur.execute('''
            SELECT st.*,u.name AS user_name,u.email AS user_email
            FROM support_tickets st
            JOIN users u ON u.id=st.user_id
            ORDER BY CASE WHEN st.status='open' THEN 0 ELSE 1 END,
                     st.updated_at DESC,st.id DESC
        ''')
        tickets=cur.fetchall()
    except Exception:
        app.logger.exception('Cannot load admin support inbox')
        abort(503)
    return render_template(
        'admin_support.html',
        user=user,
        tickets=tickets,
        message=session.pop('support_admin_notice', None),
        error=session.pop('support_admin_error', None),
    )

@app.route('/py/admin/support/<int:ticket_id>/reply', methods=['POST'])
@admin_required
def admin_support_reply(ticket_id):
    admin=get_current_user()
    reply=request.form.get('reply','').strip()
    if not reply or len(reply)>5000:
        session['support_admin_error']='Введите ответ длиной до 5000 символов.'
        return redirect('/py/admin/support')
    try:
        db=get_db()
        cur=get_cursor()
        cur.execute(
            'SELECT id FROM support_tickets WHERE id=%s',
            (ticket_id,),
        )
        if not cur.fetchone():
            abort(404,description='Вопрос не найден')
        now=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cur.execute('''
            UPDATE support_tickets
            SET admin_reply=%s,status='answered',updated_at=%s,
                replied_at=%s,replied_by=%s
            WHERE id=%s
        ''',(reply,now,now,admin['id'],ticket_id))
        db.commit()
        session['support_admin_notice']='Ответ сохранён.'
    except Exception as error:
        from werkzeug.exceptions import HTTPException
        if isinstance(error,HTTPException):
            raise
        get_db().rollback()
        app.logger.exception('Cannot reply to support ticket')
        abort(503)
    return redirect('/py/admin/support')

@app.route('/py/admin/essays')
@admin_required
def admin_essays():
    user = get_current_user()
    try:
        cur = get_cursor()
        cur.execute('''
            SELECT es.id, es.subject, es.essay_type, es.essay_topic,
                   es.text, es.word_count, es.self_score,
                   es.checklist_json, es.teacher_score, es.teacher_result, es.teacher_comment,
                   es.teacher_criteria_json, es.teacher_graded_at, es.created_at,
                   es.resubmit_count,
                   u.name as user_name, u.email as user_email
            FROM essay_submissions es
            JOIN users u ON u.id = es.user_id
            ORDER BY CASE
                       WHEN (es.essay_type='final' AND es.teacher_result IS NOT NULL)
                         OR (es.essay_type!='final' AND es.teacher_score IS NOT NULL)
                       THEN 1 ELSE 0
                     END, es.created_at DESC
        ''')
        raw = cur.fetchall()
        essays = []
        for e in raw:
            ed = dict(e)
            ed['is_graded'] = (
                ed.get('teacher_result') is not None
                if ed.get('essay_type') == 'final'
                else ed.get('teacher_score') is not None
            )
            try: ed['checklist_dict'] = json.loads(ed.get('checklist_json') or '{}')
            except: ed['checklist_dict'] = {}
            try: ed['teacher_criteria'] = json.loads(ed.get('teacher_criteria_json') or '{}')
            except: ed['teacher_criteria'] = {}
            essays.append(ed)
    except Exception:
        app.logger.exception('Cannot load admin essays')
        abort(503)
    return render_template(
        'admin_essays.html',
        user=user,
        essays=essays,
        final_essay_checks=FINAL_ESSAY_CHECKS,
    )

@app.route('/py/admin/essays/<int:essay_id>/grade', methods=['POST'])
@admin_required
def admin_grade_essay(essay_id):
    try:
        comment = request.form.get('teacher_comment','').strip()
        if len(comment)>10000: abort(400,description='Комментарий слишком длинный')
        db = get_db(); cur = get_cursor()
        cur.execute('SELECT subject,word_count,essay_type FROM essay_submissions WHERE id=%s',(essay_id,))
        essay=cur.fetchone()
        if not essay: abort(404,description='Сочинение не найдено')
        graded_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if essay['essay_type']=='final':
            teacher_result=request.form.get('teacher_result','')
            if teacher_result not in ('pass','fail'):
                abort(400,description='Выберите результат: зачёт или незачёт')
            cur.execute('''UPDATE essay_submissions
                           SET teacher_score=NULL, teacher_result=%s, teacher_comment=%s,
                               teacher_criteria_json=%s, teacher_graded_at=%s
                           WHERE id=%s''',
                        (teacher_result,comment,json.dumps({}),graded_at,essay_id))
        else:
            score_raw = request.form.get('teacher_score','')
            from assessment import integer
            teacher_score = integer(score_raw.strip(),0,22)
            CRIT_MAX = {key:cap for key,title,description,cap in CHECKLIST_RUSSIAN}
            criteria = {}
            for key, cap in CRIT_MAX.items():
                val = request.form.get(f'crit_{key}','').strip()
                if val: criteria[key] = integer(val,0,cap)
            if len(criteria)==len(CRIT_MAX) and sum(criteria.values())!=teacher_score:
                abort(400,description='Итоговый балл должен совпадать с суммой критериев')
            if essay['subject']=='russian' and essay['word_count']<150 and teacher_score:
                abort(400,description='Работа короче 150 слов оценивается нулём баллов')
            if criteria.get('К1')==0 and (criteria.get('К2',0) or criteria.get('К3',0)):
                abort(400,description='При К1=0 критерии К2 и К3 также должны быть нулевыми')
            cur.execute('''UPDATE essay_submissions
                           SET teacher_score=%s, teacher_result=NULL, teacher_comment=%s,
                               teacher_criteria_json=%s, teacher_graded_at=%s
                           WHERE id=%s''',
                        (teacher_score,comment,json.dumps(criteria),graded_at,essay_id))
        if not cur.rowcount: abort(404,description='Сочинение не найдено')
        db.commit()
    except Exception as e:
        from werkzeug.exceptions import HTTPException
        if isinstance(e,HTTPException): raise
        get_db().rollback()
        app.logger.exception('Cannot grade essay')
        abort(503)
    return redirect('/py/admin/essays')

@app.route('/py/admin/news')
@admin_required
def admin_news():
    user = get_current_user()
    msg = request.args.get('msg')
    msg_type = request.args.get('t','success')
    try:
        cur = get_cursor()
        cur.execute('SELECT * FROM news_items ORDER BY year DESC, id DESC')
        items = cur.fetchall()
        cur.execute('''
            SELECT ns.*,u.name AS user_name,u.email AS user_email
            FROM news_suggestions ns
            JOIN users u ON u.id=ns.user_id
            WHERE ns.status='pending'
            ORDER BY ns.id ASC
        ''')
        suggestions = cur.fetchall()
    except Exception:
        app.logger.exception('Cannot load admin news')
        abort(503)
    return render_template('admin_news.html', user=user, items=items,
                           suggestions=suggestions,
                           news_subject_labels=NEWS_SUBJECT_LABELS,
                           message=msg, message_type=msg_type)

@app.route('/py/admin/news/add', methods=['POST'])
@admin_required
def admin_news_add():
    title = request.form.get('title','').strip()
    content = request.form.get('content','').strip()
    subject = request.form.get('subject','').strip()
    year_raw = request.form.get('year','2026')
    from assessment import integer
    year=integer(year_raw,2000,2100)
    if subject and subject not in NEWS_SUBJECT_LABELS: abort(400,description='Неизвестный предмет')
    if len(title)>250 or len(content)>50000: abort(400,description='Новость слишком длинная')
    if not title or not content:
        return redirect('/py/admin/news?msg=Заполните+заголовок+и+текст&t=error')
    try:
        db = get_db(); cur = get_cursor()
        cur.execute('INSERT INTO news_items(title,content,year,subject) VALUES(%s,%s,%s,%s)',
                   (title, content, year, subject))
        db.commit()
    except Exception as e:
        app.logger.exception('Cannot add news')
        get_db().rollback()
        abort(503)
    return redirect('/py/admin/news?msg=Новость+опубликована&t=success')

@app.route('/py/admin/news/suggestions/<int:suggestion_id>/publish', methods=['POST'])
@admin_required
def admin_publish_news_suggestion(suggestion_id):
    admin=get_current_user()
    try:
        db=get_db()
        cur=get_cursor()
        cur.execute('SELECT * FROM news_suggestions WHERE id=%s',(suggestion_id,))
        suggestion=cur.fetchone()
        if not suggestion:
            abort(404,description='Предложение не найдено')
        if suggestion['status']!='pending':
            return redirect('/py/admin/news?msg=Предложение+уже+рассмотрено&t=error')
        cur.execute(
            "UPDATE news_suggestions SET status='published',reviewed_at=%s,reviewed_by=%s "
            "WHERE id=%s AND status='pending'",
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),admin['id'],suggestion_id),
        )
        if not cur.rowcount:
            db.rollback()
            return redirect('/py/admin/news?msg=Предложение+уже+рассмотрено&t=error')
        cur.execute(
            'INSERT INTO news_items(title,content,year,subject) VALUES(%s,%s,%s,%s)',
            (suggestion['title'],suggestion['content'],suggestion['year'],suggestion['subject']),
        )
        db.commit()
    except Exception as error:
        from werkzeug.exceptions import HTTPException
        if isinstance(error,HTTPException):
            raise
        get_db().rollback()
        app.logger.exception('Cannot publish news suggestion')
        abort(503)
    return redirect('/py/admin/news?msg=Предложение+опубликовано&t=success')

@app.route('/py/admin/news/suggestions/<int:suggestion_id>/reject', methods=['POST'])
@admin_required
def admin_reject_news_suggestion(suggestion_id):
    admin=get_current_user()
    try:
        db=get_db()
        cur=get_cursor()
        cur.execute(
            "UPDATE news_suggestions SET status='rejected',reviewed_at=%s,reviewed_by=%s "
            "WHERE id=%s AND status='pending'",
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),admin['id'],suggestion_id),
        )
        if not cur.rowcount:
            db.rollback()
            cur.execute('SELECT id FROM news_suggestions WHERE id=%s',(suggestion_id,))
            if not cur.fetchone():
                abort(404,description='Предложение не найдено')
            return redirect('/py/admin/news?msg=Предложение+уже+рассмотрено&t=error')
        db.commit()
    except Exception as error:
        from werkzeug.exceptions import HTTPException
        if isinstance(error,HTTPException):
            raise
        get_db().rollback()
        app.logger.exception('Cannot reject news suggestion')
        abort(503)
    return redirect('/py/admin/news?msg=Предложение+отклонено&t=success')

@app.route('/py/admin/news/delete/<int:news_id>', methods=['POST'])
@admin_required
def admin_news_delete(news_id):
    try:
        db = get_db(); cur = get_cursor()
        cur.execute('DELETE FROM news_items WHERE id=%s', (news_id,))
        if not cur.rowcount: abort(404,description='Новость не найдена')
        db.commit()
    except Exception as error:
        from werkzeug.exceptions import HTTPException
        if isinstance(error,HTTPException): raise
        get_db().rollback()
        app.logger.exception('Cannot delete news')
        abort(503)
    return redirect('/py/admin/news?msg=Новость+удалена&t=success')

@app.route('/')
def root_redirect(): return redirect('/py/')

@app.route('/healthz')
def health():
    get_db().execute('SELECT 1').fetchone()
    return jsonify({'status':'ok'})

@app.route('/py/admin/backup',methods=['POST'])
@admin_required
def backup_database():
    import io
    import tempfile
    if USE_SQLITE:
        with tempfile.TemporaryDirectory() as directory:
            target=os.path.join(directory,'backup.db')
            with sqlite3.connect(target) as dest:
                get_db().backup(dest)
            # Активные сессии и токены не нужны в переносимой резервной копии.
            with sqlite3.connect(target) as dest:
                dest.execute('DELETE FROM web_sessions')
                dest.execute('DELETE FROM auth_throttle')
            with open(target,'rb') as stream:
                content=io.BytesIO(stream.read())
        response=send_file(content,as_attachment=True,
                         download_name='ege-trainer-backup.db',mimetype='application/octet-stream')
    else:
        import base64
        from datetime import date, datetime

        def encode_value(value):
            if isinstance(value, (bytes, bytearray, memoryview)):
                return {'__base64__': base64.b64encode(bytes(value)).decode('ascii')}
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            raise TypeError(f'Unsupported backup value type: {type(value).__name__}')

        tables = (
            'users', 'questions', 'essay_prompts', 'theory_sections', 'task_analyses',
            'guides', 'news_items', 'test_results', 'question_attempts', 'exam_sessions',
            'mistake_bank', 'essay_submissions', 'news_suggestions', 'support_tickets',
            'practice_sessions',
        )
        payload = {'format':'ege-trainer-backup-v1','tables':{}}
        db = get_db()
        for table in tables:
            payload['tables'][table] = [
                dict(row) for row in db.execute(f'SELECT * FROM {table}').fetchall()
            ]
        content=io.BytesIO(json.dumps(payload,ensure_ascii=False,default=encode_value).encode('utf-8'))
        response=send_file(content,as_attachment=True,
                         download_name='ege-trainer-backup.json',mimetype='application/json')
    response.headers['Cache-Control']='no-store'
    return response


@app.cli.command('make-admin')
def make_admin():
    """Promote an existing registered account, without a default password."""
    import click
    email=click.prompt('Email зарегистрированного пользователя').strip().lower()
    conn = connect_database(app.config)
    try:
        result=conn.execute('UPDATE users SET is_admin=1 WHERE lower(email)=? AND disabled=0',(email,))
        if not result.rowcount:
            conn.rollback()
            raise click.ClickException('Активный пользователь не найден')
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    click.echo('Права администратора назначены.')

if __name__=='__main__':
    port=int(os.environ.get('PORT',5000))
    app.run(host='0.0.0.0',port=port,debug=False)
