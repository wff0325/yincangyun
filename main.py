#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import shutil
import requests
from datetime import datetime, timezone, timedelta
from seleniumbase import Driver

# ====================== 配置区域 ======================
HIDENCLOUD = os.getenv("HIDENCLOUD", "")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")
PROXY_SERVER = os.getenv("PROXY_SERVER", "")
# 优先读取手动配置的 ID (GitHub Secrets 中的 SERVER_ID)
MANUAL_SERVER_ID = os.getenv("SERVER_ID", "")

if "-----" in HIDENCLOUD:
    HIDEN_EMAIL, HIDEN_PWD = HIDENCLOUD.split("-----", 1)
else:
    raise ValueError("❌ HIDENCLOUD 格式错误，应为 email-----password")

BASE_URL = "https://dash.hidencloud.com"
STATE_DIR = "browser_state"
SCREENSHOT_DIR = "screenshots"

os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

USER_DATA_DIR = os.path.abspath(os.path.join(STATE_DIR, "selenium_profile"))

# ====================== 工具函数 ======================
def clean_profile():
    """在脚本内部清理浏览器残留锁文件"""
    if os.path.exists(USER_DATA_DIR):
        print(f"[INFO] 🧹 正在清理配置目录锁文件: {USER_DATA_DIR}")
        for root, dirs, files in os.walk(USER_DATA_DIR):
            for name in files:
                if name in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
                    try:
                        os.remove(os.path.join(root, name))
                    except:
                        pass

def get_bj_time():
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')

def send_tg_notification(message, photo_path=None):
    if not TG_BOT_TOKEN or not TG_CHAT_ID: return
    try:
        if photo_path and os.path.exists(photo_path):
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
            with open(photo_path, 'rb') as f:
                requests.post(url, files={'photo': f}, data={'chat_id': TG_CHAT_ID, 'caption': message, 'parse_mode': 'Markdown'}, timeout=30)
        else:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e: print(f"[ERROR] TG 发送失败: {e}")

def take_screenshot(driver, name):
    timestamp = datetime.now().strftime('%H%M%S')
    filename = os.path.join(SCREENSHOT_DIR, f"{timestamp}-{name}.png")
    try: driver.save_screenshot(filename)
    except: pass
    return filename

# ====================== 主逻辑 ======================
def main():
    print("[INFO] " + "=" * 50)
    print("[INFO] HidenCloud 自动续期脚本 (GitHub Actions Optimized)")
    print("[INFO] " + "=" * 50)

    # 启动前清理锁
    clean_profile()

    # ---------- 浏览器驱动配置 ----------
    # 针对 GitHub Actions 的 session not created 报错进行了针对性优化
    driver_kwargs = {
        "uc": True,                # 启用隐身模式
        "headless": True,          # 必须开启无头
        "user_data_dir": USER_DATA_DIR,
        "no_sandbox": True,        # ❗ 关键：解决权限问题
        "disable_dev_shm_usage": True, # ❗ 关键：解决内存分配问题
        "window_size": "1366,768",
        "agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }
    
    if PROXY_SERVER:
        driver_kwargs["proxy"] = PROXY_SERVER
        print(f"[INFO] 🌐 使用代理: {PROXY_SERVER}")

    print("[INFO] 🚀 正在启动浏览器...")
    driver = Driver(**driver_kwargs)
    driver.set_page_load_timeout(60)

    try:
        # ---------- 1. 访问主页 ----------
        dashboard_url = f"{BASE_URL}/dashboard"
        print(f"[INFO] 🌐 访问主页: {dashboard_url}")
        
        # 使用重连模式打开，绕过 CF
        driver.uc_open_with_reconnect(dashboard_url, reconnect_time=10)
        time.sleep(8)
        take_screenshot(driver, "01-initial")

        # ---------- 2. 登录判断 ----------
        if "/auth/login" in driver.current_url or driver.is_element_visible("input#username"):
            print("[INFO] 🔒 检测到未登录，执行登录...")
            driver.type("input#username", HIDEN_EMAIL)
            driver.type("input#password", HIDEN_PWD)
            
            if driver.is_element_present(".cf-turnstile"):
                print("[INFO] 🖱️ 点击 Turnstile...")
                driver.uc_gui_click_cf(".cf-turnstile")
                time.sleep(5)
            
            driver.click("button[type='submit']")
            time.sleep(10)
        else:
            print("[INFO] ✅ 已登录")

        # ---------- 3. 提取服务器 ID ----------
        sid = MANUAL_SERVER_ID
        if not sid or not str(sid).strip():
            print("[INFO] 🔍 自动抓取服务器 ID...")
            sid = driver.execute_script("""
                let m = document.body.innerHTML.match(/\\/service\\/(\\d+)\\/manage/);
                return m ? m[1] : null;
            """)

        if not sid:
            take_screenshot(driver, "ERROR-no-id")
            raise Exception("未找到服务器 ID，请在 Secret 中手动配置 SERVER_ID")

        # ---------- 4. 续期流程 ----------
        manage_url = f"{BASE_URL}/service/{sid}/manage"
        driver.get(manage_url)
        time.sleep(8)
        
        # 提取 Due Date
        due_raw = driver.execute_script("""
            let h = Array.from(document.querySelectorAll('h6')).find(e => e.innerText.includes('Due date'));
            return h ? h.nextElementSibling.innerText.trim() : 'N/A';
        """)
        print(f"[INFO] 当前到期: {due_raw}")

        try:
            renew_btn = driver.find_element("xpath", "//button[contains(.,'Renew')]")
            driver.execute_script("arguments[0].click();", renew_btn)
            time.sleep(5)
        except:
            raise Exception("未找到 Renew 按钮")

        if "Renewal Restricted" in driver.page_source:
            res_status = "ℹ️ 暂无可续期"
        else:
            print("[INFO] 提交续期请求...")
            driver.execute_script(f"document.querySelector('div#renewService-{sid} button[type=\"submit\"]').click();")
            time.sleep(5)
            try:
                pay_btn = driver.find_element("xpath", "//button[contains(.,'Pay')]")
                driver.execute_script("arguments[0].click();", pay_btn)
                time.sleep(5)
            except: pass
            res_status = "✅ 续期已执行"

        # 刷新结果
        driver.get(manage_url)
        time.sleep(5)
        final_due = driver.execute_script("""
            let h = Array.from(document.querySelectorAll('h6')).find(e => e.innerText.includes('Due date'));
            return h ? h.nextElementSibling.innerText.trim() : 'N/A';
        """)
        
        # 输出标准时间供 Cron 脚本更新
        std_m = re.search(r'(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})', final_due)
        if std_m:
            dt = datetime.strptime(f"{std_m.group(1)} {std_m.group(2)} {std_m.group(3)}", "%d %b %Y")
            print(f"到期时间(标准): {dt.strftime('%Y-%m-%d')}")

        send_tg_notification(f"{res_status}\n账号: `{HIDEN_EMAIL}`\n到期: {final_due}", 
                             photo_path=take_screenshot(driver, "final"))

    except Exception as e:
        print(f"[ERROR] ❌ 执行失败: {e}")
        take_screenshot(driver, "CRITICAL-ERROR")
        send_tg_notification(f"❌ HidenCloud 续期失败\n错误: {str(e)[:100]}")
        raise
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
