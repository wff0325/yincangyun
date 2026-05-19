# -*- coding: utf-8 -*-
import os
import time
import re
import json
from datetime import datetime, timedelta
from seleniumbase import Driver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests

# === Секреты и переменные окружения ===
HIDENCLOUD = os.environ.get("HIDENCLOUD")
SERVER_ID = os.environ.get("SERVER_ID")          # ID сервера из секрета
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")
PROXY_SERVER = os.environ.get("PROXY_SERVER")    # может быть задан из шага с прокси

def send_telegram(message):
    """Отправка уведомления в Telegram (только ошибки и успех)"""
    if TG_BOT_TOKEN and TG_CHAT_ID:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        try:
            requests.post(url, json={"chat_id": TG_CHAT_ID, "text": message}, timeout=10)
        except Exception:
            pass

def log(msg, status="info"):
    """Печать в консоль и отправка в Telegram важных сообщений"""
    print(msg)
    if status in ("error", "success"):
        send_telegram(msg)

# === Проверка наличия логина/пароля ===
if not HIDENCLOUD or "-----" not in HIDENCLOUD:
    log("❌ Ошибка: секрет HIDENCLOUD не задан или неверный формат (нужно email-----пароль)", "error")
    exit(1)

email, password = HIDENCLOUD.split("-----", 1)
log(f"🔐 Пользователь: {email}")

# === Настройка браузера (SeleniumBase) ===
options = {
    "headless": True,
    "disable_csp": True,
    "disable_gpu": True,
    "no_sandbox": True,
    "disable_dev_shm_usage": True,
}
if PROXY_SERVER:
    options["proxy"] = PROXY_SERVER
    log(f"🌐 Используется прокси: {PROXY_SERVER}")

driver = None
try:
    driver = Driver(browser="chrome", headless=True, **options)
    wait = WebDriverWait(driver, 20)
    log("🟡 Запущен браузер, начинаем работу...")
except Exception as e:
    log(f"❌ Не удалось запустить браузер: {e}", "error")
    exit(1)

# === Функция для входа в панель ===
def login():
    log("🟡 Загружаем страницу входа...")
    driver.get("https://freepanel.hidencloud.com/auth/login")
    time.sleep(2)
    # Ввод email
    email_input = wait.until(EC.presence_of_element_located((By.NAME, "email")))
    email_input.clear()
    email_input.send_keys(email)
    # Ввод пароля
    password_input = driver.find_element(By.NAME, "password")
    password_input.clear()
    password_input.send_keys(password)
    # Нажатие кнопки входа
    login_button = driver.find_element(By.XPATH, "//button[@type='submit']")
    login_button.click()
    time.sleep(3)
    # Проверка успеха
    if "dashboard" in driver.current_url:
        log("✅ Вход выполнен успешно!")
        return True
    else:
        log("❌ Не удалось войти. Проверьте email/пароль.", "error")
        return False

# === Функция для выбора сервера по ID или автоматически ===
def select_server():
    log("🟡 Переходим на страницу со списком серверов...")
    driver.get("https://freepanel.hidencloud.com/client")
    time.sleep(3)
    # Находим все элементы серверов (обычно ссылки вида /server/xxxxx)
    server_links = driver.find_elements(By.CSS_SELECTOR, "a[href^='/server/']")
    if not server_links:
        log("❌ Не найдено ни одного сервера. Возможно, аккаунт пуст или сервер удалён.", "error")
        return None

    log(f"📋 Найдено серверов: {len(server_links)}")
    
    # Если задан SERVER_ID, ищем по нему
    if SERVER_ID:
        log(f"🔍 Ищем сервер с ID: {SERVER_ID}")
        for link in server_links:
            href = link.get_attribute("href")
            match = re.search(r'/server/([a-f0-9]+)', href)
            if match and match.group(1) == SERVER_ID:
                log(f"✅ Сервер найден: {link.text.strip()} (ID: {SERVER_ID})")
                return link
        log(f"❌ Сервер с ID {SERVER_ID} не найден в списке.", "error")
        return None
    else:
        # Иначе берём первый сервер
        log("🟡 SERVER_ID не задан, берём первый сервер из списка.")
        return server_links[0]

# === Функция продления ===
def renew_server(server_link):
    log("🟡 Открываем страницу управления сервером...")
    server_link.click()
    time.sleep(3)
    # Ищем кнопку продления (Renew)
    try:
        renew_btn = driver.find_element(By.XPATH, "//button[contains(text(),'Renew') or contains(text(),'Продлить')]")
        renew_btn.click()
        time.sleep(2)
        # Подтверждение (если есть)
        try:
            confirm_btn = driver.find_element(By.XPATH, "//button[contains(text(),'Confirm') or contains(text(),'Подтвердить')]")
            confirm_btn.click()
            time.sleep(2)
        except:
            pass
        # Проверяем результат
        success_msg = driver.find_elements(By.XPATH, "//div[contains(@class,'success') or contains(text(),'success')]")
        if success_msg:
            log("✅ Сервер успешно продлён!", "success")
            # Пытаемся извлечь новую дату
            try:
                date_elem = driver.find_element(By.XPATH, "//*[contains(text(),'Expires') or contains(text(),'истекает')]/following-sibling::*")
                new_date = date_elem.text
                log(f"📅 Новая дата истечения: {new_date}")
            except:
                pass
            return True
        else:
            # Возможно, ошибка "already renewed"
            error_text = driver.find_element(By.XPATH, "//div[contains(@class,'alert-danger')]").text
            log(f"⚠️ Возможно, уже продлён: {error_text}")
            return True
    except Exception as e:
        log(f"❌ Ошибка при продлении: {e}", "error")
        return False

# === Основной процесс ===
try:
    if not login():
        exit(1)
    server = select_server()
    if not server:
        exit(1)
    if not renew_server(server):
        exit(1)
    log("🏁 Скрипт успешно завершён.", "success")
except Exception as e:
    log(f"❌ Непредвиденная ошибка: {e}", "error")
    exit(1)
finally:
    if driver:
        driver.quit()
