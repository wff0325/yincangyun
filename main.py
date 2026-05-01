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
# 💡 强烈建议：在 GitHub Secrets 中添加 SERVER_ID，值为 207359
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
        print("[WARN] 未配置 TG 信息，跳过发送")
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
        print("[INFO] 📡 TG 通知已发送")
    except Exception as e:
        print(f"[ERROR] TG 发送失败: {e}")


def take_screenshot(driver, name):
    """截图并返回文件路径"""
    timestamp = datetime.now().strftime('%H%M%S')
    filename = f"{SCREENSHOT_DIR}/{timestamp}-{name}.png"
    try:
        driver.save_screenshot(filename)
        print(f"[INFO] 📸 截图 → {filename}")
    except Exception as e:
        print(f"[WARN] 截图失败: {e}")
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


def wait_for_url_contains(driver, keyword, timeout=45):
    """等待当前 URL 包含特定关键字"""
    start = time.time()
    while time.time() - start < timeout:
        if keyword in driver.current_url:
            return True
        time.sleep(0.5)
    return False


def get_current_due_date(driver):
    """获取当前管理页面的到期时间"""
    try:
        # 尝试多种可能的 Due Date 定位器
        selectors = [
            "//h6[contains(text(),'Due date')]/following-sibling::div",
            "//div[contains(text(),'Due date')]/following-sibling::div",
            "//p[contains(text(),'Due date')]/following-sibling::p"
        ]
        for sel in selectors:
            try:
                due_elem = driver.find_element("xpath", sel)
                raw = due_elem.text.strip()
                if raw:
                    # 解析日期格式: "01 May 2026"
                    match = re.search(r'(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})', raw)
                    if match:
                        day, month_str, year = match.groups()
                        dt = datetime.strptime(f"{day} {month_str} {year}", "%d %b %Y")
                        return raw, dt.strftime("%Y-%m-%d")
                    return raw, raw
            except:
                continue
        return "N/A", None
    except:
        return "N/A", None


