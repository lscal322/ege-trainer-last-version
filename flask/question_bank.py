"""Deterministic supplementary EGE practice items for all supported subjects."""
import json


def _make_question(subject, index, task_number, section, part, prompt, answer, explanation, answer_kind='number'):
    answer = str(answer).strip()
    is_short = index % 2 == 1
    accepted = [answer]
    if subject == 'russian' and answer_kind == 'letter':
        accepted.append(prompt.split('«', 1)[1].split('»', 1)[0].replace('□', answer))

    if is_short:
        options = []
        correct_index = -1
        answer_type = 'short'
    else:
        if answer_kind == 'letter':
            choices = ['а', 'о', 'е', 'и']
            correct_index = choices.index(answer)
            options = choices
        elif answer_kind == 'binary':
            value = int(answer, 2)
            correct_index = (index // 2) % 4
            binary_choices = [format(value, 'b')]
            for candidate in (value + 1, max(0, value - 1), value + 2, max(0, value - 2)):
                choice = format(candidate, 'b')
                if choice not in binary_choices:
                    binary_choices.append(choice)
                if len(binary_choices) == 4:
                    break
            options = binary_choices[:]
            options.remove(answer)
            options.insert(correct_index, answer)
        else:
            try:
                value = int(answer)
                candidates = [value + 1, value - 1, value + 2, value - 2, value + 3]
                distractors = []
                for candidate in candidates:
                    if candidate >= 0 and str(candidate) != answer and str(candidate) not in distractors:
                        distractors.append(str(candidate))
                    if len(distractors) == 3:
                        break
                choices = [answer] + distractors
                correct_index = (index // 2) % 4
                options = choices[:]
                options.remove(answer)
                options.insert(correct_index, answer)
            except ValueError:
                choices = [answer, '0', '1', '2']
                options = choices[:]
                correct_index = 0
        answer_type = 'choice'

    return {
        'subject': subject,
        'part': part,
        'task_number': task_number,
        'section': section,
        'difficulty': 'base',
        'text': prompt,
        'options': json.dumps(options, ensure_ascii=False),
        'correct_index': correct_index,
        'correct_answer': answer,
        'accepted_answers': json.dumps(accepted, ensure_ascii=False),
        'answer_type': answer_type,
        'explanation': explanation,
        'wrong_explanations': '{}',
    }


def _math_questions():
    # FIPI 2026 profile KIM: expressions (7), equations (6), geometry (1),
    # probability (4), function analysis (8), and contextual problems (10).
    task_numbers = [7, 6, 10, 1, 4, 7, 7, 8, 6, 10]
    sections = [
        'Вычисления', 'Линейные уравнения', 'Проценты', 'Планиметрия',
        'Вероятность', 'Арифметическая прогрессия', 'Степени',
        'Производная', 'Квадратные уравнения', 'Текстовые задачи',
    ]
    for i in range(200):
        n, kind = divmod(i, 10)
        if kind == 0:
            a, b, c = n + 4, n % 7 + 2, n % 5 + 3
            answer = a + b * c
            prompt = f'Вычислите: {a} + {b} · {c}.'
            explanation = f'Сначала умножаем: {b} · {c} = {b*c}, затем прибавляем {a}: ответ {answer}.'
        elif kind == 1:
            a, x, b = n % 6 + 2, n + 3, n % 9 + 1
            answer = x
            prompt = f'Найдите корень уравнения {a}x + {b} = {a*x+b}.'
            explanation = f'Вычитаем {b} и делим на {a}: x = {x}.'
        elif kind == 2:
            percent, total = 10 + (n % 8) * 5, 200 + 20 * n
            answer = percent * total // 100
            prompt = f'Товар стоил {total} рублей. Во время распродажи цену снизили на {percent}%. На сколько рублей снизилась цена?'
            explanation = f'{total} · {percent}/100 = {answer} рублей — размер снижения цены.'
        elif kind == 3:
            a, b = n + 3, n + 5
            answer = a * b
            prompt = f'Найдите площадь прямоугольника со сторонами {a} см и {b} см.'
            explanation = f'S = a · b = {a} · {b} = {answer} см².'
        elif kind == 4:
            favorable = 5 * (n + 1)
            outcomes = 100
            answer = favorable
            prompt = f'В опыте {outcomes} равновозможных исходов, {favorable} из них благоприятны. Найдите вероятность события в процентах.'
            explanation = f'P = {favorable}/{outcomes} · 100% = {answer}%.'
        elif kind == 5:
            first, step, position = n + 1, n % 5 + 2, n % 8 + 5
            answer = first + (position - 1) * step
            prompt = f'Первый член арифметической прогрессии равен {first}, разность равна {step}. Найдите член с номером {position}.'
            explanation = f'aₙ = a₁ + (n − 1)d = {first} + ({position} − 1)·{step} = {answer}.'
        elif kind == 6:
            base, power = n + 2, n % 2 + 2
            answer = base ** power
            prompt = f'Вычислите значение выражения {base}^{power}.'
            explanation = f'{base}^{power} = {answer}.'
        elif kind == 7:
            a, b, x = n % 7 + 1, n % 6 + 2, n % 5 + 2
            answer = 2 * a * x + b
            prompt = f'Найдите значение производной функции f(x) = {a}x² + {b}x в точке x = {x}.'
            explanation = f'f′(x) = {2*a}x + {b}; f′({x}) = {answer}.'
        elif kind == 8:
            root = n + 2
            answer = root
            prompt = f'Найдите положительный корень уравнения x² − {root*root} = 0.'
            explanation = f'x² = {root*root}, поэтому положительный корень равен {root}.'
        else:
            unit, scale = n + 2, n % 6 + 2
            distance = unit * scale
            answer = scale
            prompt = f'Автомобиль проехал {distance} км со скоростью {unit} км/ч. Сколько часов заняла поездка?'
            explanation = f't = s/v = {distance}/{unit} = {answer} ч.'
        yield _make_question(
            'math', i, task_numbers[kind], sections[kind],
            'part1', prompt, answer, explanation,
        )


_RUSSIAN_WORDS = [
    ('заг□реть', 'о', 'Чередование гар/гор'), ('выг□реть', 'о', 'Чередование гар/гор'),
    ('гор□ние', 'е', 'Правописание суффиксов'), ('заг□р', 'а', 'Чередование гар/гор'),
    ('з□ря', 'а', 'Чередование зар/зор'), ('з□рница', 'а', 'Чередование зар/зор'),
    ('з□рька', 'о', 'Чередование зар/зор'), ('кас□ться', 'а', 'Чередование кас/кос'),
    ('к□снуться', 'о', 'Чередование кас/кос'), ('прик□сновение', 'о', 'Чередование кас/кос'),
    ('кас□тельная', 'а', 'Чередование кас/кос'), ('предл□гать', 'а', 'Чередование лаг/лож'),
    ('предл□жение', 'о', 'Чередование лаг/лож'), ('изл□гать', 'а', 'Чередование лаг/лож'),
    ('изл□жение', 'о', 'Чередование лаг/лож'), ('выращ□вать', 'и', 'Правописание суффиксов'),
    ('раст□ние', 'е', 'Правописание суффиксов'), ('р□сток', 'о', 'Исключение: росток'),
    ('в□зраст', 'о', 'Чередование раст/ращ/рос'), ('выр□сти', 'а', 'Чередование раст/ращ/рос'),
    ('выр□сший', 'о', 'Чередование раст/ращ/рос'), ('подр□сток', 'о', 'Чередование раст/ращ/рос'),
    ('отр□сль', 'а', 'Исключение: отрасль'), ('зар□сли', 'о', 'Чередование раст/ращ/рос'),
    ('прораст□ть', 'а', 'Правописание суффиксов'), ('соб□рать', 'и', 'Чередование бер/бир'),
    ('соб□ру', 'е', 'Чередование бер/бир'), ('выб□рать', 'и', 'Чередование бер/бир'),
    ('выб□ру', 'е', 'Чередование бер/бир'), ('заб□рать', 'и', 'Чередование бер/бир'),
    ('заб□ру', 'е', 'Чередование бер/бир'), ('расст□лать', 'и', 'Чередование стел/стил'),
    ('заст□лить', 'е', 'Чередование стел/стил'), ('выт□рать', 'и', 'Чередование тер/тир'),
    ('выт□реть', 'е', 'Чередование тер/тир'), ('зам□рать', 'и', 'Чередование мер/мир'),
    ('зам□реть', 'е', 'Чередование мер/мир'), ('отд□рать', 'и', 'Чередование дер/дир'),
    ('отд□ру', 'е', 'Чередование дер/дир'), ('бл□стать', 'и', 'Чередование блест/блист'),
    ('бл□стеть', 'е', 'Чередование блест/блист'), ('проб□раться', 'и', 'Чередование бер/бир'),
    ('проб□русь', 'е', 'Чередование бер/бир'), ('расст□латься', 'и', 'Чередование стел/стил'),
    ('заст□лать', 'и', 'Чередование стел/стил'), ('выж□гать', 'и', 'Чередование жег/жиг'),
    ('выж□г', 'е', 'Чередование жег/жиг'), ('переб□рать', 'и', 'Чередование бер/бир'),
    ('переб□ру', 'е', 'Чередование бер/бир'), ('соб□ратель', 'и', 'Чередование бер/бир'),
]
_RUSSIAN_FRAMES = [
    'Вставьте пропущенную букву в слове «{word}». Ответьте одной буквой.',
    'Укажите гласную, которую нужно вставить: «{word}».',
    'В корне слова «{word}» пропущена буква. Запишите её.',
    'Восстановите написание слова «{word}»: укажите пропущенную гласную.',
]


def _russian_questions():
    for i in range(200):
        word_index, frame_index = divmod(i, 4)
        mask, answer, section = _RUSSIAN_WORDS[word_index]
        word = mask.replace('□', answer)
        prompt = _RUSSIAN_FRAMES[frame_index].format(word=mask)
        explanation = f'Правильное написание: «{word}». Тема: {section.lower()}.'
        yield _make_question(
            'russian', i, 11 if section == 'Правописание суффиксов' else 9,
            section, 'part1', prompt, answer, explanation, 'letter',
        )


def _physics_questions():
    task_numbers = [1, 2, 11, 11, 3, 4, 3, 3, 11, 4]
    sections = [
        'Кинематика', 'Динамика', 'Электрический ток', 'Мощность',
        'Работа', 'Плотность', 'Кинетическая энергия', 'Потенциальная энергия',
        'Электрические цепи', 'Колебания',
    ]
    for i in range(200):
        n, kind = divmod(i, 10)
        if kind == 0:
            speed, time = n + 3, n % 8 + 2
            answer = speed * time
            prompt = f'Тело движется равномерно со скоростью {speed} м/с в течение {time} с. Найдите путь в метрах.'
            explanation = f's = vt = {speed} · {time} = {answer} м.'
        elif kind == 1:
            mass, acceleration = n % 9 + 2, n % 7 + 1
            answer = mass * acceleration
            prompt = f'На тело массой {mass} кг действует равнодействующая сила. Ускорение равно {acceleration} м/с². Найдите силу в ньютонах.'
            explanation = f'F = ma = {mass} · {acceleration} = {answer} Н.'
        elif kind == 2:
            voltage, resistance = 12 + 2 * n, n % 8 + 2
            answer = voltage // resistance if voltage % resistance == 0 else voltage
            if voltage % resistance:
                resistance = 2
                voltage = 12 + 2 * n
                answer = voltage // resistance
            prompt = f'Напряжение на резисторе {voltage} В, сопротивление {resistance} Ом. Найдите силу тока в амперах.'
            explanation = f'I = U/R = {voltage}/{resistance} = {answer} А.'
        elif kind == 3:
            voltage, current = n + 4, n % 6 + 2
            answer = voltage * current
            prompt = f'При напряжении {voltage} В через прибор течёт ток {current} А. Найдите мощность в ваттах.'
            explanation = f'P = UI = {voltage} · {current} = {answer} Вт.'
        elif kind == 4:
            force, distance = n + 5, n % 7 + 2
            answer = force * distance
            prompt = f'Сила {force} Н перемещает тело на {distance} м по направлению силы. Найдите работу в джоулях.'
            explanation = f'A = Fs = {force} · {distance} = {answer} Дж.'
        elif kind == 5:
            mass, volume = 2 * (n + 2), n % 5 + 1
            answer = mass // volume if mass % volume == 0 else mass
            if mass % volume:
                volume = 2
                mass = 2 * (n + 2)
                answer = mass // volume
            prompt = f'Масса однородного тела {mass} кг, объём {volume} м³. Найдите плотность в кг/м³.'
            explanation = f'ρ = m/V = {mass}/{volume} = {answer} кг/м³.'
        elif kind == 6:
            mass, speed = n + 2, 2 * (n % 3 + 1)
            answer = mass * speed * speed // 2
            prompt = f'Тело массой {mass} кг движется со скоростью {speed} м/с. Найдите его кинетическую энергию в джоулях.'
            explanation = f'Eₖ = mv²/2 = {mass} · {speed}²/2 = {answer} Дж.'
        elif kind == 7:
            mass, height = n % 7 + 1, n + 2
            answer = mass * 10 * height
            prompt = f'Тело массой {mass} кг находится на высоте {height} м. Примите g = 10 м/с². Найдите потенциальную энергию в джоулях.'
            explanation = f'Eₚ = mgh = {mass} · 10 · {height} = {answer} Дж.'
        elif kind == 8:
            first, second = n % 8 + 2, n % 6 + 3
            answer = first + second
            prompt = f'Два резистора сопротивлениями {first} Ом и {second} Ом соединены последовательно. Найдите общее сопротивление в омах.'
            explanation = f'При последовательном соединении R = R₁ + R₂ = {first} + {second} = {answer} Ом.'
        else:
            period, cycles = n % 5 + 1, n + 2
            duration = period * cycles
            answer = cycles
            prompt = f'Период колебаний равен {period} с. Сколько полных колебаний совершит тело за {duration} с?'
            explanation = f'N = t/T = {duration}/{period} = {cycles} колебаний.'
        yield _make_question(
            'physics', i, task_numbers[kind], sections[kind],
            'part1', prompt, answer, explanation,
        )


def _informatics_questions():
    task_numbers = [14, 7, 8, 2, 5, 6, 5, 6, 14, 8]
    sections = [
        'Системы счисления', 'Объём информации', 'Единицы информации',
        'Логика', 'Python: арифметика', 'Python: циклы',
        'Последовательности', 'Алгоритмы', 'Двоичная запись', 'Кодирование',
    ]
    for i in range(200):
        n, kind = divmod(i, 10)
        if kind == 0:
            number = 32 + n * 7
            answer = format(number, 'b')
            prompt = f'Переведите число {number}₁₀ в двоичную систему счисления.'
            explanation = f'{number}₁₀ = {answer}₂.'
        elif kind == 1:
            width, height, depth = 10 + n, 8 + n % 6, 8
            answer = width * height * depth
            prompt = f'Изображение размером {width} × {height} пикселей кодируется {depth} битами на пиксель. Найдите объём в битах.'
            explanation = f'V = {width} · {height} · {depth} = {answer} бит.'
        elif kind == 2:
            kib = n + 2
            answer = kib * 1024
            prompt = f'Сколько байт содержится в {kib} КиБ? Считайте, что 1 КиБ = 1024 байта.'
            explanation = f'{kib} · 1024 = {answer} байт.'
        elif kind == 3:
            a, b, c, d, e = tuple((n >> bit) & 1 for bit in range(5))
            answer = int(bool(a and b) or bool(c and d) or bool(e))
            prompt = f'Вычислите значение выражения ({a} AND {b}) OR ({c} AND {d}) OR {e}.'
            explanation = f'({a} AND {b}) OR ({c} AND {d}) OR {e} = {answer}.'
        elif kind == 4:
            a, b = n + 7, n % 6 + 2
            answer = a // b + a % b
            prompt = f'Что выведет Python: print({a} // {b} + {a} % {b})?'
            explanation = f'{a} // {b} = {a//b}, {a} % {b} = {a%b}; сумма равна {answer}.'
        elif kind == 5:
            count = n + 3
            answer = count * (count + 1) // 2
            prompt = f'Цикл выполняет сумму чисел от 1 до {count} включительно. Какое значение получится?'
            explanation = f'Сумма первых n чисел: n(n+1)/2 = {count}·{count+1}/2 = {answer}.'
        elif kind == 6:
            first, step, count = n + 2, n % 5 + 1, n % 8 + 4
            answer = first + step * (count - 1)
            prompt = f'Последовательность начинается с {first}, каждый следующий член на {step} больше. Найдите член с номером {count}.'
            explanation = f'aₙ = a₁ + (n−1)d = {first} + ({count}−1)·{step} = {answer}.'
        elif kind == 7:
            count = n + 5
            answer = count
            prompt = f'Алгоритм последовательно проверяет каждый элемент массива из {count} элементов один раз. Сколько проверок он выполнит?'
            explanation = f'По одной проверке на элемент: {count} проверок.'
        elif kind == 8:
            number = 24 + n * 5
            answer = format(number, 'b')
            prompt = f'Запишите число {number}₁₀ в двоичной системе счисления.'
            explanation = f'{number}₁₀ = {answer}₂.'
        else:
            symbols, bits = n + 3, n + 2
            answer = symbols * bits
            prompt = f'В сообщении {symbols} символа(ов), каждый записывается кодом длиной {bits} бит. Найдите общий объём сообщения в битах.'
            explanation = f'V = {symbols} · {bits} = {answer} бит.'
        yield _make_question(
            'informatics', i, task_numbers[kind], sections[kind],
            'part1', prompt, answer, explanation,
            'binary' if kind in (0, 8) else 'number',
        )


def build_question_bank():
    """Return 200 new deterministic tasks per subject."""
    yield from _math_questions()
    yield from _russian_questions()
    yield from _physics_questions()
    yield from _informatics_questions()


def _legacy_prompt(question, subject_index):
    """Return a previous generated prompt when a deterministic item's data changed."""
    index = subject_index
    n, kind = divmod(index, 10)
    if question['subject'] == 'math' and kind == 2:
        percent, total = 10 + (n % 8) * 5, 200 + 20 * n
        return f'Найдите {percent}% от числа {total}.'
    if question['subject'] == 'math' and kind == 4:
        favorable = n % 9 + 1
        outcomes = 10 * (n // 9 + 1)
        return (
            f'В опыте {outcomes} равновозможных исходов, из них {favorable} благоприятны. '
            'Чему равна вероятность в процентах?'
        )
    if question['subject'] == 'math' and kind == 9:
        unit, scale = n + 2, n % 6 + 2
        return f'Цена одной тетради {unit} рублей. Сколько стоят {scale} таких тетрадей?'
    if question['subject'] == 'physics' and kind == 6:
        mass, speed = n % 8 + 2, n % 6 + 2
        return (
            f'Тело массой {mass} кг движется со скоростью {speed} м/с. '
            'Найдите его кинетическую энергию в джоулях.'
        )
    return None


def seed_question_bank(conn):
    existing = {
        (row[0], row[1])
        for row in conn.execute('SELECT subject, text FROM questions')
    }
    rows = []
    subject_indices = {}
    for question in build_question_bank():
        subject_index = subject_indices.get(question['subject'], 0)
        subject_indices[question['subject']] = subject_index + 1
        key = (question['subject'], question['text'])
        legacy_text = _legacy_prompt(question, subject_index)
        legacy_key = (question['subject'], legacy_text) if legacy_text else None
        if key not in existing and legacy_key in existing:
            conn.execute(
                '''UPDATE questions SET text=?,part=?,task_number=?,section=?,difficulty=?,options=?,
                     correct_index=?,correct_answer=?,accepted_answers=?,answer_type=?,explanation=?,
                     wrong_explanations=? WHERE subject=? AND text=?''',
                (
                    question['text'], question['part'], question['task_number'],
                    question['section'], question['difficulty'], question['options'],
                    question['correct_index'], question['correct_answer'],
                    question['accepted_answers'], question['answer_type'],
                    question['explanation'], question['wrong_explanations'],
                    question['subject'], legacy_text,
                ),
            )
            existing.remove(legacy_key)
            existing.add(key)
            continue
        if key in existing:
            # Keep already-seeded databases in sync when a generated key,
            # explanation, section, or official task position is corrected.
            conn.execute(
                '''UPDATE questions SET part=?,task_number=?,section=?,difficulty=?,options=?,
                     correct_index=?,correct_answer=?,accepted_answers=?,answer_type=?,explanation=?,
                     wrong_explanations=? WHERE subject=? AND text=?''',
                (
                    question['part'], question['task_number'], question['section'],
                    question['difficulty'], question['options'], question['correct_index'],
                    question['correct_answer'], question['accepted_answers'],
                    question['answer_type'], question['explanation'], question['wrong_explanations'],
                    question['subject'], question['text'],
                ),
            )
            continue
        existing.add(key)
        rows.append((
            question['subject'], question['part'], question['task_number'],
            question['section'], question['difficulty'], question['text'],
            question['options'], question['correct_index'], question['correct_answer'],
            question['accepted_answers'], question['answer_type'],
            question['explanation'], question['wrong_explanations'],
        ))
    conn.executemany(
        '''INSERT INTO questions(
             subject,part,task_number,section,difficulty,text,options,correct_index,
             correct_answer,accepted_answers,answer_type,explanation,wrong_explanations
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        rows,
    )
    return len(rows)
