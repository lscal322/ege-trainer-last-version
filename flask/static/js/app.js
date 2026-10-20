document.addEventListener('DOMContentLoaded', function () {

  // Аккордеон теории
  document.querySelectorAll('.theory-section-header').forEach(function (header) {
    header.addEventListener('click', function () {
      var body = this.nextElementSibling;
      var chevron = this.querySelector('.chevron');
      var isOpen = body.classList.contains('open');
      document.querySelectorAll('.theory-section-body.open').forEach(function (b) { b.classList.remove('open'); });
      document.querySelectorAll('.chevron.open').forEach(function (c) { c.classList.remove('open'); });
      if (!isOpen) { body.classList.add('open'); if (chevron) chevron.classList.add('open'); }
    });
  });

  // Поле для рукописного решения
  document.querySelectorAll('[data-solution-pad]').forEach(function (pad) {
    var canvas = pad.querySelector('[data-solution-canvas]');
    if (!canvas) return;

    var ctx = canvas.getContext('2d');
    var questionId = pad.dataset.questionId;
    var storageKey = 'ege-solution-' + questionId;
    var statusEl = pad.querySelector('[data-draw-status]');
    var drawing = false;
    var erasing = false;
    var history = [];
    var maxHistory = 20;

    function setStatus(text) {
      if (statusEl) statusEl.textContent = text;
      if (text) {
        window.setTimeout(function () {
          if (statusEl && statusEl.textContent === text) statusEl.textContent = '';
        }, 1600);
      }
    }

    function save() {
      try { localStorage.setItem(storageKey, canvas.toDataURL('image/png')); } catch (e) {}
      setStatus('Сохранено');
    }

    function restore() {
      var saved = null;
      try { saved = localStorage.getItem(storageKey); } catch (e) {}
      if (!saved) return;
      var image = new Image();
      image.onload = function () { ctx.drawImage(image, 0, 0); };
      image.src = saved;
    }

    function snapshot() {
      history.push(ctx.getImageData(0, 0, canvas.width, canvas.height));
      if (history.length > maxHistory) history.shift();
    }

    function point(event) {
      var rect = canvas.getBoundingClientRect();
      return {
        x: (event.clientX - rect.left) * canvas.width / rect.width,
        y: (event.clientY - rect.top) * canvas.height / rect.height
      };
    }

    function start(event) {
      if (event.pointerType === 'mouse' && event.button !== 0) return;
      event.preventDefault();
      snapshot();
      drawing = true;
      canvas.setPointerCapture(event.pointerId);
      var p = point(event);
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.lineWidth = erasing ? 22 : 3;
      ctx.strokeStyle = erasing ? 'rgba(255,255,255,1)' : '#172554';
      ctx.globalCompositeOperation = 'source-over';
      ctx.lineTo(p.x + 0.01, p.y + 0.01);
      ctx.stroke();
    }

    function move(event) {
      if (!drawing) return;
      event.preventDefault();
      var p = point(event);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
    }

    function end(event) {
      if (!drawing) return;
      drawing = false;
      if (event && canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      save();
    }

    function setTool(name) {
      if (name === 'undo') {
        var previous = history.pop();
        if (previous) {
          ctx.putImageData(previous, 0, 0);
          save();
        }
        return;
      }
      if (name === 'clear') {
        snapshot();
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        save();
        return;
      }
      erasing = name === 'eraser';
      pad.querySelectorAll('[data-draw-action]').forEach(function (button) {
        button.classList.toggle('active', button.dataset.drawAction === name);
      });
    }

    canvas.addEventListener('pointerdown', start);
    canvas.addEventListener('pointermove', move);
    canvas.addEventListener('pointerup', end);
    canvas.addEventListener('pointercancel', end);
    pad.querySelectorAll('[data-draw-action]').forEach(function (button) {
      button.addEventListener('click', function () { setTool(button.dataset.drawAction); });
    });
    restore();
  });

  // Общая логика теста и адаптивного режима
  var quizForm = document.getElementById('quiz-form');
  if (quizForm) {
    var answers = {};
    var subject = quizForm.dataset.subject;
    var part = quizForm.dataset.part;
    var mode = quizForm.dataset.mode || 'quiz';
    var practiceId = quizForm.dataset.practiceId || null;
    var submitted = false;
    var submitting = false;
    var startTimes = {};
    var times = {};
    var allQids = [];
    quizForm.querySelectorAll('.quiz-question').forEach(function (b) {
      if (b.dataset.qidBlock) allQids.push(b.dataset.qidBlock);
    });

    function answeredCount() {
      return allQids.filter(function (qid) {
        return answers[qid] !== undefined && String(answers[qid]).trim() !== '';
      }).length;
    }

    function makeLine(text, color) {
      var span = document.createElement('span');
      span.style.display = 'block';
      span.style.marginTop = '4px';
      if (color) span.style.color = color;
      span.textContent = text;
      return span;
    }

    quizForm.querySelectorAll('.option').forEach(function (opt) {
      opt.addEventListener('click', function () {
        if (submitted || submitting) return;
        var qid = this.dataset.qid;
        if (!startTimes[qid]) startTimes[qid] = Date.now();
        answers[qid] = parseInt(this.dataset.idx, 10);
        times[qid] = Math.max(0, Math.round((Date.now() - startTimes[qid]) / 1000));
        var qBlock = this.closest('.quiz-question');
        qBlock.querySelectorAll('.option').forEach(function (o) { o.classList.remove('selected'); });
        this.classList.add('selected');
        var counter = document.getElementById('answered-count');
        if (counter) counter.textContent = answeredCount();
      });
    });
    quizForm.querySelectorAll('[data-answer-input]').forEach(function (input) {
      input.addEventListener('input', function () {
        if (submitted || submitting) return;
        var qid = this.dataset.qid;
        if (!startTimes[qid]) startTimes[qid] = Date.now();
        answers[qid] = this.value;
        times[qid] = Math.max(0, Math.round((Date.now() - startTimes[qid]) / 1000));
        var counter = document.getElementById('answered-count');
        if (counter) counter.textContent = answeredCount();
      });
    });

    var submitBtn = document.getElementById('submit-quiz');
    if (submitBtn) {
      var submitLabel = submitBtn.textContent;
      function resetSubmit(msg) {
        submitting = false;
        submitBtn.disabled = false;
        submitBtn.textContent = 'Повторить отправку';
        alert(msg);
      }
      submitBtn.addEventListener('click', function () {
        if (submitted || submitting) return;
        if (answeredCount() === 0) { alert('Ответьте хотя бы на один вопрос'); return; }
        submitting = true;
        submitBtn.disabled = true;
        submitBtn.textContent = 'Проверяем...';
        var payload = {};
        allQids.forEach(function (qid) {
          var input = quizForm.querySelector('[data-answer-input][data-qid="' + qid + '"]');
          payload[qid] = input ? (answers[qid] || '') : (answers[qid] !== undefined ? answers[qid] : -1);
        });

        var base = window.location.pathname.replace(/\/adaptive\/?$|\/quiz.*$/, '');
        fetch(base + '/quiz/submit', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ answers: payload, part: part, mode: mode, times: times, practice_id: practiceId, subject: subject })
        })
        .then(function (r) {
          return r.json().catch(function () { return { error: 'Некорректный ответ сервера (' + r.status + ')' }; })
            .then(function (d) { if (!r.ok && !d.error) d.error = 'Код ' + r.status; return d; });
        })
        .then(function (data) {
          if (data.error) { resetSubmit('Ошибка: ' + data.error); return; }
          submitted = true;
          submitting = false;
          var hadMistakes = false;
          (data.results || []).forEach(function (r) {
            var qBlock = quizForm.querySelector('[data-qid-block="' + r.id + '"]');
            if (!qBlock) return;
            var ai = answers[r.id];
            var answerInput = qBlock.querySelector('[data-answer-input]');
            if (answerInput) {
              answerInput.disabled = true;
              answerInput.classList.add(r.correct ? 'correct-answer' : 'wrong-answer');
            } else {
              qBlock.querySelectorAll('.option').forEach(function (opt) {
                var idx = parseInt(opt.dataset.idx, 10);
                opt.classList.add('disabled');
                if (idx === r.correct_index) opt.classList.add('correct-answer');
                else if (opt.classList.contains('selected') && !r.correct) opt.classList.add('wrong-answer');
              });
            }
            qBlock.classList.add(r.correct ? 'correct' : 'wrong');
            if (!r.correct) hadMistakes = true;
            var expEl = qBlock.querySelector('.explanation');
            if (expEl) {
              var wrongExpl = {};
              try { wrongExpl = JSON.parse(expEl.dataset.wrongExpl || '{}') || {}; } catch (e) {}
              var we = r.wrong_explanation || (ai !== undefined ? wrongExpl[String(ai)] : '');
              expEl.textContent = '';
              if (r.explanation) expEl.appendChild(document.createTextNode(String(r.explanation)));
              if (!r.correct && ai === undefined) expEl.appendChild(makeLine('Нет ответа', '#dc2626'));
              if (!r.correct && ai !== undefined && we) expEl.appendChild(makeLine('Ваш ответ: ' + we, '#dc2626'));
              if (!r.correct && r.correct_option_text) expEl.appendChild(makeLine('Правильно: ' + r.correct_option_text, '#16a34a'));
              if (!r.correct && r.answer_type === 'short') {
                if (r.submitted_answer_text) expEl.appendChild(makeLine('Ваш ответ: ' + r.submitted_answer_text, '#dc2626'));
                expEl.appendChild(makeLine('Правильный ответ: ' + r.correct_answer_text, '#16a34a'));
              }
              if (expEl.childNodes.length) expEl.style.display = 'block';
            }
          });
          var resultDiv = document.getElementById('quiz-result');
          if (resultDiv) {
            var scoreEl = resultDiv.querySelector('.result-score');
            scoreEl.textContent = data.score + '%';
            scoreEl.className = 'result-score ' + (data.score >= 80 ? 'great' : data.score >= 50 ? 'ok' : 'poor');
            resultDiv.querySelector('.result-correct').textContent = data.correct + ' из ' + data.total;
            resultDiv.querySelector('.result-xp').textContent = '+' + (data.xp_gain || 0) + ' XP';
            var notice = resultDiv.querySelector('.result-mistakes-notice');
            if (notice && hadMistakes) notice.style.display = 'block';
            resultDiv.style.display = 'block';
            resultDiv.scrollIntoView({ behavior: 'smooth' });
          }
          submitBtn.textContent = submitLabel;
          submitBtn.style.display = 'none';
        })
        .catch(function () { resetSubmit('Ошибка соединения. Проверьте интернет и нажмите «Повторить отправку».'); });
      });
    }

    // Учёт времени ответа на задания
    if ('IntersectionObserver' in window) {
      var obs = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          var qid = e.target.dataset.qidBlock;
          if (e.isIntersecting && qid && !startTimes[qid]) startTimes[qid] = Date.now();
        });
      });
      quizForm.querySelectorAll('.quiz-question').forEach(function (block) { obs.observe(block); });
    }
  }

  // Переключение вкладок
  document.querySelectorAll('[data-tab]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var target = this.dataset.tab;
      document.querySelectorAll('[data-tab]').forEach(function (b) { b.classList.remove('active'); });
      this.classList.add('active');
      document.querySelectorAll('[data-tab-content]').forEach(function (c) {
        c.style.display = c.dataset.tabContent === target ? '' : 'none';
      });
    });
  });

  var tabSwitchBtns = document.querySelectorAll('.tab-switch-btn');
  tabSwitchBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var target = this.dataset.target;
      tabSwitchBtns.forEach(function (b) { b.classList.remove('active'); });
      this.classList.add('active');
      document.querySelectorAll('.tab-panel').forEach(function (p) {
        p.style.display = p.id === target ? '' : 'none';
      });
    });
  });

  var firstPanel = document.querySelector('.tab-panel');
  if (firstPanel) {
    document.querySelectorAll('.tab-panel').forEach(function (p, i) {
      if (i > 0) p.style.display = 'none';
    });
  }
});
