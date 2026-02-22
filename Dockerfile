# Базовый образ от Microsoft с Python 3.11 и Playwright 1.40.0
FROM mcr.microsoft.com/playwright:python-3.11-1.40.0

# Устанавливаем рабочую папку внутри контейнера
WORKDIR /app

# Копируем файл с зависимостями Python
COPY requirements.txt .

# Устанавливаем Python-пакеты (браузеры уже есть в образе, поэтому playwright install НЕ НУЖЕН!)
RUN pip install --no-cache-dir -r requirements.txt

# Копируем ВСЕ файлы бота в контейнер
COPY . .

# Команда для запуска бота
CMD ["python", "bot.py"]