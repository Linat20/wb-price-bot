# -*- coding: utf-8 -*-
import asyncio
import random
import re
import json
import requests
import sqlite3
import datetime
import random
from decimal import Decimal, ROUND_FLOOR
from loguru import logger
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


TOKEN = "8546428848:AAHrGEdOQWDAUPWwIGajy3qfUaZbZ0VnwuQ"
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)




# --- Функция для конвертации времени в UTC+5 ---
def to_local_time(utc_time_str):
    """Конвертирует время из UTC в UTC+5"""
    try:
        utc_time = datetime.datetime.strptime(utc_time_str, '%Y-%m-%d %H:%M:%S')
        local_time = utc_time + datetime.timedelta(hours=5)
        return local_time
    except:
        return datetime.datetime.now()




# --- Инициализация базы данных ---
def init_db():
    conn = sqlite3.connect('price_tracking.db')
    cursor = conn.cursor()
    
    # Таблица отслеживаемых товаров
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tracked_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            nm_id TEXT NOT NULL,
            url TEXT NOT NULL,
            last_price DECIMAL(10,2) NOT NULL,
            last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            UNIQUE(user_id, nm_id)
        )
    ''')
    
    # Таблица истории цен
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nm_id TEXT NOT NULL,
            price DECIMAL(10,2) NOT NULL,
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица для целевых цен
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS target_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            nm_id TEXT NOT NULL,
            target_price DECIMAL(10,2) NOT NULL,
            is_achieved BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, nm_id)
        )
    ''')
    
    conn.commit()
    conn.close()




# --- Функция для обновления структуры БД ---
def update_db_for_availability():
    """Обновляет структуру базы данных для отслеживания наличия товара"""
    try:
        conn = sqlite3.connect('price_tracking.db')
        cursor = conn.cursor()
        
        # Добавляем колонку для статуса наличия товара
        try:
            cursor.execute("ALTER TABLE tracked_prices ADD COLUMN is_available BOOLEAN DEFAULT 1")
            logger.info("✅ Добавлена колонка is_available в таблицу tracked_prices")
        except sqlite3.OperationalError:
            logger.info("Колонка is_available уже существует")
        
        # Добавляем колонку для уведомлений о появлении
        try:
            cursor.execute("ALTER TABLE tracked_prices ADD COLUMN notify_on_appear BOOLEAN DEFAULT 0")
            logger.info("✅ Добавлена колонка notify_on_appear в таблицу tracked_prices")
        except sqlite3.OperationalError:
            logger.info("Колонка notify_on_appear уже существует")
        
        conn.commit()
        conn.close()
        logger.info("✅ Обновление структуры БД завершено")
    except Exception as e:
        logger.error(f"Ошибка при обновлении БД: {e}")




# Инициализация БД
init_db()
update_db_for_availability()




# --- WB Wallet URLs ---
DEFAULT_PAYMENT_URL = "https://static-basket-01.wbbasket.ru/vol1/global-payment/default-payment.json"




# --- Получение скидки для кошелька ---
def get_wallet_discount() -> dict:
    """Возвращает словарь со скидками для разных типов кошелька"""
    try:
        resp = requests.get(DEFAULT_PAYMENT_URL, timeout=5)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return {"anon": 0, "auth": 0}


    if payload.get("state") != 0:
        return {"anon": 0, "auth": 0}


    discounts = {"anon": 0, "auth": 0}
    
    for item in payload.get("data", []):
        if item.get("is_active"):
            if item.get("wc_type") == "Незалогиненный кошелёк":
                try:
                    discounts["anon"] = Decimal(item["discount_value"])
                except:
                    pass
            elif item.get("wc_type") == "ВБ Клуб Аноним кошелёк":
                try:
                    discounts["auth"] = Decimal(item["discount_value"])
                except:
                    pass
    
    logger.info(f"Получены скидки: незалогиненный - {discounts['anon']}%, ВБ Клуб - {discounts['auth']}%")
    return discounts




def calc_price_with_wallet(price: Decimal, discount_percent: Decimal) -> int:
    """Рассчитывает цену с учетом скидки"""
    if discount_percent <= 0:
        return int(price)
    
    discounted_price = (
        price * (Decimal("100") - discount_percent) / Decimal("100")
    ).quantize(Decimal("1"), rounding=ROUND_FLOOR)
    
    return int(discounted_price)




