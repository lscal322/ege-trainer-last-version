"""Deterministic free-response practice for extended and advanced EGE tasks."""
import json
import math

from question_bank import _make_question


def _free_response(
    subject, index, task_number, section, prompt, answer, explanation,
    kind='number', accepted=None,
):
    item = _make_question(
        subject, index, task_number, section, 'part2',
        prompt, answer, explanation, kind,
    )
    item['difficulty'] = 'part2_bank'
    item['answer_type'] = 'short'
    item['options'] = json.dumps([], ensure_ascii=False)
    item['correct_index'] = -1
    item['accepted_answers'] = json.dumps(
        accepted if accepted is not None else [str(answer)],
        ensure_ascii=False,
    )
    return item


def _math_part2():
    task_numbers = [13, 14, 15, 16, 17, 17, 18, 19]
    sections = [
        'Логарифмические уравнения', 'Стереометрия', 'Рациональные неравенства',
        'Финансовая математика', 'Текстовые задачи', 'Оптимизация',
        'Задачи с параметром', 'Целочисленные задачи',
    ]
    for i in range(200):
        n, kind = divmod(i, len(task_numbers))
        if kind == 0:
            root = n + 8
            answer = root
            prompt = (
                f'Решите уравнение log₂(x − {root - 2}) + '
                f'log₂(x − {root - 4}) = 3. В ответ запишите корень.'
            )
            explanation = (
                f'ОДЗ: x > {root - 2}. Объединяем логарифмы: '
                f'(x − {root - 2})(x − {root - 4}) = 8. '
                f'После замены y=x−{root} получаем y²+6y=0, откуда '
                f'x={root} или x={root - 6}. Второе значение не входит в ОДЗ; ответ {answer}.'
            )
        elif kind == 1:
            radius = n + 2
            height = 3 * (n % 6 + 1)
            answer = radius * radius * (height // 3)
            prompt = (
                f'Найдите коэффициент k в объёме конуса V=kπ, если радиус '
                f'основания равен {radius}, а высота — {height}.'
            )
            explanation = (
                f'V=⅓πr²h, поэтому k=r²h/3={radius}²·{height}/3='
                f'{answer}. В ответе требуется только коэффициент при π: {answer}.'
            )
        elif kind == 2:
            left_root = n % 11 - 5
            gap = n % 5 + 2
            right_root = left_root + gap
            lower, upper = -8 - n % 4, 10 + n % 6
            valid = [
                x for x in range(lower, upper + 1)
                if x != right_root and (x - left_root) / (x - right_root) >= 0
            ]
            answer = len(valid)
            prompt = (
                f'Решите неравенство (x − ({left_root}))/(x − ({right_root})) ≥ 0. '
                f'Сколько целых решений лежит на отрезке [{lower}; {upper}]?'
            )
            explanation = (
                f'Критические точки: {left_root} (нуль числителя) и {right_root} '
                f'(запрещённая точка). По методу интервалов решение: '
                f'x ≤ {left_root} или x > {right_root}. На отрезке '
                f'[{lower}; {upper}] этим условиям удовлетворяют {answer} целых чисел.'
            )
        elif kind == 3:
            principal = 120000 + 5000 * n
            rate = 5 + 5 * (n % 5)
            amount = principal * (100 + rate) ** 2 / 10000
            answer = int(amount + 0.5)
            prompt = (
                f'Вклад {principal} рублей увеличивается на {rate}% в конце каждого года. '
                f'Найдите сумму через 2 года и округлите до целого рубля.'
            )
            explanation = (
                f'Проценты начисляются на новую сумму: S={principal}·'
                f'(1+{rate}/100)²={amount:.2f} руб. После округления ответ: {answer}.'
            )
        elif kind == 4:
            first_time = 6 * (n + 1)
            second_time = first_time * 2
            answer = 2 * first_time // 3
            prompt = (
                f'Первый насос наполняет резервуар за {first_time} ч, второй — '
                f'за {second_time} ч. За сколько часов они наполнят его вместе?'
            )
            explanation = (
                f'Скорость первого насоса 1/{first_time} резервуара в час, '
                f'второго — 1/{second_time}. Общая скорость равна '
                f'1/{first_time}+1/{second_time}=3/(2·{first_time}); '
                f'время работы {answer} ч.'
            )
        elif kind == 5:
            fence = 8 * (n + 2)
            width = fence // 4
            length = fence // 2
            answer = width * length
            prompt = (
                f'Прямоугольный участок ограждают с трёх сторон; четвёртая сторона '
                f'примыкает к стене. Длина ограды — {fence} м. Найдите наибольшую '
                f'возможную площадь участка в м².'
            )
            explanation = (
                f'Пусть ширина x, тогда длина {fence}−2x и площадь '
                f'S(x)=x({fence}−2x). Парабола направлена вниз; вершина при '
                f'x={fence}/4={width} м. Тогда длина {length} м и '
                f'Smax={width}·{length}={answer} м².'
            )
        elif kind == 6:
            bound = n + 8
            low_parameter = max(-bound, 5)
            high_parameter = min(bound, 16)
            answer = max(0, high_parameter - low_parameter + 1)
            prompt = (
                f'Для каких целых a оба корня уравнения (x−a)²=16 принадлежат '
                f'отрезку [1; 20]? Сколько таких a лежит в диапазоне '
                f'от −{bound} до {bound} включительно?'
            )
            explanation = (
                'Корни равны a−4 и a+4. Условия 1≤a−4 и a+4≤20 дают '
                '5≤a≤16. После пересечения с заданным диапазоном получаем '
                f'{answer} целых значений параметра.'
            )
        else:
            x0 = n + 1
            y0 = n + 2
            target = x0 * x0 + y0 * y0
            pairs = [
                (x, y)
                for x in range(1, math.isqrt(target) + 1)
                for y in range(x, math.isqrt(target) + 1)
                if x * x + y * y == target
            ]
            answer = len(pairs)
            pair_text = ', '.join(f'({x}; {y})' for x, y in pairs)
            prompt = (
                f'Сколько неупорядоченных пар положительных целых чисел (x; y) '
                f'удовлетворяют уравнению x²+y²={target}?'
            )
            explanation = (
                f'Проверяем положительные x,y не больше √{target} и оставляем '
                f'пары с x≤y. Подходящие пары: {pair_text}. Их количество — {answer}.'
            )
        yield _free_response(
            'math', i, task_numbers[kind], sections[kind],
            prompt, answer, explanation,
        )


def _physics_part2():
    task_numbers = [21, 22, 23, 23, 24, 22, 24, 25, 25, 26]
    sections = [
        'Качественная задача: сопротивление проводника', 'Механика: движение системы тел',
        'Молекулярная физика: газовые законы', 'Термодинамика: количество теплоты',
        'Электрическая цепь: закон Ома', 'Механика: импульс',
        'Электричество: соединение проводников', 'Электромагнитная индукция',
        'Квантовая физика: энергия фотона', 'Механика: изменение энергии',
    ]
    for i in range(200):
        n, kind = divmod(i, len(task_numbers))
        if kind == 0:
            factor = n + 2
            answer = 'не изменится'
            prompt = (
                f'Длину и площадь поперечного сечения однородного провода одновременно '
                f'увеличили в {factor} раза. Материал и температура не изменились. '
                f'Как изменилось сопротивление? Запишите: «увеличилось», «уменьшилось» '
                f'или «не изменилось».'
            )
            explanation = (
                f'R=ρl/S. После изменения R₂=ρ({factor}l)/({factor}S)=ρl/S, '
                f'поэтому сопротивление не изменится.'
            )
        elif kind == 1:
            m1, m2 = n % 5 + 2, n % 7 + 3
            acceleration = n % 4 + 1
            force = (m1 + m2) * acceleration
            prompt = (
                f'Два тела массами {m1} кг и {m2} кг движутся вместе по гладкой '
                f'поверхности под действием горизонтальной силы {force} Н. '
                f'Найдите ускорение системы в м/с².'
            )
            answer = acceleration
            explanation = (
                f'Рассматриваем оба тела как одну систему: F=(m₁+m₂)a. '
                f'a={force}/({m1}+{m2})={answer} м/с².'
            )
        elif kind == 2:
            pressure = 20 * (n + 2)
            answer = 30 * (n + 2)
            prompt = (
                f'Идеальный газ занимает объём V и имеет давление {pressure} кПа. '
                f'При нагревании абсолютная температура увеличилась в 3 раза, '
                f'а объём — в 2 раза. Найдите новое давление в кПа.'
            )
            explanation = (
                f'Из pV/T=const следует p₂=p₁·(T₂/T₁)·(V₁/V₂). '
                f'p₂={pressure}·3/2={answer} кПа.'
            )
        elif kind == 3:
            mass = n % 9 + 2
            specific_heat = 400
            delta_t = n % 8 + 5
            answer = mass * specific_heat * delta_t
            prompt = (
                f'Алюминиевое тело массой {mass} кг нагрели на {delta_t} °C. '
                f'Удельная теплоёмкость равна {specific_heat} Дж/(кг·°C). '
                f'Найдите количество теплоты в джоулях.'
            )
            explanation = (
                f'Q=cmΔT={specific_heat}·{mass}·{delta_t}={answer} Дж.'
            )
        elif kind == 4:
            r1, r2 = n % 8 + 2, n % 7 + 3
            voltage = (r1 + r2) * (n % 4 + 2)
            answer = voltage // (r1 + r2)
            prompt = (
                f'Резисторы {r1} Ом и {r2} Ом соединены последовательно и подключены '
                f'к источнику напряжения {voltage} В. Найдите силу тока в цепи в амперах.'
            )
            explanation = (
                f'При последовательном соединении R={r1}+{r2}={r1+r2} Ом. '
                f'По закону Ома I=U/R={voltage}/{r1+r2}={answer} А.'
            )
        elif kind == 5:
            m1 = n % 6 + 2
            m2 = m1
            v1, v2 = 2 * (n % 7 + 5), 2 * (n % 4 + 1)
            answer = (v1 - v2) // 2
            prompt = (
                f'Тележки массами {m1} кг и {m2} кг после сцепления движутся вместе. '
                f'До сцепления их скорости были {v1} м/с и {v2} м/с навстречу друг другу. '
                f'Найдите скорость после сцепления, считая направление первой тележки положительным.'
            )
            numerator = m1 * v1 - m2 * v2
            explanation = (
                f'Сохраняется импульс: (m₁+m₂)v=m₁v₁+m₂v₂. '
                f'v=({m1}·{v1}−{m2}·{v2})/({m1}+{m2})='
                f'{numerator}/{m1+m2}={answer} м/с.'
            )
        elif kind == 6:
            resistance = 2 * (n + 2)
            answer = resistance // 2
            prompt = (
                f'Два одинаковых резистора сопротивлением {resistance} Ом каждый '
                f'соединены параллельно. Найдите общее сопротивление в омах.'
            )
            explanation = (
                f'Для двух одинаковых параллельных резисторов '
                f'Rобщ=R/2={resistance}/2={answer} Ом.'
            )
        elif kind == 7:
            turns = 200 * (n + 1)
            delta_mwb = 5
            duration = 1
            answer = n + 1
            prompt = (
                f'В катушке из {turns} витков магнитный поток через каждый виток '
                f'изменился на {delta_mwb} мВб за {duration} с. Найдите модуль ЭДС '
                f'индукции в вольтах.'
            )
            explanation = (
                f'По закону Фарадея |ε|=N·|ΔΦ|/Δt. Переводим поток: '
                f'{delta_mwb} мВб=0,005 Вб. Тогда |ε|={turns}·0,005/{duration}='
                f'{answer} В.'
            )
        elif kind == 8:
            energy = n + 2
            wavelength = 1240 // energy
            answer = int(1240 / wavelength + 0.5)
            prompt = (
                f'Фотон имеет длину волны {wavelength} нм. Используйте '
                f'hc≈1240 эВ·нм. Найдите энергию фотона в электрон-вольтах, '
                f'округлив результат до целого.'
            )
            explanation = (
                f'E=hc/λ≈1240/{wavelength}≈{1240/wavelength:.2f} эВ. '
                f'После округления ответ: {answer} эВ.'
            )
        else:
            mass = n % 7 + 2
            velocity1 = n % 5 + 4
            velocity2 = velocity1 + 2 * (n % 4 + 1)
            answer = mass * (velocity2 - velocity1) // 2
            prompt = (
                f'Тело массой {mass} кг разгоняется с {velocity1} м/с до '
                f'{velocity2} м/с. Найдите изменение его кинетической энергии в джоулях.'
            )
            explanation = (
                f'ΔEₖ=m(v₂²−v₁²)/2={mass}·({velocity2}²−{velocity1}²)/2='
                f'{answer} Дж.'
            )
        yield _free_response(
            'physics', i, task_numbers[kind], sections[kind],
            prompt, answer, explanation,
            accepted=['не изменилось', 'не изменится', 'останется прежним', 'не поменяется']
            if kind == 0 else None,
        )


def _informatics_part2():
    task_numbers = [24, 24, 25, 25, 26, 26, 27, 27, 27, 24]
    sections = [
        'Обработка строк', 'Анализ последовательности', 'Циклы и суммы',
        'Рекурсия', 'Сортировка и поиск пары', 'Подсчёт пар',
        'Динамическое программирование', 'Поиск минимального пути',
        'Обработка данных', 'Алгоритм на массивах',
    ]
    for i in range(200):
        n, kind = divmod(i, len(task_numbers))
        if kind == 0:
            repeats = n + 3
            text = 'ABAC' * repeats
            answer = text.count('AB')
            prompt = (
                f'Дана строка, состоящая из {repeats} повторов фрагмента «ABAC». '
                f'Сколько раз в строке встречается подстрока «AB»?'
            )
            explanation = (
                f'В каждом фрагменте «ABAC» ровно одно вхождение «AB», '
                f'граница соседних фрагментов новых вхождений не создаёт. '
                f'Всего {repeats}·1={answer}.'
            )
        elif kind == 1:
            values = [((j * 7 + n * 3) % 19) - 4 for j in range(12 + n % 5)]
            answer = sum(value for value in values if value % 3 == 0)
            prompt = (
                f'Алгоритм просматривает последовательность {values}. '
                f'Найдите сумму всех элементов, кратных 3.'
            )
            selected = [value for value in values if value % 3 == 0]
            explanation = (
                f'Отбираем элементы, кратные 3: {selected}. Их сумма равна {answer}.'
            )
        elif kind == 2:
            limit = n % 25 + 15
            answer = sum(x * x for x in range(1, limit + 1) if x % 4 == 1)
            prompt = (
                f'Вычислите значение программы: s=0; для x от 1 до {limit} включительно '
                f'если x mod 4 = 1, то s=s+x². Что будет выведено?'
            )
            terms = [x for x in range(1, limit + 1) if x % 4 == 1]
            explanation = (
                f'В сумму входят числа {terms}. Складываем их квадраты: '
                f'{" + ".join(str(x*x) for x in terms)}={answer}.'
            )
        elif kind == 3:
            value = n + 4
            answer = math.factorial(value)
            prompt = (
                f'Рекурсивная функция задана так: F(1)=1, F(n)=n·F(n−1). '
                f'Найдите F({value}).'
            )
            explanation = (
                f'Функция вычисляет факториал: F({value})={value}·{value-1}·…·1={answer}.'
            )
        elif kind == 4:
            values = sorted({(j * 11 + n * 5) % 47 for j in range(10 + n % 5)})
            gap = n % 7 + 2
            pairs = [
                (values[a], values[b])
                for a in range(len(values))
                for b in range(a + 1, len(values))
                if values[b] - values[a] >= gap
            ]
            differences = [right - left for left, right in pairs]
            answer = min(differences) if differences else 0
            prompt = (
                f'В отсортированном списке {values} выберите два различных числа, '
                f'разность которых не меньше {gap}. Найдите наименьшую возможную разность. '
                f'Если подходящих пар нет, запишите 0.'
            )
            explanation = (
                f'Сравниваем разности соседних подходящих значений. Минимальная '
                f'разность, не меньшая {gap}, равна {answer}.'
            )
        elif kind == 5:
            values = [((j * 5 + n * 3) % 17) - 8 for j in range(8 + n % 6)]
            divisor = n % 8 + 3
            answer = sum(
                1 for a in range(len(values)) for b in range(a + 1, len(values))
                if (values[a] + values[b]) % divisor == 0
            )
            prompt = (
                f'Дан массив {values}. Сколько пар элементов с разными индексами '
                f'имеют сумму, кратную {divisor}? Каждая пара считается один раз.'
            )
            explanation = (
                f'Проверяем пары индексов i<j и условие '
                f'(a[i]+a[j]) mod {divisor}=0. Подходящих пар {answer}.'
            )
        elif kind == 6:
            rows, cols = n % 5 + 3, n % 4 + 4
            answer = math.comb(rows + cols, rows)
            prompt = (
                f'Исполнитель начинает в левом нижнем углу прямоугольной сетки и '
                f'может двигаться только вверх или вправо. До цели нужно пройти '
                f'{rows} шагов вверх и {cols} шагов вправо. Сколько разных маршрутов?'
            )
            explanation = (
                f'Всего шагов {rows}+{cols}={rows+cols}. Выбираем места для '
                f'{rows} шагов вверх: C({rows+cols},{rows})={answer}.'
            )
        elif kind == 7:
            size = 3
            base_matrix = [[1, 8, 2], [4, 1, 5], [7, 2, 1]]
            matrix = [[value + n for value in row] for row in base_matrix]
            dp = [[0] * size for _ in range(size)]
            dp[0][0] = matrix[0][0]
            for r in range(size):
                for c in range(size):
                    if r == 0 and c == 0:
                        continue
                    from_top = dp[r - 1][c] if r else float('inf')
                    from_left = dp[r][c - 1] if c else float('inf')
                    dp[r][c] = matrix[r][c] + min(from_top, from_left)
            answer = dp[-1][-1]
            matrix_text = '; '.join(' '.join(map(str, row)) for row in matrix)
            prompt = (
                f'В таблице 3×3 записаны числа по строкам: {matrix_text}. '
                f'Из верхней левой клетки нужно дойти до нижней правой, двигаясь '
                f'только вправо или вниз. Найдите минимальную сумму чисел на пути, '
                f'включая начальную и конечную клетки.'
            )
            explanation = (
                f'В каждой клетке записываем её число плюс меньшую из сумм, '
                f'пришедших сверху и слева. Таблица минимумов: '
                f'{"; ".join(" ".join(map(str, row)) for row in dp)}. '
                f'Минимальная сумма равна {answer}.'
            )
        elif kind == 8:
            values = [((j * 13 + n * 7) % 31) - 15 for j in range(12 + n % 5)]
            best = current = values[0]
            for value in values[1:]:
                current = max(value, current + value)
                best = max(best, current)
            answer = best
            prompt = (
                f'Найдите максимальную сумму непустого непрерывного фрагмента '
                f'последовательности {values}.'
            )
            explanation = (
                f'Для каждой позиции сравниваем отдельный элемент и сумму '
                f'предыдущего фрагмента с этим элементом (алгоритм Кадане). '
                f'Максимальная сумма фрагмента равна {answer}.'
            )
        else:
            limit = n % 30 + 20
            primes = [
                value for value in range(2, limit + 1)
                if all(value % d for d in range(2, math.isqrt(value) + 1))
            ]
            answer = len(primes)
            prompt = (
                f'Программа перебирает целые числа от 2 до {limit} включительно. '
                f'Сколько среди них простых чисел?'
            )
            explanation = (
                f'Простое число имеет ровно два положительных делителя. '
                f'В заданном диапазоне это числа {primes}; их {answer}.'
            )
        yield _free_response(
            'informatics', i, task_numbers[kind], sections[kind],
            prompt, answer, explanation,
        )


def build_part2_question_bank():
    """Return 600 auto-checked free-response tasks: 200 for each non-essay subject."""
    yield from _math_part2()
    yield from _physics_part2()
    yield from _informatics_part2()


def seed_part2_question_bank(conn):
    existing = {
        (row[0], row[1])
        for row in conn.execute('SELECT subject, text FROM questions')
    }
    rows = []
    for question in build_part2_question_bank():
        key = (question['subject'], question['text'])
        if key in existing:
            conn.execute(
                '''UPDATE questions SET part=?,task_number=?,section=?,difficulty=?,options=?,
                     correct_index=?,correct_answer=?,accepted_answers=?,answer_type=?,explanation=?,
                     wrong_explanations=? WHERE subject=? AND text=?''',
                (
                    question['part'], question['task_number'], question['section'],
                    question['difficulty'], question['options'], question['correct_index'],
                    question['correct_answer'], question['accepted_answers'],
                    question['answer_type'], question['explanation'],
                    question['wrong_explanations'], question['subject'], question['text'],
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