# ====================== 主逻辑 ======================
def main():
    print("[INFO] " + "=" * 50)
    print("[INFO] HidenCloud 自动续期脚本 (SeleniumBase) - Final Stability Version")
    print("[INFO] " + "=" * 50)

    driver_kwargs = {
        "headless": True,
        "headless2": True,
        "uc": True,
        "user_data_dir": USER_DATA_DIR,
        "window_size": "1280,753",
        "disable_csp": True,
        "agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }
    if PROXY_SERVER:
        driver_kwargs["proxy"] = PROXY_SERVER
        print(f"[INFO] 🌐 使用代理: {PROXY_SERVER}")

    driver = Driver(**driver_kwargs)

    try:
        # ---------- 1. 访问主页 ----------
        print(f"[INFO] 🌐 访问主页: {BASE_URL}/dashboard")
        driver.get(f"{BASE_URL}/dashboard")
        time.sleep(5)
        take_screenshot(driver, "01-initial")

        # ---------- 2. 登录判断 ----------
        if "/auth/login" in driver.current_url or driver.is_element_visible("input#username"):
            print("[INFO] 🔒 检测到未登录，开始登录流程")
            driver.type("input#username", HIDEN_EMAIL)
            driver.type("input#password", HIDEN_PWD)
            time.sleep(2)

            if driver.is_element_present(".cf-turnstile"):
                print("[INFO] 🖱️ 尝试点击 Turnstile...")
                driver.uc_gui_click_cf(".cf-turnstile")
                if not wait_for_turnstile_token(driver):
                    raise Exception("Turnstile 验证超时")
            
            driver.click("button[type='submit']")
            if not wait_for_url_contains(driver, "/dashboard", timeout=45):
                raise Exception("登录跳转失败")
            print("[INFO] ✅ 登录成功")
        else:
            print("[INFO] ✅ 已经处于登录状态")

        # ---------- 3. 提取服务器 ID ----------
        sid = None
        if MANUAL_SERVER_ID:
            sid = MANUAL_SERVER_ID
            print(f"[INFO] 🔧 使用手动指定的服务器 ID: {sid}")
        else:
            print("[INFO] 🔍 正在尝试多种方式提取服务器 ID...")
            time.sleep(12) # 给够充足的渲染时间
            take_screenshot(driver, "08-dashboard")

            # 方式 A: 执行 JS 脚本 (最强力)
            sid = driver.execute_script("""
                const links = Array.from(document.querySelectorAll('a[href*="/service/"]'));
                for (let a of links) {
                    let m = a.href.match(/\/service\/(\\d+)/);
                    if (m) return m[1];
                }
                const rows = document.querySelector('tr[id*="table-column-body-"]');
                if (rows) return rows.id.match(/\\d+/)[0];
                return null;
            """)

            # 方式 B: Python 正则二次扫描
            if not sid:
                print("[INFO] JS 提取失败，尝试正则扫描页面源码...")
                source = driver.page_source
                match = re.search(r'/service/(\d+)', source)
                if match:
                    sid = match.group(1)
            
            if sid:
                print(f"[INFO] ✅ 成功提取到服务器 ID: {sid}")
            else:
                print(f"[DEBUG] 页面标题: {driver.title}")
                print(f"[DEBUG] 页面部分内容: {driver.find_element('tag name', 'body').text[:300]}...")
                raise Exception("无法自动提取服务器 ID。请在 GitHub Secrets 中添加 SERVER_ID 变量。")

        # ---------- 4. 进入管理页面并续期 ----------
        manage_url = f"{BASE_URL}/service/{sid}/manage"
        print(f"[INFO] 🚀 进入管理页面: {manage_url}")
        driver.get(manage_url)
        time.sleep(5)
        take_screenshot(driver, "09-manage-page")

        due_before_raw, due_before_std = get_current_due_date(driver)
        print(f"[INFO] 续期前到期时间: {due_before_raw}")

        # 查找 Renew 按钮
        print("[INFO] 🔄 查找 Renew 按钮...")
        renew_btn = None
        try:
            renew_btn = driver.find_element("xpath", "//button[contains(.,'Renew')]")
        except:
            # 备选定位
            renew_btn = driver.find_element("css selector", "button[onclick*='showRenewAlert']")

        if not renew_btn:
            raise Exception("未找到 Renew 按钮")

        # 获取续期限制信息
        onclick_val = renew_btn.get_attribute("onclick") or ""
        days_left = None
        param_match = re.search(r'showRenewAlert\((\d+)', onclick_val)
        if param_match:
            days_left = int(param_match.group(1))
            print(f"[INFO] 当前剩余天数: {days_left}")

        # 点击 Renew
        renew_btn.click()
        time.sleep(3)
        take_screenshot(driver, "10-renew-clicked")

        # 判断是否被限制续期
        is_restricted = driver.execute_script("return document.body.innerText.includes('Renewal Restricted')")
        
        if is_restricted:
            print("[INFO] ℹ️ 触发续期限制，目前无需续期。")
            result_status = "ℹ️ 暂无可续期"
            due_after_raw = due_before_raw
            due_after_std = due_before_std
        else:
            print("[INFO] 📦 正在处理续期订单...")
            # 处理模态框提交
            driver.execute_script(f"document.querySelector('div#renewService-{sid} button[type=\"submit\"]').click()")
            time.sleep(5)
            take_screenshot(driver, "12-invoice-created")
            
            # 支付页面处理 (针对免费服务通常会自动完成，或者点击 Pay 按钮)
            try:
                pay_btn = driver.find_element("xpath", "//button[contains(.,'Pay')]")
                pay_btn.click()
                time.sleep(5)
                print("[INFO] ✅ 已点击支付按钮")
            except:
                print("[INFO] 未发现支付按钮，可能已自动完成")

            # 刷新页面看最终结果
            driver.get(manage_url)
            time.sleep(5)
            due_after_raw, due_after_std = get_current_due_date(driver)
            
            if due_after_std and due_before_std and due_after_std > due_before_std:
                result_status = "✅ 续订成功"
            else:
                result_status = "⚠️ 已执行续期，请检查日期"

        # ---------- 5. 结果输出与通知 ----------
        print(f"到期时间(标准): {due_after_std or due_after_raw}")
        bj_time = get_bj_time()
        
        tg_msg = (
            f"{result_status}\n\n"
            f"账号: `{HIDEN_EMAIL}`\n"
            f"服务器: `Free Server #{sid}`\n"
            f"到期: {due_after_raw}\n"
            f"时间: {bj_time}"
        )
        send_tg_notification(tg_msg, photo_path=take_screenshot(driver, "16-final"))
        print(f"[INFO] 🎉 任务完成: {result_status}")

    except Exception as e:
        print(f"[ERROR] ❌ 脚本执行失败: {e}")
        take_screenshot(driver, "CRITICAL-ERROR")
        send_tg_notification(f"❌ HidenCloud 续期失败\n错误: {str(e)[:100]}")
        raise
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
