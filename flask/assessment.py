"""Server-owned question sets, atomic grading and retry-safe results."""
import json
import re
import secrets
from datetime import datetime, timedelta
from flask import abort


def public_questions(questions):
    return [
        dict({key: q[key] for key in ('id', 'text', 'options_list', 'task_number', 'section', 'difficulty', 'answer_type') if key in q},
             wrong_expl={})
        for q in questions
    ]


def start_practice(db, user_id, subject, mode, questions):
    token = secrets.token_urlsafe(24)
    db.execute(
        'INSERT INTO practice_sessions(id,user_id,subject,mode,question_ids_json) VALUES(?,?,?,?,?)',
        (token, user_id, subject, mode, json.dumps([q['id'] for q in questions])),
    )
    db.commit()
    return token


def validate_data(data):
    if not isinstance(data, dict):
        abort(400, description='Ожидается JSON-объект')
    if not isinstance(data.get('answers', {}), dict) or not isinstance(data.get('times', {}), dict):
        abort(400, description='Некорректный формат ответов или времени')


def integer(value, minimum, maximum):
    if isinstance(value, bool):
        abort(400, description='Некорректное числовое значение')
    try:
        if str(int(value)) != str(value):
            raise ValueError()
        value = int(value)
    except (TypeError, ValueError, OverflowError):
        abort(400, description='Некорректное числовое значение')
    if not minimum <= value <= maximum:
        abort(400, description='Число за пределами допустимого диапазона')
    return value


def normalize_answer(value):
    value = value.casefold().replace('ё', 'е').replace(',', '.')
    value = re.sub(r'\s+', '', value)
    return value.strip('.,;:')


def parse_db_datetime(value):
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def row_lock(db):
    return ' FOR UPDATE' if getattr(db, 'dialect', None) == 'postgres' else ''


def grade(db, user_id, subject, mode, ids, answers, times, xp_per_correct):
    if not ids:
        abort(400, description='В этой попытке нет заданий')
    expected = {str(i) for i in ids}
    if set(answers) - expected or set(times) - expected:
        abort(400, description='Ответы содержат задания из другой попытки')
    rows = db.execute(
        f"SELECT * FROM questions WHERE id IN ({','.join('?' for _ in ids)}) AND subject=?",
        (*ids, subject),
    ).fetchall()
    qmap = {q['id']: q for q in rows}
    if len(qmap) != len(ids):
        abort(409, description='Набор заданий изменился. Начните новую попытку.')
    results, slow_tasks = [], []
    for qid in ids:
        q = qmap[qid]
        opts = json.loads(q['options'])
        answer_type = q['answer_type'] if 'answer_type' in q.keys() else 'choice'
        answer_text = ''
        if answer_type == 'short':
            raw_answer = answers.get(str(qid), '')
            if isinstance(raw_answer, bool) or not isinstance(raw_answer, (str, int, float)):
                abort(400, description='Ответ должен быть текстом')
            answer_text = str(raw_answer).strip()
            if len(answer_text) > 1000:
                abort(400, description='Ответ слишком длинный')
            ai = -1
            accepted = json.loads(q['accepted_answers'] or '[]')
            if not accepted and q['correct_answer']:
                accepted = [q['correct_answer']]
            normalized = normalize_answer(answer_text)
            correct = bool(normalized) and normalized in {
                normalize_answer(str(value)) for value in accepted
            }
        else:
            ai = integer(answers.get(str(qid), -1), -1, len(opts) - 1)
            correct = ai == q['correct_index']
        seconds = integer(times.get(str(qid), 0), 0, 86400)
        if answer_type != 'short' and not 0 <= q['correct_index'] < len(opts):
            abort(503, description='Ошибка в задании. Обратитесь к администратору.')
        wrong = json.loads(q['wrong_explanations'] or '{}')
        results.append({
            'id': qid, 'task_number': q['task_number'], 'correct': correct,
            'answer_type': answer_type, 'correct_index': q['correct_index'],
            'correct_answer_text': q['correct_answer'] or '',
            'submitted_answer_text': answer_text,
            'explanation': q['explanation'] or '',
            'wrong_explanation': wrong.get(str(ai), '') if not correct else '',
            'correct_option_text': opts[q['correct_index']] if answer_type != 'short' else '',
        })
        if seconds > 300:
            slow_tasks.append(q['task_number'])
        db.execute(
            'INSERT INTO question_attempts(user_id,question_id,answer_idx,answer_text,is_correct,time_sec,mode) VALUES(?,?,?,?,?,?,?)',
            (user_id, qid, ai, answer_text, int(correct), seconds, mode),
        )
        if not correct:
            db.execute(
                '''INSERT INTO mistake_bank(user_id,question_id,wrong_answer_idx,wrong_answer_text) VALUES(?,?,?,?)
                   ON CONFLICT(user_id,question_id) DO UPDATE SET
                   wrong_answer_idx=excluded.wrong_answer_idx,
                   wrong_answer_text=excluded.wrong_answer_text,
                   review_count=mistake_bank.review_count+1,next_review=CURRENT_TIMESTAMP''',
                (user_id, qid, ai, answer_text),
            )
    correct_count = sum(r['correct'] for r in results)
    xp = correct_count * xp_per_correct
    db.execute('UPDATE users SET xp=xp+? WHERE id=?', (xp, user_id))
    return {
        'score': round(correct_count / len(ids) * 100),
        'correct': correct_count, 'total': len(ids), 'xp_gain': xp,
        'results': results, 'slow_tasks': slow_tasks,
    }


