"""
Tencent Cloud Free Trial Auto-Claim Bot
Run this bot on Windows to automatically claim free trial VPS at scheduled time.

Usage:
    python tencent_trial_bot.py [--now] [--time HH:MM] [--config CONFIG_PATH]
    
Examples:
    python tencent_trial_bot.py           # Run at 23:00 WIB by default
    python tencent_trial_bot.py --now     # Run immediately
    python tencent_trial_bot.py --time 22:55  # Run at 22:55
"""

import argparse
import time
import logging
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import (
    TimeoutException, 
    NoSuchElementException,
    ElementClickInterceptedException,
    WebDriverException
)

# ==================== CONFIGURATION ====================

# Default config path
DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

# Logging setup
LOG_FILE = os.path.join(os.path.dirname(__file__), "tencent_trial.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ==================== CONFIG CLASS ====================

class Config:
    """Configuration manager for the bot"""
    
    DEFAULT_CONFIG = {
        "tencent": {
            "username": "",      # Tencent account username (phone/email)
            "password": "",      # Tencent account password
            "login_method": "phone",  # "phone" or "email"
        },
        "chromedriver": {
            "path": "",          # Path to chromedriver (leave empty for auto-download)
            "headless": False,   # Run in headless mode (set to False for Windows)
            "user_data_dir": "", # Chrome user data dir for cookies (optional)
        },
        "scheduler": {
            "target_time": "23:00",  # Target time in HH:MM format (WIB)
            "timezone": "Asia/Jakarta",
            "retry_interval": 30,    # Seconds between retries if failed
            "max_retries": 10,       # Max retry attempts
            "pre_refresh_seconds": 180,  # Start refreshing N seconds before target time
        },
        "trial": {
            "page_url": "https://www.tencentcloud.com/act/pro/FreeTier",
            "target_spec": "2核2G3M",  # Target spec to claim
            "region": "ap-singapore",  # Target region (optional)
        },
        "telegram": {
            "enabled": False,
            "bot_token": "",
            "chat_id": ""
        }
    }
    
    def __init__(self, config_path: str = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.config = self._load_config()
    
    def _load_config(self) -> dict:
        """Load config from file or create default"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                logger.info(f"Loaded config from {self.config_path}")
                return self._merge_config(config)
            except Exception as e:
                logger.warning(f"Failed to load config: {e}, using defaults")
        
        self._save_config(self.DEFAULT_CONFIG)
        logger.info(f"Created default config at {self.config_path}")
        logger.info("Please edit config.json with your Tencent account credentials!")
        return self.DEFAULT_CONFIG
    
    def _merge_config(self, config: dict) -> dict:
        """Merge loaded config with defaults"""
        merged = self.DEFAULT_CONFIG.copy()
        for key, value in config.items():
            if isinstance(value, dict) and key in merged:
                merged[key].update(value)
            else:
                merged[key] = value
        return merged
    
    def _save_config(self, config: dict):
        """Save config to file"""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    
    def get(self, key: str, default=None):
        """Get config value using dot notation"""
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k, default)
            else:
                return default
        return value

# ==================== TENCENT BOT ====================

class TencentTrialBot:
    """Bot to automatically claim Tencent Cloud free trials"""
    
    def __init__(self, config: Config):
        self.config = config
        self.driver = None
        self.running = True
        self.success = False
    
    def setup_driver(self):
        """Setup Chrome driver"""
        chrome_options = Options()
        
        if self.config.get('chromedriver.headless', False):
            chrome_options.add_argument('--headless=new')
        
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        driver_path = self.config.get('chromedriver.path')
        
        try:
            if driver_path and os.path.exists(driver_path):
                service = Service(executable_path=driver_path)
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
            else:
                self.driver = webdriver.Chrome(options=chrome_options)
            
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
            })
            
            logger.info("Chrome driver initialized successfully")
            return True
            
        except WebDriverException as e:
            logger.error(f"Failed to initialize Chrome driver: {e}")
            return False
    
    def wait_for_login(self, timeout: int = 300) -> bool:
        """Wait for user to login manually"""
        logger.info("Waiting for login... Please login to your Tencent Cloud account")
        logger.info(f"Will wait up to {timeout} seconds...")
        
        wait = WebDriverWait(self.driver, timeout)
        try:
            wait.until(lambda d: 'console' in d.current_url.lower() or 
                               'console' in d.current_url.lower() or
                               'FreeTier' in d.current_url)
            logger.info("Login detected!")
            return True
        except TimeoutException:
            logger.error("Login timeout")
            return False
    
    def login(self) -> bool:
        """Attempt to login with credentials"""
        username = self.config.get('tencent.username')
        password = self.config.get('tencent.password')
        
        if not username or not password:
            logger.warning("No credentials provided, will wait for manual login")
            return False
        
        try:
            self.driver.get("https://cloud.tencent.com/login")
            time.sleep(3)
            
            login_method = self.config.get('tencent.login_method', 'phone')
            
            if login_method == 'phone':
                try:
                    phone_tab = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, "//span[contains(text(), '手机号')]"))
                    )
                    phone_tab.click()
                    time.sleep(1)
                except:
                    pass
                
                phone_input = self.driver.find_element(By.ID, "username")
                phone_input.send_keys(username)
            else:
                email_input = self.driver.find_element(By.ID, "username")
                email_input.send_keys(username)
            
            password_input = self.driver.find_element(By.ID, "password")
            password_input.send_keys(password)
            
            login_btn = self.driver.find_element(By.XPATH, "//button[@type='submit']")
            login_btn.click()
            
            time.sleep(5)
            
            if 'console' in self.driver.current_url.lower():
                logger.info("Login successful!")
                return True
            
            return False
            
        except Exception as e:
            logger.warning(f"Auto-login failed: {e}")
            return False
    
    def navigate_to_freetier(self) -> bool:
        """Navigate to FreeTier page"""
        try:
            url = self.config.get('trial.page_url', 'https://www.tencentcloud.com/act/pro/FreeTier')
            logger.info(f"Navigating to {url}")
            self.driver.get(url)
            time.sleep(5)
            
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            logger.info("FreeTier page loaded")
            return True
            
        except Exception as e:
            logger.error(f"Failed to navigate to FreeTier page: {e}")
            return False
    
    def click_get_started(self) -> bool:
        """Click Get Started button"""
        try:
            logger.info("Looking for Get Started button...")
            time.sleep(2)
            
            # Try multiple selectors for Get Started
            selectors = [
                "//button[contains(text(), 'Get Started')]",
                "//button[contains(text(), '立即试用')]",
                "//button[contains(text(), '开始使用')]",
                "//a[contains(text(), 'Get Started')]",
                "//span[contains(text(), 'Get Started')]",
                "//div[contains(text(), 'Get Started')]",
            ]
            
            for selector in selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, selector)
                    for elem in elements:
                        if elem.is_displayed():
                            logger.info(f"Found Get Started button: {elem.text}")
                            self.driver.execute_script("arguments[0].scrollIntoView(true);", elem)
                            time.sleep(0.5)
                            self.driver.execute_script("arguments[0].click();", elem)
                            time.sleep(3)
                            logger.info("Clicked Get Started")
                            return True
                except:
                    continue
            
            # Try to find any prominent button
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                try:
                    text = btn.text.lower()
                    if 'get start' in text or '试用' in text or '开始' in text:
                        logger.info(f"Found button: {btn.text}")
                        self.driver.execute_script("arguments[0].click();", btn)
                        time.sleep(3)
                        return True
                except:
                    continue
            
            logger.warning("Get Started button not found")
            return False
            
        except Exception as e:
            logger.error(f"Error clicking Get Started: {e}")
            return False
    
    def create_vps(self) -> bool:
        """Create VPS instance"""
        try:
            logger.info("Creating VPS...")
            time.sleep(3)
            
            target_spec = self.config.get('trial.target_spec', '2核2G3M')
            logger.info(f"Looking for spec: {target_spec}")
            
            # Wait for page to load
            time.sleep(5)
            
            # Find and click the target spec card
            # Try to find cards containing the target spec
            cards = self.driver.find_elements(By.XPATH, 
                "//div[contains(@class, 'card') or contains(@class, 'item') or contains(@class, 'product')]")
            
            for card in cards:
                try:
                    text = card.text
                    if target_spec in text:
                        logger.info(f"Found matching spec card")
                        
                        # Find and click the button in this card
                        buttons = card.find_elements(By.TAG_NAME, "button")
                        for btn in buttons:
                            btn_text = btn.text
                            if 'Try' in btn_text or '试用' in btn_text or 'Create' in btn_text or '购买' in btn_text:
                                logger.info(f"Clicking: {btn_text}")
                                self.driver.execute_script("arguments[0].click();", btn)
                                time.sleep(3)
                                return self.handle_create_flow()
                except Exception as e:
                    logger.debug(f"Card error: {e}")
                    continue
            
            # Alternative: Find all buttons with target spec text
            logger.info("Trying alternative search...")
            xpath_buttons = [
                f"//button[contains(text(), '{target_spec}')]",
                f"//span[contains(text(), '{target_spec}')]",
                f"//div[contains(text(), '{target_spec}')]"
            ]
            
            for xpath in xpath_buttons:
                try:
                    elements = self.driver.find_elements(By.XPATH, xpath)
                    for elem in elements:
                        try:
                            parent = elem.find_element(By.XPATH, "./..")
                            buttons = parent.find_elements(By.TAG_NAME, "button")
                            for btn in buttons:
                                logger.info(f"Found related button: {btn.text}")
                                self.driver.execute_script("arguments[0].click();", btn)
                                time.sleep(3)
                                return self.handle_create_flow()
                        except:
                            continue
                except:
                    continue
            
            logger.warning("Could not find VPS creation option")
            return False
            
        except Exception as e:
            logger.error(f"Error creating VPS: {e}")
            return False
    
    def handle_create_flow(self) -> bool:
        """Handle the VPS creation flow"""
        try:
            logger.info("Handling create flow...")
            time.sleep(5)
            
            # Click Continue or Next buttons
            next_buttons = [
                "Continue", "下一步", "Next", "确认", "Create", "立即创建",
                "Submit", "提交", "Purchase", "购买"
            ]
            
            for btn_text in next_buttons:
                try:
                    buttons = self.driver.find_elements(By.XPATH, 
                        f"//button[contains(text(), '{btn_text}')]")
                    for btn in buttons:
                        if btn.is_displayed():
                            logger.info(f"Clicking: {btn_text}")
                            self.driver.execute_script("arguments[0].click();", btn)
                            time.sleep(3)
                except:
                    continue
            
            # Check for success
            return self.check_creation_result()
            
        except Exception as e:
            logger.error(f"Error in create flow: {e}")
            return False
    
    def check_creation_result(self) -> bool:
        """Check if VPS creation was successful"""
        try:
            time.sleep(5)
            page_source = self.driver.page_source
            
            success_indicators = [
                'Created', '创建成功', '申请成功', '已开通', 
                'success', 'Complete', '完成', '已创建'
            ]
            
            for indicator in success_indicators:
                if indicator in page_source:
                    logger.info(f"SUCCESS! VPS Created: {indicator}")
                    self.success = True
                    self._send_notification("Tencent Cloud VPS Created Successfully!")
                    return True
            
            # Check URL
            current_url = self.driver.current_url.lower()
            if 'success' in current_url or 'complete' in current_url or 'created' in current_url:
                logger.info("SUCCESS! Appears to be on success page")
                self.success = True
                return True
            
            # Check if we have an instance running
            if 'console' in current_url and 'instance' in current_url:
                logger.info("SUCCESS! On instance console page")
                self.success = True
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking result: {e}")
            return False
    
    def retry_all(self, max_retries: int = 10) -> bool:
        """Retry entire flow multiple times"""
        for attempt in range(1, max_retries + 1):
            logger.info(f"=== Attempt {attempt}/{max_retries} ===")
            
            # Go back to FreeTier page
            if not self.navigate_to_freetier():
                logger.warning("Failed to load FreeTier page")
                time.sleep(5)
                continue
            
            # Click Get Started
            if not self.click_get_started():
                logger.warning("Failed to click Get Started")
                time.sleep(5)
                continue
            
            # Create VPS
            if self.create_vps():
                return True
            
            # Wait before retry
            wait_time = 10 if attempt < 5 else 30
            logger.info(f"Retrying in {wait_time} seconds...")
            time.sleep(wait_time)
        
        return False
    
    def _send_notification(self, message: str):
        """Send notification via Telegram"""
        if not self.config.get('telegram.enabled', False):
            return
            
        try:
            import requests
            bot_token = self.config.get('telegram.bot_token')
            chat_id = self.config.get('telegram.chat_id')
            
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {"chat_id": chat_id, "text": message}
            
            requests.post(url, data=data, timeout=10)
            logger.info("Telegram notification sent")
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")
    
    def run(self, immediate: bool = False):
        """Main run loop"""
        logger.info("=" * 50)
        logger.info("Tencent Cloud Trial Bot Started")
        logger.info("=" * 50)
        
        if not self.setup_driver():
            return
        
        try:
            # Navigate to FreeTier
            if not self.navigate_to_freetier():
                logger.error("Failed to navigate to FreeTier")
                return
            
            # Try to login if credentials provided
            if not self.login():
                if not self.wait_for_login():
                    logger.error("Login failed/timeout")
                    return
            
            # Wait for target time if not immediate
            if not immediate:
                self.wait_for_target_time()
            
            # Refresh page
            logger.info("Refreshing page and starting creation...")
            self.navigate_to_freetier()
            time.sleep(3)
            
            # Click Get Started
            self.click_get_started()
            time.sleep(3)
            
            # Create VPS
            if self.retry_all(self.config.get('scheduler.max_retries', 10)):
                logger.info("=" * 50)
                logger.info("VPS CREATION SUCCESS!")
                logger.info("=" * 50)
            else:
                logger.warning("VPS creation failed - all attempts exhausted")
                
        except KeyboardInterrupt:
            logger.info("Bot interrupted by user")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup()
    
    def wait_for_target_time(self):
        """Wait until target time"""
        target_time = self.config.get('scheduler.target_time', '23:00')
        pre_refresh = self.config.get('scheduler.pre_refresh_seconds', 180)
        
        target_hour, target_minute = map(int, target_time.split(':'))
        
        while self.running:
            now = datetime.now()
            
            target_dt = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
            
            if target_dt <= now:
                target_dt += timedelta(days=1)
            
            refresh_time = target_dt - timedelta(seconds=pre_refresh)
            
            if now >= refresh_time:
                logger.info(f"Reached refresh time, starting...")
                break
            
            wait_seconds = (refresh_time - now).total_seconds()
            hours = int(wait_seconds // 3600)
            minutes = int((wait_seconds % 3600) // 60)
            
            logger.info(f"Waiting for {target_time}... ({hours}h {minutes}m remaining)")
            time.sleep(min(60, wait_seconds))
    
    def cleanup(self):
        """Clean up resources"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Chrome driver closed")
            except:
                pass

# ==================== MAIN ====================

def main():
    parser = argparse.ArgumentParser(description='Tencent Cloud Free Trial Bot')
    parser.add_argument('--now', action='store_true', help='Run immediately')
    parser.add_argument('--time', type=str, help='Target time in HH:MM format')
    parser.add_argument('--config', type=str, help='Path to config file')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    
    args = parser.parse_args()
    
    config = Config(args.config)
    
    if args.time:
        config.config['scheduler']['target_time'] = args.time
    if args.headless:
        config.config['chromedriver']['headless'] = True
    
    bot = TencentTrialBot(config)
    bot.run(immediate=args.now)

if __name__ == "__main__":
    main()