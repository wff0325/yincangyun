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

# --- 核心注入脚本：解决 Shadow DOM 验证码定位问题 ---
INJECTED_SCRIPT = """
(function() {
    if (window.self !== window.top) return;
    const originalAttachShadow = Element.prototype.attachShadow;
    Element.prototype.attachShadow = function(init) {
        const shadowRoot = originalAttachShadow.call(this, init);
        if (shadowRoot) {
            const check = () => {
                const cb = shadowRoot.querySelector('input[type="checkbox"]');
                if (cb) {
                    const rect = cb.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        window.__turnstile_coords = {
                            x: rect.left + rect.width / 2,
                            y: rect.top + rect.height / 2
                        };
                        return true;
                    }
                }
                return false;
            };
            const obs = new MutationObserver(() => { if (check()) obs.disconnect(); });
            obs.observe(shadowRoot, { childList: true, subtree: true });
        }
        return shadowRoot;
    };
})();
"""

# ====================== 工具函数 (保留原版) ======================
def get_bj_time():
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')

def send_tg_notification(message, photo_path=None):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("[WARN] 未配置 TG 信息，跳过发送")
        return
    try:
        if photo_path and os.path.exists(photo_path):
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
            with open(photo_path, 'rb') as f:
                requests.post(url, files={'photo': f}, data={'chat_id': TG_CHAT_ID, 'caption': message, 'parse_mode': 'Markdown'}, timeout=30)
        else:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)
        print("[INFO] 📡 TG 通知已发送")
    except Exception as e:
        print(f"[ERROR] TG 发送失败: {e}")

def take_screenshot(driver, name):
    timestamp = datetime.now().strftime('%H%M%S')
    filename = f"{SCREENSHOT_DIR}/{timestamp}-{name}.png"
    try:
        driver.save_screenshot(filename)
        print(f"[INFO] 📸 截图 → {filename}")
    except Exception as e:
        print(f"[WARN] 截图失败: {e}")
    return filename

def wait_for_turnstile_token(driver, timeout=90):
    print("[INFO] ⏳ 等待 Turnstile 验证通过...")
    start = time.time()
    while time.time() - start < timeout:
        token = driver.execute_script('return document.querySelector("[name=cf-turnstile-response]")?.value')
        if token and len(token) > 20:
            print("[INFO] ✅ Turnstile token 已生成")
            return True
        time.sleep(1)
    return False

