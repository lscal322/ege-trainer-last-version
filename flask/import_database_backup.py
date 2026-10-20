"""Restore an admin SQLite/JSON backup into the development PostgreSQL database."""
import argparse
import base64
import json
import os
from pathlib import Path
import sqlite3

from storage import connect_database


TABLES = (
    'users', 'questions', 'essay_prompts', 'theory_sections', 'task_analyses',
    'guides', 'news_items', 'test_results', 'question_attempts', 'exam_sessions',
    'mistake_bank', 'essay_submissions', 'news_suggestions', 'support_tickets',
    'practice_sessions',
)
RESET_TABLES = TABLES + ('web_sessions', 'auth_throttle')
SERIAL_TABLES = tuple(table for table in TABLES if table != 'practice_sessions')
CONTENT_TABLES = (
    'questions', 'essay_prompts', 'theory_sections',
    'task_analyses', 'guides', 'news_items',
)
CONTENT_KEYS = {
    'questions': ('subject', 'part', 'task_number', 'section', 'text'),
    'essay_prompts': ('title',),
    'theory_sections': ('subject', 'title', 'content', 'order_index'),
    'task_analyses': ('subject', 'task_number', 'title', 'content'),
    'guides': ('subject', 'category', 'title', 'content', 'url'),
    'news_items': ('title', 'content', 'year', 'subject'),
}
BACKUP_FORMAT = 'ege-trainer-backup-v1'


def decode_json_value(value):
    if isinstance(value, dict) and set(value) == {'__base64__'}:
        return base64.b64decode(value['__base64__'], validate=True)
    return value


def content_key(table, row):
    return tuple(row.get(column) for column in CONTENT_KEYS[table])


