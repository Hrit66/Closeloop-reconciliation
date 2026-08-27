import json
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

with open("data/test_orders.json") as f:
    orders = json.load(f)

chrome_options = Options()
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option("useAutomationExtension", False)
# chrome_options.add_argument("--headless")  # Uncomment to run headless

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

wait = WebDriverWait(driver, 30)

def pay_order(order_id, amount):
    driver.get("http://localhost:8888/test_checkout.html")
    time.sleep(1)
    
    btn = wait.until(EC.element_to_be_clickable((By.XPATH, f"//button[contains(@onclick, '{order_id}')]")))
    btn.click()
    
    wait.until(EC.frame_to_be_available_and_switch_to_it((By.XPATH, "//iframe[contains(@src, 'razorpay')]")))
    
    wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@placeholder='Card number']"))).send_keys("4111 1111 1111 1111")
    driver.find_element(By.XPATH, "//input[@placeholder='MM/YY']").send_keys("12/30")
    driver.find_element(By.XPATH, "//input[@placeholder='CVV']").send_keys("123")
    driver.find_element(By.XPATH, "//input[@placeholder='Name']").send_keys("Test User")
    
    driver.find_element(By.XPATH, "//button[contains(text(), 'Pay')]").click()
    
    wait.until(EC.alert_is_present())
    alert = driver.switch_to.alert
    alert_text = alert.text
    alert.accept()
    
    driver.switch_to.default_content()
    print(f"  {order_id}: {alert_text}")
    return alert_text

print(f"Auto-paying {len(orders)} orders...")
for i, order in enumerate(orders, 1):
    print(f"[{i}/{len(orders)}] {order['id']} - ₹{order['amount']/100:.2f}")
    try:
        pay_order(order['id'], order['amount'])
    except Exception as e:
        print(f"  ERROR: {e}")
    time.sleep(1)

driver.quit()
print("Done!")