def save_result(db, user_id, subject, mode, result):
    db.execute(
        'INSERT INTO test_results(user_id,subject,score,questions_count,mode) VALUES(?,?,?,?,?)',
        (user_id, subject, result['score'], result['total'], mode),
    )
    db.execute('UPDATE users SET tests_completed=tests_completed+1 WHERE id=?', (user_id,))


def submit_practice(db, user_id, subject, data):
    validate_data(data)
    if not isinstance(data.get('practice_id'),str) or len(data['practice_id'])>100:
        abort(400,description='Некорректный идентификатор попытки')
    db.execute('BEGIN IMMEDIATE')
    row = db.execute(
        'SELECT * FROM practice_sessions WHERE id=? AND user_id=? AND subject=?' + row_lock(db),
        (data.get('practice_id'), user_id, subject),
    ).fetchone()
    if not row or row['mode'] not in ('quiz', 'adaptive'):
        abort(404, description='Попытка не найдена')
    if row['result_json']:
        db.commit()
        return json.loads(row['result_json'])
    if parse_db_datetime(row['created_at']) < datetime.now() - timedelta(days=1):
        abort(409, description='Попытка устарела. Начните новую.')
    result = grade(db, user_id, subject, row['mode'], json.loads(row['question_ids_json']),
                   data.get('answers', {}), data.get('times', {}), 10)
    save_result(db, user_id, subject, row['mode'], result)
    db.execute('UPDATE practice_sessions SET result_json=? WHERE id=?', (json.dumps(result), row['id']))
    db.commit()
    return result


def submit_exam(db, user_id, subject, data):
    validate_data(data)
    sid = integer(data.get('sess_id'), 1, 2**63 - 1)
    db.execute('BEGIN IMMEDIATE')
    row = db.execute(
        'SELECT * FROM exam_sessions WHERE id=? AND user_id=? AND subject=?' + row_lock(db),
        (sid, user_id, subject),
    ).fetchone()
    if not row:
        abort(404, description='Экзамен не найден')
    stored = json.loads(row['answers_json'] or '{}')
    if row['finished_at']:
        if stored.get('result'):
            db.commit()
            return stored['result']
        abort(409, description='Экзамен уже завершён')
    ids = stored.get('question_ids')
    if not ids:
        abort(409, description='Начните новый экзамен')
    deadline = parse_db_datetime(row['started_at']) + timedelta(minutes=row['time_limit_min'])
    # Короткое окно на доставку запроса после автозавершения таймера.
    answers = data.get('answers', {}) if datetime.now() <= deadline + timedelta(seconds=30) else {}
    result = grade(db, user_id, subject, 'exam', ids, answers, data.get('times', {}), 15)
    save_result(db, user_id, subject, 'exam', result)
    stored.update(answers=answers, result=result)
    db.execute(
        '''UPDATE exam_sessions SET finished_at=CURRENT_TIMESTAMP,score=?,correct=?,total=?,answers_json=?
           WHERE id=? AND user_id=?''',
        (result['score'], result['correct'], result['total'], json.dumps(stored), sid, user_id),
    )
    db.commit()
    return result


def submit_drill(db, user_id, subject, data):
    validate_data(data)
    if not isinstance(data.get('practice_id'),str) or len(data['practice_id'])>100:
        abort(400,description='Некорректный идентификатор тренировки')
    qid = integer(data.get('question_id'), 1, 2**63 - 1)
    db.execute('BEGIN IMMEDIATE')
    row = db.execute(
        "SELECT * FROM practice_sessions WHERE id=? AND user_id=? AND subject=? AND mode='drill'"
        + row_lock(db),
        (data.get('practice_id'), user_id, subject),
    ).fetchone()
    if not row or qid not in json.loads(row['question_ids_json']):
        abort(404, description='Тренировка или задание не найдены')
    saved = json.loads(row['result_json'] or '{}')
    if str(qid) in saved:
        db.commit()
        return saved[str(qid)]
    if saved.get('_complete'):
        abort(409, description='Тренировка завершена. Начните новую.')
    submitted = data.get('answer_text') if 'answer_text' in data else data.get('answer_idx')
    result = grade(db, user_id, subject, 'drill', [qid], {str(qid): submitted},
                   {str(qid): data.get('time_sec', 0)}, 10)
    answer = dict(result['results'][0], xp_gain=result['xp_gain'])
    saved[str(qid)] = answer
    values=list(saved.values())
    if len(saved) == len(json.loads(row['question_ids_json'])) or (
        len(values)>=3 and all(answer['correct'] for answer in values[-3:])
    ):
        correct = sum(r['correct'] for r in saved.values())
        save_result(db, user_id, subject, 'drill',
                    {'score': round(correct / len(saved) * 100), 'total': len(saved)})
        saved['_complete']=True
    db.execute('UPDATE practice_sessions SET result_json=? WHERE id=?', (json.dumps(saved), row['id']))
    db.commit()
    return answer
