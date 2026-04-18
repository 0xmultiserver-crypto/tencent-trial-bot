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
            "max_retries": 3,        # Max retry attempts
            "pre_refresh_seconds": 120,  # Start refreshing N seconds before target time
        },
        "trial": {
            "target_spec": "2核2G3M",  # Target spec to claim (partial match)
            "page_url": "https://cloud.tencent.com/act/pro/free",
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
                # Merge with defaults
                return self._merge_config(config)
            except Exception as e:
                logger.warning(f"Failed to load config: {e}, using defaults")
        
        # Create default config
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
        
        # Chrome options for Windows
        if self.config.get('chromedriver.headless', False):
            chrome_options.add_argument('--headless=new')
        
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # User agent
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        driver_path = self.config.get('chromedriver.path')
        
        try:
            if driver_path and os.path.exists(driver_path):
                service = Service(executable_path=driver_path)
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
            else:
                # Use webdriver-manager or just create without path
                self.driver = webdriver.Chrome(options=chrome_options)
            
            # Anti-detection
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    })
                '''
            })
            
            logger.info("Chrome driver initialized successfully")
            return True
            
        except WebDriverException as e:
            logger.error(f"Failed to initialize Chrome driver: {e}")
            logger.error("Please ensure Chrome is installed and chromedriver is available")
            return False
    
    def wait_for_login(self, timeout: int = 300) -> bool:
        """Wait for user to login manually (if not using credentials)"""
        logger.info("Waiting for login... Please login to your Tencent Cloud account")
        logger.info(f"Will wait up to {timeout} seconds...")
        
        wait = WebDriverWait(self.driver, timeout)
        try:
            # Wait for console to appear (indicates logged in)
            wait.until(lambda d: 'console' in d.current_url.lower() or 
                               'control' in d.current_url.lower() or
                               'cvm' in d.current_url.lower())
            logger.info("Login detected!")
            return True
        except TimeoutException:
            logger.error("Login timeout")
            return False
    
    def login(self) -> bool:
        """Attempt to login with credentials (if provided)"""
        username = self.config.get('tencent.username')
        password = self.config.get('tencent.password')
        
        if not username or not password:
            logger.warning("No credentials provided, will wait for manual login")
            return False
        
        try:
            # Go to login page
            self.driver.get("https://cloud.tencent.com/login")
            time.sleep(2)
            
            # Select login method
            login_method = self.config.get('tencent.login_method', 'phone')
            
            if login_method == 'phone':
                # Click phone tab
                phone_tab = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//span[contains(text(), '手机号')]"))
                )
                phone_tab.click()
                time.sleep(1)
                
                # Enter phone number
                phone_input = self.driver.find_element(By.ID, "username")
                phone_input.send_keys(username)
            else:
                # Email login
                email_input = self.driver.find_element(By.ID, "username")
                email_input.send_keys(username)
            
            # Enter password
            password_input = self.driver.find_element(By.ID, "password")
            password_input.send_keys(password)
            
            # Click login button
            login_btn = self.driver.find_element(By.XPATH, "//button[@type='submit']")
            login_btn.click()
            
            time.sleep(3)
            
            # Check if login successful
            if 'console' in self.driver.current_url.lower():
                logger.info("Login successful!")
                return True
            else:
                logger.warning("Login may have failed, will continue anyway")
                return False
                
        except Exception as e:
            logger.warning(f"Auto-login failed: {e}")
            return False
    
    def navigate_to_trial_page(self) -> bool:
        """Navigate to the free trial page"""
        try:
            url = self.config.get('trial.page_url', 'https://cloud.tencent.com/act/pro/free')
            logger.info(f"Navigating to {url}")
            self.driver.get(url)
            time.sleep(3)
            
            # Wait for page to load
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            logger.info("Trial page loaded")
            return True
            
        except Exception as e:
            logger.error(f"Failed to navigate to trial page: {e}")
            return False
    
    def find_and_click_trial_button(self) -> bool:
        """Find the trial button and click it"""
        try:
            # Find trial cards
            trial_cards = self.driver.find_elements(By.XPATH, 
                "//div[contains(@class, 'trial-card') or contains(@class, 'product-card')]")
            
            target_spec = self.config.get('trial.target_spec', '2核2G3M')
            logger.info(f"Looking for trial with spec: {target_spec}")
            
            for card in trial_cards:
                try:
                    card_text = card.text
                    if target_spec in card_text:
                        logger.info(f"Found matching card: {card_text[:200]}")
                        
                        # Find the 试用 (try) button
                        buttons = card.find_elements(By.XPATH, 
                            ".//button[contains(text(), '试用') or contains(text(), '立即试用')]")
                        
                        for btn in buttons:
                            try:
                                # Scroll to button
                                self.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                                time.sleep(0.5)
                                
                                # Check if button is enabled
                                btn_text = btn.text
                                if '已' in btn_text or '领取' in btn_text:
                                    logger.info(f"Button text: {btn_text}")
                                
                                # Click the button
                                btn.click()
                                logger.info(f"Clicked trial button: {btn_text}")
                                time.sleep(2)
                                
                                # Check for success modal or message
                                return self.check_trial_result()
                                
                            except ElementClickInterceptedException:
                                logger.warning("Button click intercepted, trying JavaScript click")
                                self.driver.execute_script("arguments[0].click();", btn)
                                time.sleep(2)
                                return self.check_trial_result()
                                
                except Exception as e:
                    logger.debug(f"Error processing card: {e}")
                    continue
            
            # Try alternative method - find all buttons with 试用
            logger.info("Trying alternative button search...")
            all_buttons = self.driver.find_elements(By.XPATH, 
                "//button[contains(text(), '试用') and not(contains(text(), '教程'))]")
            
            for btn in all_buttons:
                try:
                    btn_text = btn.text
                    if target_spec in btn_text or '轻量' in btn_text or '服务器' in btn_text:
                        logger.info(f"Found button: {btn_text}")
                        self.driver.execute_script("arguments[0].click();", btn)
                        time.sleep(2)
                        return self.check_trial_result()
                except:
                    continue
            
            logger.warning("No trial button found with target spec")
            return False
            
        except Exception as e:
            logger.error(f"Error finding trial button: {e}")
            return False
    
    def check_trial_result(self) -> bool:
        """Check if trial claim was successful"""
        try:
            time.sleep(2)
            
            # Check for success indicators
            page_source = self.driver.page_source
            
            success_indicators = [
                '申请成功',
                '领取成功', 
                '创建成功',
                '已开通',
                '立即前往'
            ]
            
            for indicator in success_indicators:
                if indicator in page_source:
                    logger.info(f"SUCCESS! Trial claim confirmed: {indicator}")
                    self.success = True
                    self._send_notification("Tencent Cloud Trial Claimed Successfully!")
                    return True
            
            # Check for error messages
            error_indicators = [
                '已领取',
                '已被领取',
                '已抢光',
                '名额已满',
                '来晚了'
            ]
            
            for indicator in error_indicators:
                if indicator in page_source:
                    logger.warning(f"Trial claim failed: {indicator}")
                    return False
            
            # Check current URL
            if 'success' in self.driver.current_url.lower() or 'result' in self.driver.current_url.lower():
                logger.info("Appears to be on success page")
                self.success = True
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking trial result: {e}")
            return False
    
    def retry_claim(self, max_retries: int = 3) -> bool:
        """Retry claiming trial multiple times"""
        for attempt in range(1, max_retries + 1):
            logger.info(f"Attempt {attempt}/{max_retries}")
            
            if self.find_and_click_trial_button():
                return True
            
            if attempt < max_retries:
                logger.info("Retrying in 5 seconds...")
                time.sleep(5)
                self.navigate_to_trial_page()
        
        return False
    
    def _send_notification(self, message: str):
        """Send notification via Telegram (if configured)"""
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
            logger.warning(f"Failed to send Telegram notification: {e}")
    
    def run(self, immediate: bool = False):
        """Main run loop"""
        logger.info("=" * 50)
        logger.info("Tencent Cloud Trial Bot Started")
        logger.info("=" * 50)
        
        # Setup driver
        if not self.setup_driver():
            return
        
        try:
            # Navigate to trial page
            if not self.navigate_to_trial_page():
                logger.error("Failed to navigate to trial page")
                return
            
            # Try to login if credentials provided
            if not self.login():
                # Wait for manual login
                if not self.wait_for_login():
                    logger.error("Login failed/timeout")
                    return
            
            # Wait for target time if not immediate
            if not immediate:
                self.wait_for_target_time()
            
            # Refresh page right before target time
            logger.info("Refreshing trial page...")
            self.navigate_to_trial_page()
            time.sleep(2)
            
            # Try to claim
            if self.retry_claim(self.config.get('scheduler.max_retries', 3)):
                logger.info("=" * 50)
                logger.info("TRIAL CLAIM SUCCESS!")
                logger.info("=" * 50)
            else:
                logger.warning("Trial claim failed - all attempts exhausted")
                
        except KeyboardInterrupt:
            logger.info("Bot interrupted by user")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            self.cleanup()
    
    def wait_for_target_time(self):
        """Wait until target time (or slightly before)"""
        target_time = self.config.get('scheduler.target_time', '23:00')
        pre_refresh = self.config.get('scheduler.pre_refresh_seconds', 120)
        
        target_hour, target_minute = map(int, target_time.split(':'))
        
        while self.running:
            now = datetime.now()
            
            # Calculate target datetime
            target_dt = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
            
            # If target time has passed today, target tomorrow
            if target_dt <= now:
                target_dt += timedelta(days=1)
            
            # Start refreshing N seconds before target
            refresh_time = target_dt - timedelta(seconds=pre_refresh)
            
            if now >= refresh_time:
                logger.info(f"Reached refresh time, will refresh page shortly...")
                break
            
            # Calculate wait time
            wait_seconds = (refresh_time - now).total_seconds()
            hours = int(wait_seconds // 3600)
            minutes = int((wait_seconds % 3600) // 60)
            
            logger.info(f"Waiting for target time {target_time}... ({hours}h {minutes}m remaining)")
            time.sleep(min(60, wait_seconds))  # Sleep max 60 seconds
    
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
    parser = argparse.ArgumentParser(description='Tencent Cloud Free Trial Auto-Claim Bot')
    parser.add_argument('--now', action='store_true', help='Run immediately instead of waiting for scheduled time')
    parser.add_argument('--time', type=str, help='Target time in HH:MM format (default: 23:00)')
    parser.add_argument('--config', type=str, help='Path to config file')
    parser.add_argument('--headless', action='store_true', help='Run Chrome in headless mode')
    
    args = parser.parse_args()
    
    # Load config
    config = Config(args.config)
    
    # Override config with CLI args
    if args.time:
        config.config['scheduler']['target_time'] = args.time
    if args.headless:
        config.config['chromedriver']['headless'] = True
    
    # Create and run bot
    bot = TencentTrialBot(config)
    bot.run(immediate=args.now)

if __name__ == "__main__":
    main()