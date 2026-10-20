(function () {
  var root = document.documentElement;
  var buttons = document.querySelectorAll('[data-theme-toggle]');

  function applyTheme(theme, persist) {
    root.setAttribute('data-theme', theme);
    if (persist) {
      try { localStorage.setItem('ege-trainer-theme', theme); } catch (e) {}
    }
    buttons.forEach(function (button) {
      var isDark = theme === 'dark';
      var icon = button.querySelector('.theme-toggle-icon');
      var label = button.querySelector('.theme-toggle-label');
      if (icon) icon.textContent = isDark ? '☀' : '☾';
      if (label) label.textContent = isDark ? 'Светлая тема' : 'Тёмная тема';
      button.setAttribute('aria-label', isDark ? 'Включить светлую тему' : 'Включить тёмную тему');
      button.setAttribute('aria-pressed', isDark ? 'true' : 'false');
      button.setAttribute('title', isDark ? 'Включить светлую тему' : 'Включить тёмную тему');
    });
  }

  applyTheme(root.getAttribute('data-theme') || 'light', false);
  buttons.forEach(function (button) {
    button.addEventListener('click', function () {
      applyTheme(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark', true);
    });
  });
})();
