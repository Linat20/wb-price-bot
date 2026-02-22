# Официальный образ Playwright с Python 3.11
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Устанавливаем рабочую папку
WORKDIR /app

# Копируем файл с зависимостями
COPY requirements.txt .

# Устанавливаем Python-пакеты (браузеры уже есть в образе)
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код бота
COPY . .

# Команда для запуска
CMD ["python", "bot.py"]