# --- Извлечение NM ID из ссылки ---
def get_nm_id(url: str):
    patterns = [
        r'/catalog/(\d+)',
        r'/product/(\d+)',
        r'/products/(\d+)',
        r'/(\d{5,})\.html',
        r'nm=(\d+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None




async def get_product_price_with_availability(url: str):
    """Получает цену product (со скидкой продавца) из API Wildberries"""
    nm_id = get_nm_id(url)
    if not nm_id:
        logger.error(f"❌ Не удалось извлечь артикул из URL: {url}")
        return None, None, False


    # Ваши куки и заголовки (оставляем без изменений)
    cookies = {
        '_wbauid': '9117851341767702431',
        'x_wbaas_token': '1.1000.d1627711296f44628e9eca5a71ec989a.MHwxOTMuMTQzLjY3LjE1N3xNb3ppbGxhLzUuMCAoV2luZG93cyBOVCAxMC4wOyBXaW42NDsgeDY0KSBBcHBsZVdlYktpdC81MzcuMzYgKEtIVE1MLCBsaWtlIEdlY2tvKSBDaHJvbWUvMTQ0LjAuMC4wIFNhZmFyaS81MzcuMzZ8MTc3Mjc4NDQ3NXxyZXVzYWJsZXwyfGV5Sm9ZWE5vSWpvaUluMD18MHwzfDE3NzIxNzk2NzV8MQ==.MEUCIAZ3de8sle97/Qv63oxkMw4cKhXnp/0jH0C5g+VoqUiqAiEAmUkVA1jsg7Avnx+BzXZZFs3YO0lAJsB1f6AQy4MJNoA=',
        '_cp': '1',
        '_wbauid': '6169040771771582040',
        'external-locale': 'ru',
        'wbx-validation-key': 'aaafd817-319b-44d4-a99f-0dbffb64e712',
        '__zzatw-wb': 'MDA0dC0yYBwREFsKEH49WgsbSl1pCENQGC9LXz1uLWEPJ3wjYnwgGWsvC1RDMmUIPkBNOTM5NGZwVydgTmAgSV5OCC0hF3xyH0FLVCNyM3dlaXceViUTFmcPRyJObXOuxw==',
        'x-supplier-id-external': '',
        'cfidsw-wb': 'GmKfgRiCnWRvUrJLpKEA5Bk8HGttak7hMxVeeXCqVkXV4Gol8FEKUaK4gEySLGWsqk8kuuirv+Zr+fbt9UEPf3fi2nUSbouRjRJJ+sPYgOX3Me4GBsh0DvuNGBzaj5Dc5hJcScKniqQYXgJbRKhTNMQdVs8jn+4whIkz',
        'routeb': '1771692710.778.1977.438487|fc3b37d75a18d923fd0e9c7589719997',
    }


    headers = {
        'accept': '*/*',
        'accept-language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'authorization': 'Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE3NzE3NTM2NDIsInVzZXIiOiIzMTAzMjc1NDYiLCJzaGFyZF9rZXkiOiIxMiIsImNsaWVudF9pZCI6IndiIiwic2Vzc2lvbl9pZCI6ImE1MzUzZWJjZjE3NDQ5ZjBiODA0ZGRkMThmZGY3YjQ1IiwicGhvbmUiOiIxbVdvSHMyV2llKzNDSjBHZXcvM2NBPT0iLCJ2YWxpZGF0aW9uX2tleSI6IjdlMWQwZWNmNDc3NTJjNzFkMWI2NzkxMDMzNDY4NTlhOTIzODQ0NTY2M2M2NzczNGUyNjA5ZGMxZGZjOWUwZjciLCJ1c2VyX3JlZ2lzdHJhdGlvbl9kdCI6MTc3MTU4MTA2NCwidmVyc2lvbiI6Mn0.Zc9rikmAHeFPB31k_UgXpzrJOhpE38jJ1ZsIdhVaMhWfM8kXIQ2hSeCTmVrDJUcZ-OuiHbw48uDhIoFZwqSYQxU1syvhnGSh35q7kDAsRv_0Lwkbo0nZlRdPpbmbCO0LSucYgZep3zQBF2h_xC1I_9iDNw5qc_kTKUj7PoORx2b460pwm65RNONDv8yF6H_OPYlYz399jhEGwsTbcbWJgRkYR3Gt4SGm31X2NQxbEFDIrmM_Mzka8jeArSTJnZSmRcXYhpICaCLYQvhpKxJ4rGE4Y_xZORJCrRYwqRYqL7z-H0287N5MDOV5AfBPmlgHQvDu80dLUiwwcFjqBV6lsw',
        'deviceid': 'site_0a6c99d05f114a0d942ff4748e351610',
        'priority': 'u=1, i',
        'referer': 'https://www.wildberries.ru/catalog/471955155/detail.aspx?targetUrl=MI',
        'sec-ch-ua': '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
        'x-requested-with': 'XMLHttpRequest',
        'x-spa-version': '13.24.5',
    }


    # Формируем URL для одного товара
    api_url = f"https://www.wildberries.ru/__internal/card/cards/v4/detail?appType=1&curr=rub&dest=-284542&spp=30&hide_vflags=4294967296&ab_testing=false&lang=ru&nm={nm_id}"


    try:
        logger.info(f"🔍 Запрос к API: {api_url}")
        
        # Используем session для сохранения кук
        session = requests.Session()
        session.cookies.update(cookies)
        session.headers.update(headers)
        
        response = await asyncio.to_thread(session.get, api_url, timeout=10)
        
        logger.info(f"📊 Статус ответа: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"❌ Ошибка HTTP {response.status_code}")
            if response.text:
                logger.debug(f"Ответ: {response.text[:200]}")
            return None, nm_id, False
            
        data = response.json()
        
        # Проверяем наличие товара
        if not data.get("products") or len(data["products"]) == 0:
            logger.info(f"❌ Товар {nm_id} не найден")
            return None, nm_id, False
        
        product = data["products"][0]
        logger.info(f"📦 Найден товар: {product.get('name', 'Unknown')}")
        
        # Извлекаем ТОЛЬКО цену product (скидка продавца)
        product_price = None
        
        if "sizes" in product and len(product["sizes"]) > 0:
            size = product["sizes"][0]
            if "price" in size:
                price_data = size["price"]
                logger.info(f"💰 Данные о цене: {price_data}")
                
                # Нам нужна только цена 'product' (в копейках)
                if "product" in price_data and price_data["product"] > 0:
                    # Конвертируем из копеек в рубли
                    product_price = Decimal(price_data["product"]) / Decimal(100)
                    logger.info(f"✅ Найдена цена product (со скидкой продавца): {product_price} ₽")
                else:
                    logger.warning(f"⚠️ Цена product не найдена в ответе")
        
        if product_price and product_price > 0:
            # Возвращаем ТОЛЬКО цену product
            return product_price, nm_id, True
        else:
            logger.warning(f"⚠️ Товар {nm_id} есть, но цена не найдена")
            return None, nm_id, True
            
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке товара {nm_id}: {type(e).__name__}: {e}")
        return None, nm_id, False






# --- Функции для работы с БД ---
def add_to_tracking(user_id: int, nm_id: str, url: str, price: Decimal, is_available: bool = True):
    conn = sqlite3.connect('price_tracking.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO tracked_prices (user_id, nm_id, url, last_price, is_available, last_checked)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ''', (user_id, nm_id, url, float(price), 1 if is_available else 0))
    
    if is_available and price > 0:
        cursor.execute('''
            INSERT INTO price_history (nm_id, price)
            VALUES (?, ?)
        ''', (nm_id, float(price)))
    
    conn.commit()
    conn.close()




def remove_from_tracking(user_id: int, nm_id: str):
    conn = sqlite3.connect('price_tracking.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE tracked_prices 
        SET is_active = 0 
        WHERE user_id = ? AND nm_id = ?
    ''', (user_id, nm_id))
    
    conn.commit()
    conn.close()




def get_user_tracked_items(user_id: int):
    conn = sqlite3.connect('price_tracking.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT nm_id, url, last_price, last_checked 
        FROM tracked_prices 
        WHERE user_id = ? AND is_active = 1
        ORDER BY last_checked DESC
    ''', (user_id,))
    
    items = cursor.fetchall()
    conn.close()
    return items




def get_all_tracked_items():
    conn = sqlite3.connect('price_tracking.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT user_id, nm_id, url, last_price 
        FROM tracked_prices 
        WHERE is_active = 1 AND is_available = 1
    ''')
    
    items = cursor.fetchall()
    conn.close()
    return items




def update_price(nm_id: str, new_price: Decimal):
    conn = sqlite3.connect('price_tracking.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE tracked_prices 
        SET last_price = ?, last_checked = CURRENT_TIMESTAMP 
        WHERE nm_id = ? AND is_active = 1
    ''', (float(new_price), nm_id))
    
    cursor.execute('''
        INSERT INTO price_history (nm_id, price)
        VALUES (?, ?)
    ''', (nm_id, float(new_price)))
    
    conn.commit()
    conn.close()




def get_price_history(nm_id: str, days: int = 7):
    conn = sqlite3.connect('price_tracking.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT price, checked_at 
        FROM price_history 
        WHERE nm_id = ? AND checked_at >= datetime('now', ?)
        ORDER BY checked_at DESC
    ''', (nm_id, f'-{days} days'))
    
    history = cursor.fetchall()
    conn.close()
    return history




def update_product_availability(nm_id: str, is_available: bool):
    """Обновляет статус наличия товара"""
    conn = sqlite3.connect('price_tracking.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE tracked_prices 
        SET is_available = ?
        WHERE nm_id = ? AND is_active = 1
    ''', (1 if is_available else 0, nm_id))
    
    conn.commit()
    conn.close()




def set_notify_on_appear(user_id: int, nm_id: str, notify: bool = True):
    """Включает/выключает уведомления о появлении товара"""
    conn = sqlite3.connect('price_tracking.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE tracked_prices 
        SET notify_on_appear = ?
        WHERE user_id = ? AND nm_id = ? AND is_active = 1
    ''', (1 if notify else 0, user_id, nm_id))
    
    conn.commit()
    conn.close()




def get_products_to_notify():
    """Получает товары, за которыми нужно следить (нет в наличии)"""
    conn = sqlite3.connect('price_tracking.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT user_id, nm_id, url, last_price
        FROM tracked_prices 
        WHERE is_active = 1 AND is_available = 0 AND notify_on_appear = 1
    ''')
    
    items = cursor.fetchall()
    conn.close()
    return items




# --- Функции для работы с целевыми ценами ---
def set_target_price(user_id: int, nm_id: str, target_price: Decimal):
    conn = sqlite3.connect('price_tracking.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO target_prices (user_id, nm_id, target_price, is_achieved)
        VALUES (?, ?, ?, 0)
    ''', (user_id, nm_id, float(target_price)))
    
    conn.commit()
    conn.close()




def get_user_targets(user_id: int):
    conn = sqlite3.connect('price_tracking.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT tp.nm_id, tp.target_price, tp.is_achieved,
               tp.created_at, tp2.url, tp2.last_price
        FROM target_prices tp
        JOIN tracked_prices tp2 ON tp.user_id = tp2.user_id AND tp.nm_id = tp2.nm_id
        WHERE tp.user_id = ? AND tp2.is_active = 1
        ORDER BY tp.is_achieved, tp.created_at DESC
    ''', (user_id,))
    
    targets = cursor.fetchall()
    conn.close()
    return targets




def mark_target_achieved(user_id: int, nm_id: str):
    conn = sqlite3.connect('price_tracking.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE target_prices 
        SET is_achieved = 1 
        WHERE user_id = ? AND nm_id = ?
    ''', (user_id, nm_id))
    
    conn.commit()
    conn.close()




def remove_target(user_id: int, nm_id: str):
    conn = sqlite3.connect('price_tracking.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        DELETE FROM target_prices 
        WHERE user_id = ? AND nm_id = ?
    ''', (user_id, nm_id))
    
    conn.commit()
    conn.close()




# --- Функция проверки цен (обновленная) ---
async def check_prices():
    discounts = get_wallet_discount()
    
    while True:
        try:
            # Проверяем обычные товары (в наличии)
            tracked_items = get_all_tracked_items()
            total_items = len(tracked_items)
            
            logger.info("=" * 50)
            logger.info(f"🔄 ЗАПУСК ПРОВЕРКИ ЦЕН: {total_items} товаров в наличии")
            logger.info("=" * 50)
            
            for user_id, nm_id, url, last_price in tracked_items:
                try:
                    logger.info(f"👤 Пользователь {user_id} | 📦 Товар {nm_id}")
                    
                    # Используем новую функцию с проверкой наличия
                    current_price, _, is_available = await get_product_price_with_availability(url)
                    
                    # Обновляем статус наличия
                    update_product_availability(nm_id, is_available)
                    
                    if not is_available or current_price is None:
                        logger.info(f"   ℹ️ Товар {nm_id} отсутствует в наличии")
                        continue
                    
                    current_price_decimal = Decimal(str(current_price))
                    last_price_decimal = Decimal(str(last_price))
                    
                    logger.info(f"   💰 Цена: {current_price_decimal} ₽")
                    
                    if current_price_decimal != last_price_decimal:
                        update_price(nm_id, current_price_decimal)
                        
                        price_with_auth = calc_price_with_wallet(current_price_decimal, discounts["auth"])
                        
                        if current_price_decimal < last_price_decimal:
                            change_emoji = "📉"
                            change_text = "снизилась"
                            price_diff = last_price_decimal - current_price_decimal
                        else:
                            change_emoji = "📈"
                            change_text = "повысилась"
                            price_diff = current_price_decimal - last_price_decimal
                        
                        message = (
                            f"{change_emoji} <b>Цена товара {change_text}!</b>\n\n"
                            f"🔗 <a href='{url}'>Ссылка на товар</a>\n\n"
                            f"💰 <b>Цена на WB:</b> {current_price_decimal} ₽\n"
                            f"📉 <b>Изменение:</b> {price_diff} ₽\n"
                            f"💎 <b>С ВБ Кошельком:</b> {price_with_auth} ₽"
                        )
                        
                        await bot.send_message(
                            user_id,
                            message,
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                        
                        logger.info(f"   📢 Уведомление об изменении цены отправлено")
                    
                    # Проверяем целевые цены
                    price_with_auth = calc_price_with_wallet(current_price_decimal, discounts["auth"])
                    check_target_prices(user_id, nm_id, url, price_with_auth)
                    
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    logger.error(f"   ❌ Ошибка: {e}")
                    continue
            
            # Проверяем товары, которых нет в наличии (ждут появления)
            waiting_items = get_products_to_notify()
            if waiting_items:
                logger.info(f"🔍 Проверка {len(waiting_items)} товаров на появление...")
                
                for user_id, nm_id, url, last_price in waiting_items:
                    try:
                        price, _, is_available = await get_product_price_with_availability(url)
                        
                        if is_available and price is not None:
                            # Товар появился!
                            
                            # Обновляем статус
                            update_product_availability(nm_id, True)
                            update_price(nm_id, price)
                            
                            price_with_auth = calc_price_with_wallet(price, discounts["auth"])
                            
                            message = (
                                f"🎉 <b>ТОВАР СНОВА В НАЛИЧИИ!</b>\n\n"
                                f"📦 <b>Товар:</b> <a href='{url}'>Артикул {nm_id}</a>\n\n"
                                f"💰 <b>Цена:</b> {price} ₽\n"
                                f"💎 <b>С ВБ Кошельком:</b> {price_with_auth} ₽\n\n"
                                f"✅ Скорее покупайте, пока не разобрали!"
                            )
                            
                            await bot.send_message(
                                user_id,
                                message,
                                parse_mode="HTML",
                                disable_web_page_preview=True
                            )
                            
                            logger.info(f"   📢 Уведомление о появлении отправлено пользователю {user_id}")
                            
                            await asyncio.sleep(1)
                            
                    except Exception as e:
                        logger.error(f"Ошибка при проверке наличия {nm_id}: {e}")
                        continue
            
            logger.info("=" * 50)
            logger.info("✅ ПРОВЕРКА ЗАВЕРШЕНА. Следующая через 30 минут")
            logger.info("=" * 50)
            await asyncio.sleep(1800)
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}")
            await asyncio.sleep(300)




def check_target_prices(user_id: int, nm_id: str, url: str, current_price_with_auth: Decimal):
    """Проверка достижения целевых цен"""
    try:
        conn = sqlite3.connect('price_tracking.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT target_price 
            FROM target_prices 
            WHERE user_id = ? AND nm_id = ? AND is_achieved = 0
        ''', (user_id, nm_id))
        
        targets = cursor.fetchall()
        conn.close()
        
        for (target_price,) in targets:
            target_decimal = Decimal(str(target_price))
            
            if current_price_with_auth <= target_decimal:
                mark_target_achieved(user_id, nm_id)
                
                asyncio.create_task(send_target_notification(
                    user_id, nm_id, url, current_price_with_auth, target_decimal
                ))
    except Exception as e:
        logger.error(f"Ошибка при проверке целевых цен: {e}")




async def send_target_notification(user_id: int, nm_id: str, url: str, 
                                   current_price: Decimal, target_price: Decimal):
    """Отправка уведомления о достижении целевой цены"""
    try:
        current_time = datetime.datetime.now() + datetime.timedelta(hours=5)
        time_str = current_time.strftime('%d.%m.%Y %H:%M')
        
        message = (
            f"🎯 <b>ЦЕЛЕВАЯ ЦЕНА ДОСТИГНУТА!</b>\n\n"
            f"📦 <b>Товар:</b> <a href='{url}'>Артикул {nm_id}</a>\n\n"
            f"💰 <b>Цена с ВБ Кошельком:</b> {current_price} ₽\n"
            f"🎯 <b>Ваша цель была:</b> {target_price} ₽\n"
            f"🕐 <b>Достигнута:</b> {time_str} (UTC+5)\n\n"
            f"✅ Самое время покупать!"
        )
        
        await bot.send_message(
            user_id,
            message,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления: {e}")




# --- Обработчики команд ---
@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    discounts = get_wallet_discount()
    user_name = message.from_user.first_name
    
    welcome_text = (
        f"👋 <b>Привет, {user_name}!</b>\n\n"
        f"🛍️ <b>Добро пожаловать в бот отслеживания цен Wildberries!</b>\n\n"
        f"📊 <b>Основная цена, на которую вам нужно смотреть - Цена с ВБ кошельком.</b>\n\n"
        
        f"🎯 <b>Что я умею:</b>\n"
        f"✅ Отслеживать цены на любые товары Wildberries\n"
        f"✅ Уведомлять об изменении цен\n"
        f"✅ Оповещать при достижении желаемой цены\n"
        f"✅ Сообщать, когда товар снова появится в наличии\n"
        f"✅ Показывать историю изменения цен\n\n"
        
        f"📌 <b>Как начать:</b>\n"
        f"1️⃣ Просто отправь мне ссылку на товар\n"
        f"2️⃣ Нажми кнопку «Отслеживать»\n"
        f"3️⃣ Я буду следить за ценой и пришлю уведомление!\n\n"
        
        f"🔍 <b>Пример:</b>\n"
        f"`https://www.wildberries.ru/catalog/12345678/detail.aspx`\n\n"
        
        f"ℹ️ <b>Доступные команды:</b>\n"
        f"• /track [ссылка] - добавить товар\n"
        f"• /mytrack - мои товары\n"
        f"• /history [номер] - история цены\n"
        f"• /target [номер] [цена] - установить цель\n"
        f"• /mytargets - мои цели\n"
        f"• /notify [номер] - уведомлять о появлении\n"
        f"• /help - подробная инструкция"
    )
    await message.answer(welcome_text, parse_mode="HTML")




@dp.message_handler(commands=['help'])
async def help_command(message: types.Message):
    discounts = get_wallet_discount()
    
    help_text = (
        "🆘 <b>Центр помощи</b>\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 <b>КАК ПОЛЬЗОВАТЬСЯ БОТОМ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "📌 <b>ШАГ 1: Найти товар</b>\n"
        "• Открой Wildberries\n"
        "• Найди нужный товар\n"
        "• Скопируй ссылку из адресной строки или из приложения\n\n"
        
        "📌 <b>ШАГ 2: Отправить ссылку</b>\n"
        "• Просто вставь ссылку в чат\n"
        "• Бот покажет текущую цену\n"
        "• Нажми кнопку «Отслеживать»\n\n"
        
        "📌 <b>ШАГ 3: Дополнительные настройки</b>\n"
        "• /target - установить желаемую цену\n"
        "• /notify - включить уведомление о появлении\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 <b>ВСЕ КОМАНДЫ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "🆕 <b>/track [ссылка]</b>\n"
        "➜ Начать отслеживание товара\n"
        "📌 <i>Пример:</i> /track https://www.wildberries.ru/catalog/12345678/detail.aspx\n\n"
        
        "📋 <b>/mytrack</b>\n"
        "➜ Показать все отслеживаемые товары\n"
        "📌 <i>Пример:</i> /mytrack\n"
        "   Бот покажет список с номерами:\n"
        "   1. ✅ Товар 12345678 - 1500 ₽\n"
        "   2. ❌ Товар 87654321 - нет в наличии 🔔\n\n"
        
        "🗑️ <b>/untrack [номер]</b>\n"
        "➜ Удалить товар из отслеживания\n"
        "📌 <i>Пример:</i> /untrack 1\n\n"
        
        "📊 <b>/history [номер]</b>\n"
        "➜ Показать историю изменения цены\n"
        "📌 <i>Пример:</i> /history 1\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 <b>ЦЕЛЕВЫЕ ЦЕНЫ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "🎯 <b>/target [номер] [цена]</b>\n"
        "➜ Установить желаемую цену (для цены с ВБ Кошельком)\n"
        "📌 <i>Пример:</i> /target 1 5000\n\n"
        
        "🎯 <b>/mytargets</b>\n"
        "➜ Показать все установленные цели\n\n"
        
        "🗑️ <b>/removetarget [номер]</b>\n"
        "➜ Удалить целевую цену\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔔 <b>УВЕДОМЛЕНИЯ О ПОЯВЛЕНИИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "🔔 <b>/notify [номер]</b>\n"
        "➜ Включить уведомления, когда товар появится в наличии\n"
        "📌 <i>Пример:</i> /notify 1\n\n"
        
        "🔕 <b>/stopnotify [номер]</b>\n"
        "➜ Отключить уведомления о появлении\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <b>ПОЛЕЗНЫЕ СОВЕТЫ (скидка: {discounts['auth']}%)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "✅ <b>Как получить максимальную выгоду:</b>\n"
        f"• Все цены показываются с учетом ВБ Кошелька ({discounts['auth']}%)\n"
        "• Устанавливайте цели чуть ниже текущей цены\n"
        "• Включайте уведомления для отсутствующих товаров\n\n"
        
        "⏱️ <b>Как часто проверяются цены:</b>\n"
        "• Бот проверяет цены КАЖДЫЕ 30 МИНУТ\n"
        "• При изменении цены вы получите уведомление\n"
        "• При появлении товара - тоже уведомление\n\n"
        
        "🌍 <b>Часовой пояс:</b> UTC+5\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎉 <b>Удачных покупок!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    await message.answer(help_text, parse_mode="HTML")




@dp.message_handler(commands=['track'])
async def track_command(message: types.Message):
    args = message.get_args()
    if not args:
        await message.answer("❌ Укажите ссылку на товар\nПример: /track https://www.wildberries.ru/catalog/12345678/detail.aspx")
        return
    
    url = args.strip()
    if not re.search(r'wildberries\.ru', url):
        await message.answer("❌ Ссылка должна быть на Wildberries")
        return
    
    await message.answer("🔍 Получаю информацию...")
    
    try:
        price, nm_id, is_available = await get_product_price_with_availability(url)
        discounts = get_wallet_discount()
        
        if not is_available or price is None:
            # Товара нет в наличии, но добавляем в отслеживание
            add_to_tracking(message.from_user.id, nm_id, url, Decimal('0'), False)
            
            await message.answer(
                f"ℹ️ <b>Товар добавлен в список ожидания</b>\n\n"
                f"📦 Артикул: {nm_id}\n"
                f"❌ Товар временно отсутствует в наличии\n\n"
                f"🔔 Используйте /notify {len(get_user_tracked_items(message.from_user.id))} чтобы получить уведомление о появлении",
                parse_mode="HTML"
            )
            return
        
        add_to_tracking(message.from_user.id, nm_id, url, price, True)
        
        price_with_auth = calc_price_with_wallet(price, discounts["auth"])
        
        await message.answer(
            f"✅ <b>Товар добавлен в отслеживание!</b>\n\n"
            f"📦 Артикул: {nm_id}\n"
            f"💰 Цена: {price} ₽\n"
            f"💎 С ВБ Кошельком: {price_with_auth} ₽",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await message.answer("❌ Не удалось получить информацию о товаре")




@dp.message_handler(commands=['mytrack'])
async def mytrack_command(message: types.Message):
    items = get_user_tracked_items(message.from_user.id)
    discounts = get_wallet_discount()
    
    if not items:
        await message.answer("📭 У вас пока нет отслеживаемых товаров\nДобавьте товар командой /track")
        return
    
    response = "📋 <b>Ваши товары:</b>\n\n"
    
    for i, (nm_id, url, last_price, last_checked) in enumerate(items, 1):
        local_time = to_local_time(last_checked)
        formatted_date = local_time.strftime('%d.%m.%Y %H:%M')
        
        # Получаем статус наличия из БД
        conn = sqlite3.connect('price_tracking.db')
        cursor = conn.cursor()
        cursor.execute('SELECT is_available, notify_on_appear FROM tracked_prices WHERE nm_id = ? AND user_id = ?', 
                      (nm_id, message.from_user.id))
        result = cursor.fetchone()
        conn.close()
        
        is_available = result[0] if result else 1
        notify_on_appear = result[1] if result else 0
        
        status_emoji = "✅" if is_available else "❌"
        notify_emoji = " 🔔" if notify_on_appear else ""
        
        if is_available and last_price > 0:
            price_with_auth = calc_price_with_wallet(Decimal(str(last_price)), discounts["auth"])
            price_text = f"{last_price} ₽ (с кошельком: {price_with_auth} ₽)"
        else:
            price_text = "Нет в наличии"
        
        response += (
            f"<b>{i}.</b> {status_emoji} <a href='{url}'>Товар {nm_id}</a>{notify_emoji}\n"
            f"   💰 {price_text}\n"
            f"   🕐 {formatted_date}\n\n"
        )
    
    response += (
        "📌 <b>Команды:</b>\n"
        "• /untrack [номер] - удалить\n"
        "• /notify [номер] - уведомлять о появлении\n"
        "• /stopnotify [номер] - отключить уведомления\n"
        "• /target [номер] [цена] - установить цель"
    )
    await message.answer(response, parse_mode="HTML", disable_web_page_preview=True)




@dp.message_handler(commands=['untrack'])
async def untrack_command(message: types.Message):
    args = message.get_args()
    if not args:
        await message.answer("❌ Укажите номер товара из списка /mytrack")
        return
    
    try:
        item_number = int(args)
        items = get_user_tracked_items(message.from_user.id)
        
        if item_number < 1 or item_number > len(items):
            await message.answer("❌ Неверный номер")
            return
        
        nm_id = items[item_number - 1][0]
        remove_from_tracking(message.from_user.id, nm_id)
        
        await message.answer(f"✅ Товар {nm_id} удален из отслеживания")
        
    except ValueError:
        await message.answer("❌ Введите номер цифрой")




@dp.message_handler(commands=['history'])
async def history_command(message: types.Message):
    args = message.get_args()
    if not args:
        await message.answer("❌ Укажите номер товара из списка /mytrack")
        return
    
    try:
        item_number = int(args)
        items = get_user_tracked_items(message.from_user.id)
        
        if item_number < 1 or item_number > len(items):
            await message.answer("❌ Неверный номер")
            return
        
        nm_id = items[item_number - 1][0]
        url = items[item_number - 1][1]
        
        history = get_price_history(nm_id)
        
        if not history:
            await message.answer("📊 История изменения цены пока отсутствует")
            return
        
        discounts = get_wallet_discount()
        response = f"📊 <b>История цены</b>\n🔗 <a href='{url}'>Товар {nm_id}</a>\n\n"
        
        for price, checked_at in history[:10]:
            local_time = to_local_time(checked_at)
            formatted_date = local_time.strftime('%d.%m.%Y %H:%M')
            price_with_auth = calc_price_with_wallet(Decimal(str(price)), discounts["auth"])
            response += f"• {formatted_date}: {price} ₽ (с кошельком: {price_with_auth} ₽)\n"
        
        await message.answer(response, parse_mode="HTML", disable_web_page_preview=True)
        
    except ValueError:
        await message.answer("❌ Введите номер цифрой")




@dp.message_handler(commands=['target'])
async def target_command(message: types.Message):
    args = message.get_args()
    if not args:
        await message.answer("❌ Укажите: /target [номер] [цена]\nПример: /target 1 5000")
        return
    
    try:
        parts = args.split()
        if len(parts) != 2:
            await message.answer("❌ Неверный формат. Используйте: /target [номер] [цена]")
            return
        
        item_number = int(parts[0])
        target_price = Decimal(parts[1])
        
        items = get_user_tracked_items(message.from_user.id)
        
        if item_number < 1 or item_number > len(items):
            await message.answer("❌ Неверный номер")
            return
        
        nm_id = items[item_number - 1][0]
        url = items[item_number - 1][1]
        
        set_target_price(message.from_user.id, nm_id, target_price)
        
        await message.answer(
            f"✅ <b>Цель установлена!</b>\n\n"
            f"📦 <a href='{url}'>Товар {nm_id}</a>\n"
            f"🎯 Цель (с ВБ Кошельком): {target_price} ₽\n\n"
            f"🔔 Я уведомлю вас, когда цена достигнет цели!",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        
    except ValueError:
        await message.answer("❌ Введите корректные числа")




@dp.message_handler(commands=['mytargets'])
async def mytargets_command(message: types.Message):
    targets = get_user_targets(message.from_user.id)
    discounts = get_wallet_discount()
    
    if not targets:
        await message.answer(
            "📭 У вас нет установленных целевых цен\n"
            "Установите цель командой: /target [номер] [цена]"
        )
        return
    
    response = "🎯 <b>Ваши цели:</b>\n\n"
    
    for i, (nm_id, target_price, is_achieved, created_at, url, current_price) in enumerate(targets, 1):
        status = "✅ Достигнута" if is_achieved else "⏳ Ожидание"
        current_with_auth = calc_price_with_wallet(Decimal(str(current_price)), discounts["auth"])
        
        local_time = to_local_time(created_at)
        formatted_date = local_time.strftime('%d.%m.%Y')
        
        response += (
            f"<b>{i}.</b> <a href='{url}'>Товар {nm_id}</a>\n"
            f"   📊 {status}\n"
            f"   🎯 Цель: {target_price} ₽\n"
            f"   💰 Сейчас: {current_with_auth} ₽\n"
            f"   📅 {formatted_date}\n\n"
        )
    
    response += "Для удаления: /removetarget [номер]"
    await message.answer(response, parse_mode="HTML", disable_web_page_preview=True)




@dp.message_handler(commands=['removetarget'])
async def removetarget_command(message: types.Message):
    args = message.get_args()
    if not args:
        await message.answer("❌ Укажите номер цели из списка /mytargets")
        return
    
    try:
        item_number = int(args)
        targets = get_user_targets(message.from_user.id)
        
        if item_number < 1 or item_number > len(targets):
            await message.answer("❌ Неверный номер")
            return
        
        nm_id = targets[item_number - 1][0]
        remove_target(message.from_user.id, nm_id)
        
        await message.answer(f"✅ Цель для товара {nm_id} удалена")
        
    except ValueError:
        await message.answer("❌ Введите номер цифрой")




@dp.message_handler(commands=['notify'])
async def notify_command(message: types.Message):
    """Включить уведомления о появлении товара"""
    args = message.get_args()
    if not args:
        await message.answer("❌ Укажите номер товара из списка /mytrack")
        return
    
    try:
        item_number = int(args)
        items = get_user_tracked_items(message.from_user.id)
        
        if item_number < 1 or item_number > len(items):
            await message.answer("❌ Неверный номер")
            return
        
        nm_id = items[item_number - 1][0]
        url = items[item_number - 1][1]
        
        set_notify_on_appear(message.from_user.id, nm_id, True)
        
        await message.answer(
            f"🔔 <b>Уведомление включено!</b>\n\n"
            f"📦 <a href='{url}'>Товар {nm_id}</a>\n"
            f"Я уведомлю вас, когда товар снова появится в наличии!",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        
    except ValueError:
        await message.answer("❌ Введите номер цифрой")




@dp.message_handler(commands=['stopnotify'])
async def stop_notify_command(message: types.Message):
    """Выключить уведомления о появлении товара"""
    args = message.get_args()
    if not args:
        await message.answer("❌ Укажите номер товара из списка /mytrack")
        return
    
    try:
        item_number = int(args)
        items = get_user_tracked_items(message.from_user.id)
        
        if item_number < 1 or item_number > len(items):
            await message.answer("❌ Неверный номер")
            return
        
        nm_id = items[item_number - 1][0]
        
        set_notify_on_appear(message.from_user.id, nm_id, False)
        
        await message.answer(f"🔕 Уведомления для товара {nm_id} отключены")
        
    except ValueError:
        await message.answer("❌ Введите номер цифрой")




@dp.message_handler()
async def handle_link(message: types.Message):
    url = message.text.strip()
    
    if not re.search(r'wildberries\.ru', url):
        await message.answer("❌ Отправьте ссылку на товар Wildberries")
        return
    
    await message.answer("🔍 Получаю информацию...")


    try:
        price, nm_id, is_available = await get_product_price_with_availability(url)
        discounts = get_wallet_discount()
        
        keyboard = InlineKeyboardMarkup(row_width=1)
        track_button = InlineKeyboardButton(
            "🔔 Отслеживать",
            callback_data=f"track_{nm_id}"
        )
        keyboard.add(track_button)
        
        if not is_available or price is None:
            await message.answer(
                f"ℹ️ <b>Товар временно отсутствует в наличии</b>\n\n"
                f"📦 Артикул: {nm_id}\n\n"
                f"Вы можете добавить его в список ожидания и получить уведомление о появлении!",
                parse_mode="HTML",
                reply_markup=keyboard
            )
            return
        
        price_with_auth = calc_price_with_wallet(price, discounts["auth"])


        await message.answer(
            f"💰 <b>Цена на WB:</b> {price} ₽\n"
            f"💎 <b>С ВБ Кошельком:</b> {price_with_auth} ₽\n\n"
            f"📦 Артикул: {nm_id}",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await message.answer("❌ Не удалось получить информацию о товаре")




@dp.callback_query_handler(lambda c: c.data and c.data.startswith('track_'))
async def process_callback_track(callback_query: types.CallbackQuery):
    nm_id = callback_query.data.replace('track_', '')
    
    try:
        url = f"https://www.wildberries.ru/catalog/{nm_id}/detail.aspx"
        price, _, is_available = await get_product_price_with_availability(url)
        
        add_to_tracking(callback_query.from_user.id, nm_id, url, price if price else Decimal('0'), is_available)
        
        await bot.answer_callback_query(callback_query.id, "✅ Товар добавлен!")
        
        if is_available and price:
            discounts = get_wallet_discount()
            price_with_auth = calc_price_with_wallet(price, discounts["auth"])
            
            await bot.send_message(
                callback_query.from_user.id,
                f"✅ <b>Товар добавлен в отслеживание!</b>\n\n"
                f"📦 Артикул: {nm_id}\n"
                f"💰 Цена: {price} ₽\n"
                f"💎 С ВБ Кошельком: {price_with_auth} ₽",
                parse_mode="HTML"
            )
        else:
            await bot.send_message(
                callback_query.from_user.id,
                f"✅ <b>Товар добавлен в список ожидания</b>\n\n"
                f"📦 Артикул: {nm_id}\n"
                f"🔔 Используйте /notify чтобы получать уведомления о появлении",
                parse_mode="HTML"
            )
            
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await bot.answer_callback_query(
            callback_query.id,
            "❌ Ошибка при добавлении",
            show_alert=True
        )




# --- Запуск ---
async def on_startup(dp):
    asyncio.create_task(check_prices())
    logger.info("=" * 50)
    logger.info("🚀 БОТ УСПЕШНО ЗАПУЩЕН!")
    logger.info("=" * 50)




if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
