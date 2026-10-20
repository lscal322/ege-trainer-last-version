

Учебное веб-приложение на Python 3.12 и Flask. Архив содержит исходный код, шаблоны, статические файлы, тесты и учебные материалы.

Встроенная SQLite-копия очищена: в ней оставлены только задания, темы, разборы, методички, сочинения и опубликованные новости. Аккаунты, ответы учеников, сессии и результаты не включены

1. Установите Python 3.12 или новее.
2. Из корня архива установите зависимости: `python -m pip install -r flask/requirements.txt`.
3. В PowerShell задайте локальные переменные:

   ```powershell
   $env:SESSION_SECRET = ""
   $env:EGE_DB_DRIVER = "sqlite"
   python flask/app.py
   ```

   В Linux/macOS перед запуском: `export SESSION_SECRET="..."` и `export EGE_DB_DRIVER=sqlite`.
4. Откройте `http://127.0.0.1:5000/py/`.

Для тестов из корня архива: `python -m unittest discover -s flask/tests -v`.