def read_backup(path):
    if path.suffix.lower() == '.json':
        payload = json.loads(path.read_text(encoding='utf-8'))
        if payload.get('format') != BACKUP_FORMAT or not isinstance(payload.get('tables'), dict):
            raise ValueError('Неподдерживаемый формат JSON-копии.')
        result = {}
        for table in TABLES:
            rows = payload['tables'].get(table, [])
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError(f'Повреждены данные таблицы {table}.')
            result[table] = [
                {key: decode_json_value(value) for key, value in row.items()}
                for row in rows
            ]
        return result

    source = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    try:
        integrity = source.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            raise ValueError(f'Проверка SQLite не прошла: {integrity}')
        available = {
            row[0] for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not {'users', 'questions'}.issubset(available):
            raise ValueError('В файле нет обязательных таблиц users/questions.')

        result = {}
        for table in TABLES:
            if table not in available:
                result[table] = []
                continue
            result[table] = [
                dict(row) for row in source.execute(f'SELECT * FROM {table}').fetchall()
            ]
        violations = source.execute('PRAGMA foreign_key_check').fetchall()
        if violations:
            raise ValueError(f'В резервной копии найдены нарушения связей: {len(violations)}.')
        return result
    finally:
        source.close()


def import_backup(path, dry_run=False):
    if os.environ.get('APP_ENV', '').lower() == 'production':
        raise RuntimeError('Импорт в production запрещён. Запустите его в development-среде.')
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise RuntimeError('Не подключена development PostgreSQL-база.')

    tables = read_backup(path)
    if not tables['users'] or not tables['questions']:
        raise ValueError('Копия должна содержать пользователей и задания.')

    db = connect_database({
        'USE_SQLITE': False,
        'DATABASE_URL': database_url,
    })
    try:
        # Проверяем целевую схему до очистки: все обязательные поля должны быть
        # перенесены либо иметь значение по умолчанию в PostgreSQL.
        target_columns = {}
        for table in RESET_TABLES:
            rows = db.execute(
                '''SELECT column_name,is_nullable,column_default
                   FROM information_schema.columns
                   WHERE table_schema=current_schema() AND table_name=?''',
                (table,),
            ).fetchall()
            if not rows:
                raise RuntimeError(f'В PostgreSQL отсутствует таблица {table}.')
            target_columns[table] = {
                row['column_name']: row for row in rows
            }

        # Keep the newer study bank in development when importing an older
        # published SQLite copy. Published question IDs stay untouched so
        # previous attempts and unfinished exams continue to point to them.
        preserved_content = {
            table: [dict(row) for row in db.execute(f'SELECT * FROM {table}').fetchall()]
            for table in CONTENT_TABLES
        }
        db.execute('TRUNCATE TABLE ' + ','.join(RESET_TABLES) + ' RESTART IDENTITY CASCADE')
        imported_counts = {}
        for table in TABLES:
            rows = tables[table]
            target = target_columns[table]
            source_columns = set(rows[0]) if rows else set()
            columns = [name for name in target if name in source_columns]
            missing_required = [
                name for name, definition in target.items()
                if name not in source_columns
                and definition['is_nullable'] == 'NO'
                and definition['column_default'] is None
            ]
            if rows and missing_required:
                raise ValueError(
                    f'В копии не хватает обязательных полей {table}: '
                    + ', '.join(missing_required)
                )
            if rows:
                if any(set(row) != source_columns for row in rows):
                    raise ValueError(f'В строках таблицы {table} различается набор полей.')
                column_sql = ','.join(f'"{column}"' for column in columns)
                values_sql = ','.join('?' for _ in columns)
                db.executemany(
                    f'INSERT INTO {table} ({column_sql}) VALUES ({values_sql})',
                    [tuple(row[column] for column in columns) for row in rows],
                )
            imported_counts[table] = len(rows)

        preserved_counts = {}
        expected_counts = dict(imported_counts)
        for table in CONTENT_TABLES:
            existing_keys = {content_key(table, row) for row in tables[table]}
            target = target_columns[table]
            columns = [name for name in target if name != 'id']
            db.execute(
                f"""SELECT setval(pg_get_serial_sequence(?, 'id'),
                      COALESCE((SELECT MAX(id) FROM {table}), 1),
                      EXISTS(SELECT 1 FROM {table}))""",
                (table,),
            )
            for row in preserved_content[table]:
                key = content_key(table, row)
                if key in existing_keys:
                    continue
                column_sql = ','.join('"' + name + '"' for name in columns)
                values_sql = ','.join('?' for _ in columns)
                db.execute(
                    f'INSERT INTO {table} ({column_sql}) VALUES ({values_sql})',
                    tuple(row[name] for name in columns),
                )
                existing_keys.add(key)
                expected_counts[table] += 1
            preserved_counts[table] = expected_counts[table] - imported_counts[table]

        for table in SERIAL_TABLES:
            db.execute(
                f"""SELECT setval(pg_get_serial_sequence(?, 'id'),
                      COALESCE((SELECT MAX(id) FROM {table}), 1),
                      EXISTS(SELECT 1 FROM {table}))""",
                (table,),
            )

        for table, expected in expected_counts.items():
            actual = db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            if actual != expected:
                raise RuntimeError(
                    f'Проверка переноса {table} не прошла: ожидалось {expected}, записано {actual}.'
                )
        if dry_run:
            db.rollback()
        else:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return {'source': imported_counts, 'preserved_content_added': preserved_counts}


def main():
    parser = argparse.ArgumentParser(
        description='Восстановить резервную копию тренажёра в development PostgreSQL.'
    )
    parser.add_argument('backup', type=Path, help='SQLite .db или JSON-копия из админки')
    parser.add_argument(
        '--replace-development-data',
        action='store_true',
        help='явно разрешить замену данных в development PostgreSQL',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='проверить копию и целевую схему, затем отменить все изменения',
    )
    args = parser.parse_args()
    if not args.replace_development_data:
        parser.error('для переноса укажите --replace-development-data')
    if not args.backup.is_file():
        parser.error('файл резервной копии не найден')
    counts = import_backup(args.backup, dry_run=args.dry_run)
    print(
        'Проверка переноса завершена; изменения отменены.'
        if args.dry_run else
        'Перенос завершён; количество записей по таблицам:'
    )
    for table, count in counts['source'].items():
        print(f'{table}: {count}')
    print('Дополнительно сохранено учебных материалов из development:')
    for table, count in counts['preserved_content_added'].items():
        print(f'{table}: {count}')


if __name__ == '__main__':
    main()
