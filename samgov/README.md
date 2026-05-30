# SAM.gov Tender Bot landing

Минимальный одностраничный сайт в бежевых тонах с большой кнопкой запуска Python-скрипта.

## Технологии

- HTML, CSS, JavaScript: простой интерфейс без сборщика и npm.
- Python `http.server`: локальный сервер и API-мост к скрипту.
- `subprocess`: запуск `bot/samgov_bot.py`.
- TXT download: сервер отдает файл `output/samgov_tenders.txt` как скачивание.

## Запуск

```powershell
cd C:\Users\anelt\Desktop\samgov
python server.py
```

Откройте:

```text
http://127.0.0.1:8000
```

Если порт занят:

```powershell
$env:PORT="8010"; python server.py
```

## Как подключить реальный SAM.gov скрипт

Замените код внутри `bot/samgov_bot.py`. Сервер передает скрипту путь для итогового TXT-файла первым аргументом:

```python
output_path = Path(sys.argv[1])
```

Главное условие: после успешного выполнения скрипт должен записать TXT-файл по этому пути и завершиться с кодом `0`.