def cdp_click_turnstile(driver):
    """ 使用 CDP 协议进行底层点击 (绕过 Cloudflare 检测的核心) """
    print("[INFO] 🕵️ 探测 Shadow DOM 中的验证码坐标...")
    for _ in range(20):
        coords = driver.execute_script("return window.__turnstile_coords;")
        if coords:
            x, y = coords['x'], coords['y']
            print(f"[INFO] 🎯 发现坐标 ({x}, {y})，执行 CDP 物理点击")
            driver.execute_cdp_cmd("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
            time.sleep(0.1)
            driver.execute_cdp_cmd("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})
            return True
        time.sleep(1)
    return False

def wait_for_url_contains(driver, keyword, timeout=45):
    start = time.time()
    while time.time() - start < timeout:
        if keyword in driver.current_url: return True
        time.sleep(0.5)
    return False

def check_login_error(driver):
    try:
        error_selectors = [".text-red-500", ".alert-danger", "[role='alert']", ".error"]
        for sel in error_selectors:
            elem = driver.find_element(sel, by="css selector")
            if elem and elem.is_displayed(): return elem.text.strip()
    except: pass
    return None

def mask_email(email):
    if '@' in email:
        local, domain = email.split('@', 1)
        return f"{local[:3]}***@{domain}"
    return f"{email[:3]}***"

def parse_due_date(text):
    if not text: return None
    match = re.search(r'(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})', text)
    if match:
        day, month_str, year = match.groups()
        try:
            dt = datetime.strptime(f"{day} {month_str} {year}", "%d %b %Y")
            return dt.strftime("%Y-%m-%d")
        except: pass
    if re.match(r'\d{4}-\d{2}-\d{2}', text): return text
    return None

def get_current_due_date(driver):
    try:
        due_elem = driver.find_element("xpath", "//h6[contains(text(),'Due date')]/following-sibling::div")
        raw = due_elem.text.strip()
        return raw, parse_due_date(raw)
    except: return "N/A", None

# ====================== 主逻辑 (保留原版完整流程) ======================
def main():
    print("[INFO] " + "=" * 50)
    print("[INFO] HidenCloud 自动续期脚本 (CDP 增强版)")
    print("[INFO] " + "=" * 50)

    driver_kwargs = {
        "headless": True, "headless2": True, "uc": True,
        "user_data_dir": USER_DATA_DIR, "window_size": "1280,1024",
        "agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }
    if PROXY_SERVER: driver_kwargs["proxy"] = PROXY_SERVER

    driver = Driver(**driver_kwargs)

    try:
        # 核心注入：在页面加载前植入坐标探测器
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": INJECTED_SCRIPT})
        
        print(f"[INFO] 🌐 访问主页: {BASE_URL}/dashboard")
        driver.get(f"{BASE_URL}/dashboard")
        time.sleep(3)
        take_screenshot(driver, "01-initial")

        # 2. 登录判断
        if "/auth/login" in driver.current_url or driver.is_element_visible("input#username"):
            print(f"[INFO] 🔒 检测到未登录，开始登录流程: {mask_email(HIDEN_EMAIL)}")
            driver.type("input#username", HIDEN_EMAIL)
            driver.type("input#password", HIDEN_PWD)
            
            # 使用新的 CDP 点击逻辑代替原来的 uc_gui_click_cf
            if not cdp_click_turnstile(driver):
                print("[WARN] 未探测到验证码坐标，尝试普通等待...")
            
            if not wait_for_turnstile_token(driver, timeout=90):
                take_screenshot(driver, "ERROR-turnstile-timeout")
                raise Exception("Turnstile 验证超时")

            driver.click("button[type='submit']")
            
            if not wait_for_url_contains(driver, "/dashboard", timeout=45):
                err = check_login_error(driver)
                if err: raise Exception(f"登录失败: {err}")
                elif "/dashboard" not in driver.current_url: raise Exception("登录跳转超时")

            print("[INFO] ✅ 登录成功")
            take_screenshot(driver, "07-login-success")
        else:
            print("[INFO] ✅ 已登录")

        # 3. 提取服务器 ID
        time.sleep(3)
        try:
            element = driver.find_element("xpath", "//span[contains(text(),'Free Server #')]")
            sid = re.search(r'Free Server #(\d+)', element.text).group(1)
            print(f"[INFO] ✅ 提取到服务器 ID: {sid}")
        except Exception as e:
            take_screenshot(driver, "ERROR-no-server-id")
            raise Exception("无法提取服务器 ID")

        manage_url = f"{BASE_URL}/service/{sid}/manage"
        driver.get(manage_url)
        time.sleep(3)
        due_date_before_raw, due_date_before_std = get_current_due_date(driver)
        print(f"[INFO] 续订前到期时间: {due_date_before_raw}")

        # 5. 续期操作
        renew_executed = False
        restricted = False
        days_left, threshold = None, None

        try:
            renew_btn = driver.find_element("css selector", "button[onclick*='showRenewAlert']")
            onclick_val = renew_btn.get_attribute("onclick") or ""
            param_match = re.search(r'showRenewAlert\((\d+),\s*(\d+)', onclick_val)
            if param_match:
                days_left, threshold = int(param_match.group(1)), int(param_match.group(2))

            renew_btn.click()
            renew_executed = True
            time.sleep(3)

            # 检测限制弹窗 (原版逻辑)
            restriction_h3 = driver.execute_script("var el = document.querySelector('.fixed.inset-0 h3'); return el ? el.textContent.strip() : '';")
            if 'Renewal Restricted' in restriction_h3:
                restricted = True
                print(f"[INFO] ⚠️ 触发限制弹窗 (剩余 {days_left} 天)")
                driver.click("xpath", "//button[contains(text(),'OK')]")
            else:
                # 正常续期流程: Invoice -> Pay
                modal_selector = f"div#renewService-{sid}"
                driver.wait_for_element_visible(modal_selector, timeout=10)
                driver.click(f"{modal_selector} button[type='submit']")
                time.sleep(5) # 等待 Invoice 生成
                
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                take_screenshot(driver, "13-invoice-page")

                pay_clicked = driver.execute_script("""
                    var btn = document.querySelector('button[type="submit"]');
                    if(btn && btn.innerText.includes('Pay')) { btn.click(); return true; }
                    return false;
                """)
                if pay_clicked:
                    print("[INFO] ✅ Pay 按钮已点击")
                    time.sleep(5)

        except Exception as e:
            print(f"[ERROR] 续期过程出错: {e}")
            raise e

        # 6. 验证结果
        driver.get(manage_url)
        time.sleep(3)
        due_date_after_raw, due_date_after_std = get_current_due_date(driver)
        final_screenshot = take_screenshot(driver, "16-final-result")

        # 7. 判断结果
        if restricted: result_status = "ℹ️ 暂无可续期"
        elif due_date_before_std and due_date_after_std and due_date_after_std > due_date_before_std:
            result_status = "✅ 续订成功"
        else: result_status = "❌ 续订失败"

        # 8. 发送通知
        change_info = f"{due_date_before_raw} → {due_date_after_raw}" if due_date_before_raw != due_date_after_raw else due_date_after_raw
        extra_info = f"\n剩余: {days_left} 天 (需 ≤{threshold} 天可续)" if restricted else ""
        tg_caption = (f"{result_status}\n\n账号: `{HIDEN_EMAIL}`\n服务器: `Free Server #{sid}`\n到期: {change_info}{extra_info}\n时间: {get_bj_time()}")
        send_tg_notification(tg_caption, photo_path=final_screenshot)

    except Exception as e:
        print(f"[ERROR] ❌ 执行失败: {e}")
        send_tg_notification(f"❌ HidenCloud 续期失败\n错误: {str(e)[:100]}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
