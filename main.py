#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
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
def get_bj_time():
    """返回北京时间字符串"""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')


def send_tg_notification(message, photo_path=None):
    """发送 Telegram 通知，可附带截图"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        if photo_path and os.path.exists(photo_path):
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
            with open(photo_path, 'rb') as f:
                files = {'photo': f}
                data = {'chat_id': TG_CHAT_ID, 'caption': message, 'parse_mode': 'Markdown'}
                requests.post(url, files=files, data=data, timeout=30)
        else:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "Markdown"}
            requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[ERROR] TG 发送失败: {e}")


def take_screenshot(driver, name):
    """截图并返回文件路径"""
    timestamp = datetime.now().strftime('%H%M%S')
    filename = f"{SCREENSHOT_DIR}/{timestamp}-{name}.png"
    try:
        driver.save_screenshot(filename)
        print(f"[INFO] 📸 截图 → {filename}")
    except:
        pass
    return filename


def wait_for_turnstile_token(driver, timeout=90):
    """等待 Cloudflare Turnstile token 生成"""
    print("[INFO] ⏳ 等待 Turnstile 验证通过...")
    start = time.time()
    while time.time() - start < timeout:
        token = driver.execute_script(
            'return document.querySelector("[name=cf-turnstile-response]")?.value'
        )
        if token and len(token) > 20:
            print("[INFO] ✅ Turnstile token 已生成")
            return True
        time.sleep(1)
    return False


def get_current_due_date(driver):
    """获取当前管理页面的到期时间"""
    try:
        due_elem = driver.find_element(
            "xpath", "//h6[contains(text(),'Due date')]/following-sibling::div"
        )
        raw = due_elem.text.strip()
        # 格式解析: "01 May 2026"
        match = re.search(r'(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})', raw)
        if match:
            day, month_str, year = match.groups()
            dt = datetime.strptime(f"{day} {month_str} {year}", "%d %b %Y")
            return raw, dt.strftime("%Y-%m-%d")
        return raw, None
    except:
        return "N/A", None


# ====================== 主逻辑 ======================
def main():
    print("[INFO] " + "=" * 50)
    print("[INFO] HidenCloud 自动续期脚本 (Final Stable Build)")
    print("[INFO] " + "=" * 50)

    # ---------- 浏览器驱动配置 ----------
    # 针对 GitHub Actions 优化：关闭 headless2，仅使用标准的 uc=True
    driver_kwargs = {
        "headless": True,
        "uc": True,
        "user_data_dir": USER_DATA_DIR,
        "window_size": "1366,768",
        "disable_csp": True,
        "agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }
    if PROXY_SERVER:
        driver_kwargs["proxy"] = PROXY_SERVER
        print(f"[INFO] 🌐 使用代理: {PROXY_SERVER}")

    driver = Driver(**driver_kwargs)
    driver.set_page_load_timeout(60)

    final_screenshot = None
    result_status = "❌ 续订失败"
    sid = None

    try:
        # ---------- 1. 访问主页 ----------
        dashboard_url = f"{BASE_URL}/dashboard"
        print(f"[INFO] 🌐 访问主页: {dashboard_url}")
        
        # ⚠️ 使用 uc_open_with_reconnect 代替普通 get，解决“failed to close window”报错
        driver.uc_open_with_reconnect(dashboard_url, reconnect_time=10)
        time.sleep(5)
        take_screenshot(driver, "01-initial")

        # ---------- 2. 登录判断 ----------
        if "/auth/login" in driver.current_url or driver.is_element_visible("input#username"):
            print("[INFO] 🔒 检测到未登录，开始登录流程")
            driver.type("input#username", HIDEN_EMAIL)
            driver.type("input#password", HIDEN_PWD)
            
            if driver.is_element_present(".cf-turnstile"):
                print("[INFO] 🖱️ 尝试通过 JS 点击 Turnstile...")
                driver.uc_gui_click_cf(".cf-turnstile")
                wait_for_turnstile_token(driver)
            
            driver.click("button[type='submit']")
            time.sleep(8)
            print("[INFO] ✅ 登录请求已发送")
        else:
            print("[INFO] ✅ 已登录，跳过登录流程")

        # ---------- 3. 提取服务器 ID ----------
        if MANUAL_SERVER_ID and str(MANUAL_SERVER_ID).strip():
            sid = str(MANUAL_SERVER_ID).strip()
            print(f"[INFO] 🔧 使用手动指定的 ID: {sid}")
        else:
            print("[INFO] 🔍 正在提取服务器 ID...")
            time.sleep(5)
            # 通过全页面搜索提取
            sid = driver.execute_script("""
                let m = document.body.innerHTML.match(/\\/service\\/(\\d+)\\/manage/);
                return m ? m[1] : null;
            """)

        if not sid:
            take_screenshot(driver, "ERROR-no-id")
            raise Exception("无法抓取服务器 ID，请检查 Secret 中是否配置了 SERVER_ID")

        # ---------- 4. 续期核心流程 ----------
        manage_url = f"{BASE_URL}/service/{sid}/manage"
        print(f"[INFO] 🚀 访问管理页面: {manage_url}")
        driver.get(manage_url)
        time.sleep(5)
        
        due_before_raw, due_before_std = get_current_due_date(driver)
        print(f"[INFO] 续订前到期时间: {due_before_raw}")

        # 查找并点击 Renew
        try:
            renew_btn = driver.find_element("xpath", "//button[contains(.,'Renew')]")
            driver.execute_script("arguments[0].click();", renew_btn)
            print("[INFO] ✅ Renew 按钮已点击")
            time.sleep(3)
        except:
            raise Exception("未找到 Renew 按钮")

        # 检测是否受限
        if "Renewal Restricted" in driver.page_source:
            print("[INFO] ℹ️ 目前暂不可续期")
            result_status = "ℹ️ 暂无可续期"
            due_after_raw = due_before_raw
            due_after_std = due_before_std
        else:
            # 正常提交续期
            print("[INFO] 📦 提交续期模态框...")
            driver.execute_script(f"document.querySelector('div#renewService-{sid} button[type=\"submit\"]').click();")
            time.sleep(5)
            
            # 处理支付按钮（免费服务通常点击 Pay 即可）
            try:
                pay_btn = driver.find_element("xpath", "//button[contains(.,'Pay')]")
                driver.execute_script("arguments[0].click();", pay_btn)
                time.sleep(5)
            except:
                pass
            
            # 刷新结果
            driver.get(manage_url)
            time.sleep(5)
            due_after_raw, due_after_std = get_current_due_date(driver)
            
            if due_after_std and due_before_std and due_after_std > due_before_std:
                result_status = "✅ 续订成功"
            else:
                result_status = "⚠️ 已执行续期，请检查"

        # 结果输出供 YAML 提取
        if due_after_std:
            print(f"到期时间(标准): {due_after_std}")

        # 发送通知
        final_screenshot = take_screenshot(driver, "final-result")
        tg_msg = (
            f"{result_status}\n\n"
            f"账号: `{HIDEN_EMAIL}`\n"
            f"服务器: `Free Server #{sid}`\n"
            f"到期: {due_after_raw}\n"
            f"时间: {get_bj_time()}"
        )
        send_tg_notification(tg_msg, photo_path=final_screenshot)
        print(f"[INFO] 🎉 任务完成: {result_status}")

    except Exception as e:
        print(f"[ERROR] ❌ 执行失败: {e}")
        send_tg_notification(f"❌ HidenCloud 续期失败\n错误: {str(e)[:100]}")
        raise
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
