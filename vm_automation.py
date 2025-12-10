"""VM automation using Playwright for noVNC interaction."""
import logging
import time
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext


logger = logging.getLogger(__name__)


class VMAutomationError(Exception):
    """Exception raised for VM automation errors."""
    pass


class VMAutomation:
    """Automate Windows Server operations via noVNC."""

    def __init__(
        self,
        screenshot_dir: str = "screenshots",
        headless: bool = False,
        llm_client=None,
        show_password: bool = False,
        pause_before_login: bool = False,
        pause_duration: int = 30,
        max_retries: int = 2
    ):
        """
        Initialize VM automation.

        Args:
            screenshot_dir: Directory to save screenshots
            headless: Run browser in headless mode
            llm_client: Optional LLM client for vision-based verification
            show_password: Show password characters as they are typed (for debugging)
            pause_before_login: Pause after typing password for manual verification
            pause_duration: Duration of pause in seconds
            max_retries: Maximum number of retries for failed verification steps
        """
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.llm_client = llm_client
        self.show_password = show_password
        self.pause_before_login = pause_before_login
        self.pause_duration = pause_duration
        self.max_retries = max_retries

        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        self.screenshots: List[str] = []
        self.action_log: List[Dict[str, Any]] = []
        self.verification_results: List[Dict[str, Any]] = []

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def start(self):
        """Start browser and Playwright."""
        logger.info("Starting Playwright browser")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        self.context = self.browser.new_context(
            viewport={"width": 1920, "height": 1080}
        )
        self.page = self.context.new_page()
        logger.info("Browser started successfully")

    def close(self):
        """Close browser and cleanup."""
        logger.info("Closing browser")
        if self.page:
            self.page.close()
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        logger.info("Browser closed")

    def connect_to_vm(self, novnc_url: str, wait_time: int = 15) -> bool:
        """
        Connect to VM via noVNC URL.

        Args:
            novnc_url: noVNC URL from Slide API
            wait_time: Time to wait for connection in seconds

        Returns:
            True if connected successfully
        """
        logger.info(f"Connecting to VM via noVNC: {novnc_url}")

        try:
            # Use 'domcontentloaded' instead of 'networkidle' because noVNC
            # maintains active WebSocket connections that prevent networkidle
            self.page.goto(novnc_url, wait_until="domcontentloaded", timeout=60000)

            # Wait for noVNC to fully load and connect
            logger.info("Waiting for noVNC to connect...")
            time.sleep(wait_time)

            # Take initial screenshot
            self._capture_screenshot("01_novnc_connected")

            logger.info("Successfully connected to VM via noVNC")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to VM: {e}")
            raise VMAutomationError(f"Failed to connect to VM: {e}") from e

    def wait_for_windows_desktop(self, timeout: int = 90) -> bool:
        """
        Wait for Windows desktop to be ready.

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            True if desktop is ready
        """
        logger.info("Waiting for Windows desktop to be ready")
        logger.info(f"Waiting {timeout} seconds for Windows to boot...")

        # Wait for Windows to fully boot
        # TODO: Could use OCR or image detection to check for desktop
        time.sleep(timeout)

        self._capture_screenshot("02_windows_desktop")
        logger.info("Windows desktop should be ready")
        return True

    def login_windows(
        self,
        username: str,
        password: str,
        wait_after_login: int = 15,
        max_wait_for_login_screen: int = 60
    ) -> bool:
        """
        Login to Windows Server.

        Args:
            username: Windows username
            password: Windows password
            wait_after_login: Wait time after login in seconds
            max_wait_for_login_screen: Maximum time to wait for login screen

        Returns:
            True if login successful
        """
        logger.info(f"Logging into Windows as {username}")

        try:
            # Wait for login screen to be ready (using LLM verification if available)
            logger.info("Waiting for Windows login screen to appear...")
            login_screen_ready = False
            attempts = 0
            max_attempts = max_wait_for_login_screen // 10  # Check every 10 seconds

            while not login_screen_ready and attempts < max_attempts:
                attempts += 1
                logger.info(f"Checking for login screen (attempt {attempts}/{max_attempts})...")

                # Send Ctrl+Alt+Del to bring up login screen
                if attempts == 1 or attempts % 3 == 0:  # Try every 3rd attempt
                    self._log_action("Send Ctrl+Alt+Del", "Bringing up login screen")
                    self._send_ctrl_alt_del()
                    time.sleep(5)

                # Take screenshot and verify with LLM if available
                screenshot_path, verification = self._capture_screenshot(
                    f"03_login_screen_check_{attempts}",
                    verify_state="A Windows login screen showing username and password fields. "
                                 "Note: This is being viewed through VNC/noVNC remote access, which is expected and correct. "
                                 "Look for login credentials fields, not whether it's 'native' Windows."
                )

                if verification and verification.get("verified"):
                    logger.info(f"[OK] Login screen is ready! ({verification.get('confidence')} confidence)")
                    logger.info(f"  AI saw: {verification.get('description')}")
                    login_screen_ready = True
                    break
                elif verification:
                    logger.warning(f"Login screen not ready yet. AI saw: {verification.get('description')}")
                    time.sleep(10)  # Wait before checking again
                else:
                    # No LLM available, assume ready after waiting
                    logger.warning("No LLM verification available, assuming login screen is ready")
                    time.sleep(10)
                    login_screen_ready = True
                    break

            if not login_screen_ready:
                logger.error("Login screen did not appear within timeout period")
                raise VMAutomationError("Login screen did not appear - cannot proceed with verification")

            logger.info("Login screen confirmed ready - detecting which fields are visible...")

            # Detect which login fields are present using AI
            field_detection = None
            if self.llm_client:
                field_detection = self.llm_client.detect_login_fields(screenshot_path)
                logger.info(f"AI detected fields: {field_detection.get('description')}")

                # If detection failed (empty response), assume password-only (username usually cached)
                if not field_detection.get('description') or (
                    not field_detection.get('has_username') and not field_detection.get('has_password')
                ):
                    logger.warning("Field detection failed or returned empty - assuming password-only login")
                    field_detection = {'has_username': False, 'has_password': True, 'description': 'Fallback: password only'}
            else:
                logger.warning("No LLM available - assuming password-only login (username usually cached)")
                field_detection = {'has_username': False, 'has_password': True, 'description': 'No LLM: password only'}

            # Check if displayed username matches expected username
            if field_detection and field_detection.get('displayed_username'):
                displayed_user = field_detection.get('displayed_username')
                logger.info(f"Displayed username on screen: {displayed_user}")

                # Strip domain prefix if present (e.g., "DOMAIN\username" -> "username")
                displayed_user_clean = displayed_user.split('\\')[-1] if '\\' in displayed_user else displayed_user
                username_clean = username.split('\\')[-1] if '\\' in username else username

                # Compare displayed username with expected username (case-insensitive)
                if displayed_user_clean.lower() == username_clean.lower():
                    # Cached username matches expected - use it!
                    logger.info(f"[OK] Cached username matches expected: {username}")
                    logger.info("Will use cached user with password-only login")
                    # Force password-only login since username is already correct
                    field_detection = {
                        'has_username': False,
                        'has_password': True,
                        'displayed_username': displayed_user,
                        'description': f'Cached user matches: {displayed_user}'
                    }
                else:
                    # Username mismatch - try to switch users
                    logger.warning(f"Username mismatch detected!")
                    logger.warning(f"  Expected: {username} (clean: {username_clean})")
                    logger.warning(f"  Displayed: {displayed_user} (clean: {displayed_user_clean})")
                    logger.info("Attempting to switch users...")

                    # Press Escape to go back to user selection
                    self.page.keyboard.press("Escape")
                    time.sleep(3)

                    # Take a screenshot before clicking
                    self._capture_screenshot("03b_before_other_user_click")

                    # Click "Other user" option - try multiple locations
                    # Windows typically shows this at bottom left
                    logger.info("Clicking 'Other user' option...")
                    other_user_locations = [
                        (150, 1000),  # Far bottom left
                        (200, 950),   # Bottom left
                        (150, 950),   # Left middle-bottom
                        (200, 1020),  # Bottom left lower
                        (100, 1000),  # Far left bottom
                    ]

                    for i, (x, y) in enumerate(other_user_locations, 1):
                        logger.info(f"Attempt {i}/{len(other_user_locations)}: Clicking VNC coords ({x}, {y})")
                        self._click_vnc_at_coordinates(x, y)
                        time.sleep(1)

                    # Wait for the screen to change
                    logger.info("Waiting 10 seconds for 'Other user' screen to appear...")
                    time.sleep(10)

                    # Take screenshot and re-detect fields
                    logger.info("Re-detecting login fields after user switch attempt...")
                    screenshot_path_switch, _ = self._capture_screenshot("03c_after_other_user_click")

                    if self.llm_client:
                        field_detection = self.llm_client.detect_login_fields(screenshot_path_switch)
                        logger.info(f"AI re-detected fields: {field_detection.get('description')}")

                        # Check if we got both fields
                        if field_detection.get('has_username') and field_detection.get('has_password'):
                            logger.info("[OK] Successfully switched to 'Other user' - both fields now visible")
                        else:
                            logger.warning("[WARN] Both fields not detected after switch attempt")
                            logger.warning("Will proceed with whatever fields are available")
                    else:
                        # No LLM - assume both fields present after clicking
                        logger.warning("No LLM for re-detection - assuming both fields present")
                        field_detection = {'has_username': True, 'has_password': True, 'description': 'After switch: both fields'}

            # Click on the screen to ensure focus
            self._click_vnc_canvas()
            time.sleep(1)

            # Enter credentials based on what fields are present
            if field_detection and not field_detection.get("has_username") and field_detection.get("has_password"):
                # Only password field visible (username cached)
                logger.info("Only password field detected - skipping username entry")
                self._log_action("Enter password", "Typing password (username cached)")

                # Click multiple times to ensure password field has focus
                logger.info("Ensuring password field has focus...")
                self._click_vnc_canvas()
                time.sleep(0.5)
                self._click_vnc_canvas()
                time.sleep(0.5)

                # Click directly on the password field to ensure focus
                logger.info("Clicking directly on password field at VNC coords (960, 560)")
                password_field_x = 960  # Center horizontally
                password_field_y = 560  # Approximate password field location
                self._click_vnc_at_coordinates(password_field_x, password_field_y)
                time.sleep(1)

                # Clear any existing content
                logger.info("Clearing password field...")
                self.page.keyboard.press("Control+A")
                time.sleep(0.3)
                self.page.keyboard.press("Backspace")
                time.sleep(0.5)

                # Type password using keyboard.type() which should work better with VNC
                if self.show_password:
                    logger.warning(f"[DEBUG] Password being typed: '{password}'")
                    logger.warning(f"[DEBUG] Password length: {len(password)} characters")
                    logger.info("Typing password character by character...")
                else:
                    logger.info("Typing password...")

                # Type each character with explicit Shift handling for VNC
                for i, char in enumerate(password):
                    if self.show_password:
                        logger.warning(f"[DEBUG] Typing char {i+1}/{len(password)}: '{char}' (ASCII: {ord(char)})")
                    try:
                        self._type_char_vnc(char)
                        time.sleep(0.15)
                    except Exception as e:
                        logger.warning(f"Failed to type '{char}': {e}")

                time.sleep(1)

                # Pause for manual inspection if requested
                if self.pause_before_login:
                    logger.warning(f"")
                    logger.warning(f"{'='*70}")
                    logger.warning(f"PAUSED FOR MANUAL VERIFICATION")
                    logger.warning(f"{'='*70}")
                    logger.warning(f"Password has been typed.")
                    logger.warning(f"You can now verify the password field before login.")
                    logger.warning(f"")
                    logger.warning(f"Waiting {self.pause_duration} seconds...")
                    logger.warning(f"Script will automatically continue and press Enter to login.")
                    logger.warning(f"{'='*70}")
                    time.sleep(self.pause_duration)
                    logger.info("Pause complete - continuing with login...")
                else:
                    # Brief pause before pressing Enter
                    time.sleep(1)
            else:
                # Both fields present or no LLM detection - enter username and password
                logger.info("Username and password fields detected - entering both")

                # Type username slowly
                self._log_action("Enter username", f"Typing username: {username}")
                logger.info(f"Typing username: {username}")
                for char in username:
                    self.page.keyboard.type(char, delay=200)
                    time.sleep(0.1)
                time.sleep(2)

                # Press Tab to move to password field
                logger.info("Moving to password field...")
                self.page.keyboard.press("Tab")
                time.sleep(2)

                # Clear any existing content in password field
                logger.info("Clearing password field...")
                self.page.keyboard.press("Control+A")
                time.sleep(0.2)
                self.page.keyboard.press("Delete")
                time.sleep(0.5)

                # Type password slowly
                self._log_action("Enter password", "Typing password")
                if self.show_password:
                    logger.warning(f"[DEBUG] Password being typed: '{password}'")
                    logger.warning(f"[DEBUG] Password length: {len(password)} characters")
                    logger.info("Typing password character by character...")
                else:
                    logger.info("Typing password...")

                # Type each character with explicit Shift handling for VNC
                for i, char in enumerate(password):
                    if self.show_password:
                        logger.warning(f"[DEBUG] Typing char {i+1}/{len(password)}: '{char}' (ASCII: {ord(char)})")
                    try:
                        self._type_char_vnc(char)
                        time.sleep(0.15)
                    except Exception as e:
                        logger.warning(f"Failed to type '{char}': {e}")

                time.sleep(1)

                # Pause for manual inspection if requested
                if self.pause_before_login:
                    logger.warning(f"")
                    logger.warning(f"{'='*70}")
                    logger.warning(f"PAUSED FOR MANUAL VERIFICATION")
                    logger.warning(f"{'='*70}")
                    logger.warning(f"Password has been typed.")
                    logger.warning(f"You can now verify the password field before login.")
                    logger.warning(f"")
                    logger.warning(f"Waiting {self.pause_duration} seconds...")
                    logger.warning(f"Script will automatically continue and press Enter to login.")
                    logger.warning(f"{'='*70}")
                    time.sleep(self.pause_duration)
                    logger.info("Pause complete - continuing with login...")
                else:
                    # Brief pause before pressing Enter
                    time.sleep(1)

            # Press Enter to login
            logger.info("Pressing Enter to login...")
            self.page.keyboard.press("Enter")

            # Wait for Windows to process the login
            logger.info(f"Waiting {wait_after_login} seconds for Windows desktop to load...")
            time.sleep(wait_after_login)

            # IMMEDIATELY capture screenshot and verify login succeeded
            logger.info("Verifying login was successful...")
            screenshot_path, verification = self._capture_screenshot(
                "04_login_verify",
                verify_state="Windows desktop with taskbar visible at the bottom, showing the user successfully logged in. "
                             "IMPORTANT: The Shutdown Event Tracker dialog may be present after VSS backup - this is EXPECTED and NORMAL. "
                             "If you see the desktop with taskbar AND optionally a Shutdown Event Tracker dialog, consider this VERIFIED. "
                             "Viewing via VNC is expected. "
                             "FAIL if you see: login screen, password prompt, 'incorrect password', or locked screen."
            )

            # Verify login succeeded
            login_verified = False
            if verification:
                # Check confidence and description
                confidence = verification.get('confidence', 'low')
                description = verification.get('description', '').upper()
                verified = verification.get("verified", False)

                # CHECK SUCCESS INDICATORS FIRST (most reliable)
                if verified:
                    # AI explicitly verified - trust this above all else
                    logger.info("[OK] Login verified - Windows desktop visible")
                    login_verified = True
                elif 'SHUTDOWN EVENT TRACKER' in description or 'SHUTDOWN' in description:
                    # Shutdown Event Tracker is expected after VSS backups
                    logger.info("[OK] Login verified - Desktop visible with expected Shutdown Event Tracker dialog (normal after VSS backup)")
                    logger.info(f"  AI saw: {description}")
                    login_verified = True
                elif 'DESKTOP' in description and 'TASKBAR' in description:
                    # Desktop and taskbar are visible, even if AI said not verified
                    logger.info("[OK] Desktop and taskbar detected - login succeeded")
                    logger.info(f"  AI saw: {description}")
                    login_verified = True
                # Check for ACTUAL login failure indicators (be specific)
                elif 'STILL ON LOGIN' in description or 'SHOWING LOGIN' in description or 'AT LOGIN SCREEN' in description:
                    error_msg = f"Login FAILED - Still on login screen. AI saw: {description}"
                    logger.error(error_msg)
                    raise VMAutomationError(error_msg)
                elif 'INCORRECT PASSWORD' in description or 'PASSWORD INCORRECT' in description or 'WRONG PASSWORD' in description:
                    error_msg = f"Login FAILED - Password incorrect. AI saw: {description}"
                    logger.error(error_msg)
                    raise VMAutomationError(error_msg)
                elif 'LOCKED' in description and 'SCREEN' in description:
                    error_msg = f"Login FAILED - Screen is locked. AI saw: {description}"
                    logger.error(error_msg)
                    raise VMAutomationError(error_msg)
                elif confidence == 'low' or not description:
                    # Low confidence or empty response - be cautious but allow
                    logger.warning(f"[WARN] AI verification inconclusive (confidence: {confidence})")
                    logger.warning(f"[WARN] Assuming login succeeded - check screenshot: {screenshot_path}")
                    login_verified = True
                else:
                    # AI didn't verify and no clear success/failure indicators
                    error_msg = f"Login FAILED - AI verification did not detect Windows desktop. AI saw: {description}"
                    logger.error(error_msg)
                    raise VMAutomationError(error_msg)
            else:
                logger.warning("[WARN] Login success is NOT verified - no LLM available")
                login_verified = True  # Assume success if no LLM available

            # Only proceed with screen lock disable if login verified
            if login_verified:
                # Disable screen lock to prevent auto-lock during testing
                logger.info("Disabling screen lock timeout...")
                try:
                    # Use PowerShell to disable screen timeout
                    self.page.keyboard.press("Meta+R")
                    time.sleep(2)
                    self.page.keyboard.type("powershell", delay=100)
                    time.sleep(1)
                    self.page.keyboard.press("Enter")
                    time.sleep(3)

                    # Disable screen timeout (set to 0 = never)
                    self.page.keyboard.type("powercfg /change monitor-timeout-ac 0", delay=50)
                    self.page.keyboard.press("Enter")
                    time.sleep(1)
                    self.page.keyboard.type("powercfg /change standby-timeout-ac 0", delay=50)
                    self.page.keyboard.press("Enter")
                    time.sleep(1)

                    # Close PowerShell
                    self.page.keyboard.type("exit", delay=100)
                    self.page.keyboard.press("Enter")
                    time.sleep(1)
                    logger.info("[OK] Screen lock timeout disabled")
                except Exception as e:
                    logger.warning(f"Failed to disable screen lock: {e}")

                # Take final screenshot showing logged in desktop
                self._capture_screenshot("04_logged_in")
                logger.info("[OK] Login complete and verified")
                return True
            else:
                raise VMAutomationError("Login verification failed - desktop not detected")
        except VMAutomationError:
            # Re-raise VMAutomationError as-is
            raise
        except Exception as e:
            logger.error(f"Login failed with exception: {e}")
            self._capture_screenshot("04_login_failed")
            raise VMAutomationError(f"Login failed: {e}") from e

    def open_services_manager(self) -> bool:
        """
        Open Windows Service Manager with retry logic.

        Returns:
            True if opened successfully
        """
        logger.info("Opening Service Manager")

        for attempt in range(1, self.max_retries + 1):
            try:
                if attempt > 1:
                    logger.info(f"Retrying Services Manager (attempt {attempt}/{self.max_retries})...")

                # Close Server Manager if it's open (blocks view of Services Manager)
                logger.info("Closing Server Manager window if open...")
                self._click_vnc_canvas()
                time.sleep(1)
                # Try Alt+F4 to close any open window (likely Server Manager)
                self.page.keyboard.press("Alt+F4")
                time.sleep(2)
                self._capture_screenshot(f"05_closed_server_manager_attempt{attempt}")

                # Open Run dialog (Win+R)
                self._log_action("Open Run dialog", "Pressing Win+R")
                self._click_vnc_canvas()
                self.page.keyboard.press("Meta+R")
                time.sleep(2)
                self._capture_screenshot(f"05_run_dialog_attempt{attempt}")

                # Type services.msc
                self._log_action("Launch services.msc", "Typing services.msc")
                self.page.keyboard.type("services.msc", delay=100)
                time.sleep(1)

                # Press Enter
                self.page.keyboard.press("Enter")
                time.sleep(5)

                # Capture screenshot and verify with AI if available
                screenshot_path, verification = self._capture_screenshot(
                    f"06_services_manager_attempt{attempt}",
                    verify_state="Windows Services Manager window showing a list of Windows services with columns "
                                 "like Name, Description, Status, and Startup Type. The window title should say 'Services'. It could be in the background, see if the windows services Icon is available in the taskbar. That would also be a passing grade."
                )

                # Check verification result
                if verification:
                    if verification.get("verified"):
                        logger.info(f"[OK] Services Manager verified - opened successfully on attempt {attempt}")
                        return True
                    else:
                        logger.warning(f"[WARN] Services Manager verification failed on attempt {attempt}")
                        logger.warning(f"  AI saw: {verification.get('description')}")
                        if attempt < self.max_retries:
                            logger.info("Will retry...")
                            # Close any open windows before retry
                            self.page.keyboard.press("Alt+F4")
                            time.sleep(1)
                            continue
                        else:
                            logger.error("Max retries reached - Services Manager verification failed")
                            return False
                else:
                    logger.info("Services Manager opened (no AI verification available)")
                    return True

            except Exception as e:
                logger.error(f"Failed to open Services Manager (attempt {attempt}): {e}")
                self._capture_screenshot(f"06_services_failed_attempt{attempt}")
                if attempt < self.max_retries:
                    continue
                return False

        return False

    def check_service_status(self, service_name: str) -> Dict[str, Any]:
        """
        Check the status of a specific Windows service.

        Args:
            service_name: Name of the service to check

        Returns:
            Dictionary with service status information
        """
        logger.info(f"Checking status of service: {service_name}")

        self._log_action(
            f"Check service: {service_name}",
            f"Searching for service {service_name}"
        )

        # Take screenshot showing the service list
        screenshot_path = self._capture_screenshot(
            f"07_service_{service_name.replace(' ', '_')}"
        )

        # In a real implementation, we would use OCR or vision AI
        # to read the service status from the screenshot
        # For now, we just record that we checked it
        return {
            "service_name": service_name,
            "checked": True,
            "screenshot": screenshot_path,
            "timestamp": datetime.now().isoformat()
        }

    def open_server_manager(self) -> bool:
        """
        Verify Server Manager is visible (it auto-launches on Windows Server by default).

        Returns:
            True if Server Manager is visible
        """
        logger.info("Verifying Server Manager is visible (auto-launches on Server OS)")

        for attempt in range(1, self.max_retries + 1):
            try:
                if attempt > 1:
                    logger.info(f"Retrying Server Manager verification (attempt {attempt}/{self.max_retries})...")

                # Server Manager launches automatically on Windows Server
                # Just verify it's visible on the desktop
                self._log_action("Verify Server Manager", "Checking if Server Manager is visible on desktop")

                # Click on desktop to ensure focus
                self._click_vnc_canvas()
                time.sleep(1)

                # Capture screenshot and verify with AI if available
                screenshot_path, verification = self._capture_screenshot(
                    f"08_server_manager_visible_attempt{attempt}",
                    verify_state="Windows Server Manager application window visible on the desktop, showing the Server Manager Dashboard "
                                 "with sections like Local Server, All Servers, or the Server Manager interface. "
                                 "It may be in the background or foreground."
                )

                # Check verification result
                if verification:
                    if verification.get("verified"):
                        logger.info(f"[OK] Server Manager verified - visible on desktop (attempt {attempt})")
                        return True
                    else:
                        logger.warning(f"[WARN] Server Manager not visible on attempt {attempt}")
                        logger.warning(f"  AI saw: {verification.get('description')}")
                        if attempt < self.max_retries:
                            logger.info("Server Manager may not have launched yet - will retry...")
                            time.sleep(3)
                            continue
                        else:
                            logger.error("Max retries reached - Server Manager not visible")
                            logger.error("This may be expected if Server Manager was disabled from auto-launch")
                            return False
                else:
                    logger.info("Server Manager check complete (no AI verification available)")
                    return True

            except Exception as e:
                logger.error(f"Failed to verify Server Manager (attempt {attempt}): {e}")
                self._capture_screenshot(f"08_server_manager_check_failed_attempt{attempt}")
                if attempt < self.max_retries:
                    continue
                return False

        return False

    def run_powershell_command(self, command: str) -> bool:
        """
        Run a PowerShell command via cmd.exe → powershell.exe → command.
        Uses the same reliable method as interactive PowerShell.

        Args:
            command: PowerShell command to execute

        Returns:
            True if command executed successfully
        """
        logger.info(f"Running PowerShell command via cmd.exe: {command}")

        for attempt in range(1, self.max_retries + 1):
            try:
                if attempt > 1:
                    logger.info(f"Retrying PowerShell command (attempt {attempt}/{self.max_retries})...")

                # Open Run dialog
                self._log_action("Open Run dialog", "Pressing Win+R")
                self._click_vnc_canvas()
                time.sleep(1)

                logger.info("Pressing Win+R to open Run dialog")
                self.page.keyboard.press("Meta+R")
                time.sleep(3)

                # Verify Run dialog opened with AI
                screenshot_path, verification = self._capture_screenshot(
                    f"09_run_dialog_opened_attempt{attempt}",
                    verify_state="Windows Run dialog box is open on the screen, showing a text input field "
                                 "with 'Open:' label. The dialog should have OK and Cancel buttons."
                )

                if verification:
                    description = verification.get('description', '').upper()

                    # Check if screen is locked
                    if 'CTRL+ALT+DELETE' in description or 'UNLOCK' in description or 'LOCK SCREEN' in description:
                        logger.error(f"[FAIL] Screen is locked! AI saw: {description}")
                        logger.error("Screen locked during test - this indicates Windows auto-lock is enabled")
                        logger.error("The test will fail. Please disable screen lock before running tests.")
                        return False

                    if not verification.get("verified"):
                        logger.error(f"[FAIL] Run dialog did not open on attempt {attempt}")
                        logger.error(f"  AI saw: {description}")
                        if attempt < self.max_retries:
                            logger.info("Will retry opening Run dialog...")
                            time.sleep(2)
                            continue
                        else:
                            logger.error("Max retries reached - Run dialog never opened")
                            return False
                    else:
                        logger.info("[OK] Run dialog is open and ready")
                else:
                    logger.warning("No AI verification - assuming Run dialog is open")

                # Type cmd.exe directly (Run dialog text field has focus by default)
                logger.info("Typing cmd.exe in Run dialog (text field should have focus)")
                self.page.keyboard.type("cmd.exe", delay=100)
                time.sleep(1)

                self._capture_screenshot(f"09_run_dialog_typed_cmd_attempt{attempt}")

                # Press Enter to launch cmd
                logger.info("Pressing Enter to launch cmd.exe")
                self.page.keyboard.press("Enter")
                logger.info("Waiting 20 seconds for cmd.exe to open...")
                time.sleep(20)  # Wait for cmd to open

                # Capture screenshot of cmd window
                self._capture_screenshot(f"09_cmd_window_opened_attempt{attempt}")

                # Type powershell.exe in cmd
                self._log_action("Launch PowerShell from cmd", "Typing powershell.exe in cmd")
                logger.info("Typing powershell.exe in cmd window")
                self.page.keyboard.type("powershell.exe", delay=100)
                time.sleep(1)

                # Press Enter to launch PowerShell
                self.page.keyboard.press("Enter")
                logger.info("Waiting 10 seconds for PowerShell to launch...")
                time.sleep(10)  # Wait for PowerShell to launch

                # Verify PowerShell prompt is visible (informational only)
                screenshot_path, verification = self._capture_screenshot(
                    f"09_powershell_prompt_ready_attempt{attempt}",
                    verify_state="Command window showing PowerShell prompt (PS C:\\...> or similar). "
                                 "The PowerShell prompt should be visible in the terminal window. "
                                 "Note: PowerShell is running inside cmd.exe, so there will be NO blue background."
                )

                if verification:
                    if verification.get("verified"):
                        logger.info(f"[OK] PowerShell prompt verified by AI")
                    else:
                        logger.info(f"[INFO] AI could not verify PowerShell prompt - continuing anyway")
                        logger.info(f"  AI saw: {verification.get('description') or 'empty response'}")
                else:
                    logger.info("[INFO] No AI verification - continuing")

                # Type the command in PowerShell character-by-character
                # This ensures special characters like | are typed correctly through VNC
                self._log_action(f"Execute command: {command}", f"Typing command in PowerShell")
                logger.info(f"Typing command in PowerShell: {command}")
                for char in command:
                    try:
                        self._type_char_vnc(char)
                        time.sleep(0.05)
                    except Exception as e:
                        logger.warning(f"Failed to type '{char}': {e}")
                time.sleep(1)

                # Press Enter to execute
                self.page.keyboard.press("Enter")
                time.sleep(4)  # Wait for command to execute

                # Capture and verify command output
                screenshot_path, verification = self._capture_screenshot(
                    f"10_powershell_command_executed_attempt{attempt}",
                    verify_state=f"Terminal window showing PowerShell output after executing '{command}'. "
                                 f"The command should show its output/results. "
                                 f"Note: This is PowerShell running inside cmd.exe, so NO blue background expected. "
                                 f"IMPORTANT: ONLY mark as FAIL if you see RED TEXT indicating an error, or if the terminal shows "
                                 f"actual error messages (like 'cannot be found', 'access denied', etc.). "
                                 f"If you see normal command output (even if white/gray text), mark as VERIFIED."
                )

                # Check verification result and detect errors
                command_has_error = False
                if verification:
                    description = verification.get('description', '').upper()

                    # Check for negations first - if AI says "NO ERROR" or "NO RED", don't flag as error
                    negation_phrases = [
                        'NO RED',
                        'NO ERROR',
                        'NO ERRORS',
                        'WITHOUT ERROR',
                        'WITHOUT RED'
                    ]

                    has_negation = any(neg in description for neg in negation_phrases)

                    # Only fail if AI explicitly says there's RED error text or shows actual error output
                    # AND there's no negation phrase
                    if not has_negation:
                        error_indicators = [
                            'RED TEXT',
                            'RED ERROR',
                            'ERROR TEXT IN RED',
                            'ERROR MESSAGE IS DISPLAYED',
                            'ERROR MESSAGE IS VISIBLE',
                            'DISPLAYS AN ERROR MESSAGE',
                            'SHOWS AN ERROR MESSAGE',
                            'ACCESS IS DENIED',
                            'PERMISSION IS DENIED',
                            'THE TERMINAL SHOWS THE ERROR OUTPUT'
                        ]

                        for indicator in error_indicators:
                            if indicator in description:
                                command_has_error = True
                                logger.error(f"[FAIL] PowerShell command error detected on attempt {attempt}")
                                logger.error(f"  Error indicator: '{indicator}'")
                                logger.error(f"  AI saw: {description[:300]}...")
                                break

                    if not command_has_error and verification.get("verified"):
                        logger.info(f"[OK] PowerShell command verified by AI - output visible")
                    elif not command_has_error:
                        logger.info(f"[OK] No errors detected in command output")
                        logger.info(f"  AI saw: {description[:200]}...")
                else:
                    logger.info("[INFO] No AI verification - assuming command executed successfully")

                # If error detected and we have retries left, retry
                if command_has_error:
                    if attempt < self.max_retries:
                        logger.warning(f"Retrying due to detected error (attempt {attempt + 1}/{self.max_retries})")
                        self.page.keyboard.press("Alt+F4")
                        time.sleep(2)
                        continue
                    else:
                        logger.error(f"PowerShell command failed after {self.max_retries} attempts")
                        self.page.keyboard.press("Alt+F4")
                        time.sleep(1)
                        return False

                # Success - close terminal window and return
                time.sleep(2)
                self.page.keyboard.press("Alt+F4")
                time.sleep(1)
                logger.info("PowerShell command completed successfully")
                return True

            except Exception as e:
                logger.error(f"Failed to execute PowerShell command (attempt {attempt}): {e}")
                self._capture_screenshot(f"10_command_failed_attempt{attempt}")
                if attempt < self.max_retries:
                    continue
                return False

        return False

    def run_powershell_interactive(self, command: str) -> bool:
        """
        Run a PowerShell command interactively (Win+R > cmd.exe > powershell.exe > type command).
        Opens cmd first, then launches PowerShell from cmd, then runs the command.

        Args:
            command: PowerShell command to execute

        Returns:
            True if command executed successfully
        """
        logger.info(f"Running PowerShell command interactively via cmd.exe: {command}")

        for attempt in range(1, self.max_retries + 1):
            try:
                if attempt > 1:
                    logger.info(f"Retrying interactive PowerShell (attempt {attempt}/{self.max_retries})...")

                # Open Run dialog
                self._log_action("Open Run dialog", "Pressing Win+R")
                self._click_vnc_canvas()
                time.sleep(1)

                logger.info("Pressing Win+R to open Run dialog")
                self.page.keyboard.press("Meta+R")
                time.sleep(3)

                # Verify Run dialog opened with AI
                screenshot_path, verification = self._capture_screenshot(
                    f"09_run_dialog_opened_attempt{attempt}",
                    verify_state="Windows Run dialog box is open on the screen, showing a text input field "
                                 "with 'Open:' label. The dialog should have OK and Cancel buttons."
                )

                if verification:
                    description = verification.get('description', '').upper()

                    # Check if screen is locked
                    if 'CTRL+ALT+DELETE' in description or 'UNLOCK' in description or 'LOCK SCREEN' in description:
                        logger.error(f"[FAIL] Screen is locked! AI saw: {description}")
                        logger.error("Screen locked during test - this indicates Windows auto-lock is enabled")
                        logger.error("The test will fail. Please disable screen lock before running tests.")
                        return False

                    if not verification.get("verified"):
                        logger.error(f"[FAIL] Run dialog did not open on attempt {attempt}")
                        logger.error(f"  AI saw: {description}")
                        if attempt < self.max_retries:
                            logger.info("Will retry opening Run dialog...")
                            time.sleep(2)
                            continue
                        else:
                            logger.error("Max retries reached - Run dialog never opened")
                            return False
                    else:
                        logger.info("[OK] Run dialog is open and ready")
                else:
                    logger.warning("No AI verification - assuming Run dialog is open")

                # Type cmd.exe directly (Run dialog text field has focus by default)
                logger.info("Typing cmd.exe in Run dialog (text field should have focus)")
                self.page.keyboard.type("cmd.exe", delay=100)
                time.sleep(1)

                self._capture_screenshot(f"09_run_dialog_typed_cmd_attempt{attempt}")

                # Press Enter to launch cmd
                logger.info("Pressing Enter to launch cmd.exe")
                self.page.keyboard.press("Enter")
                logger.info("Waiting 20 seconds for cmd.exe to open...")
                time.sleep(20)  # Wait for cmd to open

                # Capture screenshot of cmd window
                self._capture_screenshot(f"09_cmd_window_opened_attempt{attempt}")

                # Type powershell.exe in cmd
                self._log_action("Launch PowerShell from cmd", "Typing powershell.exe in cmd")
                logger.info("Typing powershell.exe in cmd window")
                self.page.keyboard.type("powershell.exe", delay=100)
                time.sleep(1)

                # Press Enter to launch PowerShell
                self.page.keyboard.press("Enter")
                logger.info("Waiting 10 seconds for PowerShell to launch...")
                time.sleep(10)  # Wait for PowerShell to launch

                # Verify PowerShell prompt is visible (informational only)
                screenshot_path, verification = self._capture_screenshot(
                    f"09_powershell_prompt_ready_attempt{attempt}",
                    verify_state="Command window showing PowerShell prompt (PS C:\\...> or similar). "
                                 "The PowerShell prompt should be visible in the terminal window. "
                                 "Note: PowerShell is running inside cmd.exe, so there will be NO blue background."
                )

                if verification:
                    if verification.get("verified"):
                        logger.info(f"[OK] PowerShell prompt verified by AI")
                    else:
                        logger.info(f"[INFO] AI could not verify PowerShell prompt - continuing anyway")
                        logger.info(f"  AI saw: {verification.get('description') or 'empty response'}")
                else:
                    logger.info("[INFO] No AI verification - continuing")

                # Type the command in the PowerShell prompt character-by-character
                # This ensures special characters like | are typed correctly through VNC
                self._log_action(f"Execute command: {command}", f"Typing command in PowerShell")
                logger.info(f"Typing command in PowerShell: {command}")
                for char in command:
                    try:
                        self._type_char_vnc(char)
                        time.sleep(0.05)
                    except Exception as e:
                        logger.warning(f"Failed to type '{char}': {e}")
                time.sleep(1)

                # Press Enter to execute command
                self.page.keyboard.press("Enter")
                time.sleep(4)  # Wait for command to execute

                # Capture and verify command output
                screenshot_path, verification = self._capture_screenshot(
                    f"10_powershell_interactive_output_attempt{attempt}",
                    verify_state=f"Terminal window showing PowerShell output after executing '{command}'. "
                                 f"The command should show its output/results. "
                                 f"Note: This is PowerShell running inside cmd.exe, so NO blue background expected. "
                                 f"IMPORTANT: ONLY mark as FAIL if you see RED TEXT indicating an error, or if the terminal shows "
                                 f"actual error messages (like 'cannot be found', 'access denied', etc.). "
                                 f"If you see normal command output (even if white/gray text), mark as VERIFIED."
                )

                # Check verification result and detect errors
                command_has_error = False
                if verification:
                    description = verification.get('description', '').upper()

                    # Check for negations first - if AI says "NO ERROR" or "NO RED", don't flag as error
                    negation_phrases = [
                        'NO RED',
                        'NO ERROR',
                        'NO ERRORS',
                        'WITHOUT ERROR',
                        'WITHOUT RED'
                    ]

                    has_negation = any(neg in description for neg in negation_phrases)

                    # Only fail if AI explicitly says there's RED error text or shows actual error output
                    # AND there's no negation phrase
                    if not has_negation:
                        error_indicators = [
                            'RED TEXT',
                            'RED ERROR',
                            'ERROR TEXT IN RED',
                            'ERROR MESSAGE IS DISPLAYED',
                            'ERROR MESSAGE IS VISIBLE',
                            'DISPLAYS AN ERROR MESSAGE',
                            'SHOWS AN ERROR MESSAGE',
                            'ACCESS IS DENIED',
                            'PERMISSION IS DENIED',
                            'THE TERMINAL SHOWS THE ERROR OUTPUT'
                        ]

                        for indicator in error_indicators:
                            if indicator in description:
                                command_has_error = True
                                logger.error(f"[FAIL] PowerShell command error detected on attempt {attempt}")
                                logger.error(f"  Error indicator: '{indicator}'")
                                logger.error(f"  AI saw: {description[:300]}...")
                                break

                    if not command_has_error and verification.get("verified"):
                        logger.info(f"[OK] Interactive PowerShell command verified by AI - output visible")
                    elif not command_has_error:
                        # No error detected, even if not explicitly verified - treat as success
                        logger.info(f"[OK] No errors detected in command output")
                        logger.info(f"  AI saw: {description[:200]}...")
                else:
                    logger.info("[INFO] No AI verification - assuming command executed successfully")

                # If error detected and we have retries left, retry
                if command_has_error:
                    if attempt < self.max_retries:
                        logger.warning(f"Retrying due to detected error (attempt {attempt + 1}/{self.max_retries})")
                        # Close the terminal before retrying
                        self.page.keyboard.press("Alt+F4")
                        time.sleep(2)
                        continue
                    else:
                        logger.error(f"PowerShell command failed after {self.max_retries} attempts")
                        logger.error(f"Last error: Command produced error output")
                        # Close terminal and return failure
                        self.page.keyboard.press("Alt+F4")
                        time.sleep(1)
                        return False

                # Success - close terminal window and return
                time.sleep(2)
                self.page.keyboard.press("Alt+F4")
                time.sleep(1)
                logger.info("Interactive PowerShell command completed successfully")
                return True

            except Exception as e:
                logger.error(f"Failed to execute interactive PowerShell command (attempt {attempt}): {e}")
                self._capture_screenshot(f"10_interactive_powershell_failed_attempt{attempt}")
                if attempt < self.max_retries:
                    continue
                return False

        return False

    def perform_custom_steps(
        self,
        steps: List[str],
        step_delay: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Perform custom automation steps interpreted by LLM.
        Takes plain text descriptions and uses LLM to generate PowerShell commands.

        Args:
            steps: List of plain text step descriptions (e.g., "ping localhost", "check disk space")
            step_delay: Delay between steps in seconds

        Returns:
            List of step results
        """
        results = []

        for i, step in enumerate(steps, 1):
            logger.info(f"Performing custom step {i}/{len(steps)}: {step}")
            self._log_action(f"Custom Step {i}", step)

            try:
                # Use LLM to convert plain text to PowerShell command
                if self.llm_client:
                    logger.info(f"Asking LLM to generate PowerShell command for: {step}")

                    prompt = f"""Convert the following task description into a single PowerShell command that can be executed in a Windows terminal.

Task: {step}

Requirements:
- Return ONLY the PowerShell command, no explanations
- Command should be safe to execute
- Command should produce visible output
- Keep it simple and direct

Example:
Task: ping localhost
Response: ping 127.0.0.1 -n 4

Task: check disk space
Response: Get-PSDrive C | Select-Object Used,Free

Now generate the command for the task above:"""

                    messages = [
                        {
                            "role": "system",
                            "content": "You are a PowerShell expert. Generate safe, simple PowerShell commands for given tasks. Return only the command, no explanations."
                        },
                        {"role": "user", "content": prompt}
                    ]

                    powershell_cmd = self.llm_client.chat(messages, temperature=0.2).strip()

                    # Remove any markdown code blocks if present
                    if powershell_cmd.startswith("```"):
                        powershell_cmd = powershell_cmd.split("\n")[1]
                    if powershell_cmd.endswith("```"):
                        powershell_cmd = powershell_cmd.rsplit("\n", 1)[0]

                    logger.info(f"LLM generated command: {powershell_cmd}")
                else:
                    logger.warning("No LLM client available - skipping custom step execution")
                    powershell_cmd = None

                # Execute the PowerShell command if we have one
                if powershell_cmd:
                    success = self.run_powershell_interactive(powershell_cmd)

                    results.append({
                        "step_number": len(results) + 1,
                        "description": f"Custom: {step} (executed: {powershell_cmd})",
                        "success": success,
                        "timestamp": datetime.now().isoformat()
                    })
                else:
                    # No LLM - just capture current state
                    self._click_vnc_canvas()
                    time.sleep(1)

                    screenshot_path, verification = self._capture_screenshot(
                        f"custom_step_{i:02d}",
                        verify_state=f"Desktop showing the result of: {step}"
                    )

                    results.append({
                        "step_number": len(results) + 1,
                        "description": f"Custom: {step} (no automation - screenshot only)",
                        "success": True,
                        "screenshot": screenshot_path,
                        "timestamp": datetime.now().isoformat()
                    })

                time.sleep(step_delay)

            except Exception as e:
                logger.error(f"Custom step {i} failed: {e}")
                results.append({
                    "step_number": len(results) + 1,
                    "description": f"Custom: {step}",
                    "success": False,
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                })

        return results

    def _click_vnc_canvas(self):
        """Click on the VNC canvas to ensure it has focus."""
        try:
            # Look for common noVNC canvas selectors
            canvas_selectors = [
                "canvas#noVNC_canvas",
                "canvas",
                "#noVNC_screen",
                ".noVNC_canvas"
            ]

            for selector in canvas_selectors:
                try:
                    canvas = self.page.query_selector(selector)
                    if canvas:
                        canvas.click()
                        return
                except:
                    continue

            # If no canvas found, click center of page
            self.page.mouse.click(960, 540)
        except Exception as e:
            logger.warning(f"Failed to click VNC canvas: {e}")

    def _click_vnc_at_coordinates(self, x: int, y: int):
        """
        Click at specific coordinates within the VNC canvas.

        Args:
            x: X coordinate within the VNC screen (e.g., 960 for center of 1920px width)
            y: Y coordinate within the VNC screen (e.g., 540 for center of 1080px height)
        """
        try:
            # Look for common noVNC canvas selectors
            canvas_selectors = [
                "canvas#noVNC_canvas",
                "canvas",
                "#noVNC_screen",
                ".noVNC_canvas"
            ]

            canvas = None
            for selector in canvas_selectors:
                try:
                    canvas = self.page.query_selector(selector)
                    if canvas:
                        break
                except:
                    continue

            if canvas:
                # Get the canvas bounding box
                bbox = canvas.bounding_box()
                if bbox:
                    # Calculate scale factor (canvas display size vs VNC resolution)
                    # Assuming VNC is 1920x1080
                    vnc_width = 1920
                    vnc_height = 1080

                    scale_x = bbox['width'] / vnc_width
                    scale_y = bbox['height'] / vnc_height

                    # Calculate actual click position
                    click_x = bbox['x'] + (x * scale_x)
                    click_y = bbox['y'] + (y * scale_y)

                    logger.debug(f"Clicking VNC at ({x}, {y}) -> page coords ({click_x:.1f}, {click_y:.1f})")
                    self.page.mouse.click(click_x, click_y)
                    return
                else:
                    logger.warning("Could not get canvas bounding box, clicking on canvas center")
                    canvas.click()
                    return
            else:
                logger.warning("VNC canvas not found, clicking page center")
                self.page.mouse.click(960, 540)

        except Exception as e:
            logger.error(f"Failed to click VNC at coordinates ({x}, {y}): {e}")
            # Fallback to clicking canvas
            self._click_vnc_canvas()

    def _send_ctrl_alt_del(self):
        """Send Ctrl+Alt+Del to the VM."""
        try:
            # Look for Ctrl+Alt+Del button in noVNC interface
            cad_selectors = [
                "button:has-text('Ctrl+Alt+Del')",
                "button[title*='Ctrl+Alt+Del']",
                "#noVNC_cad_button"
            ]

            for selector in cad_selectors:
                try:
                    button = self.page.query_selector(selector)
                    if button:
                        button.click()
                        return
                except:
                    continue

            # Fallback: try keyboard combination
            logger.warning("Ctrl+Alt+Del button not found, using keyboard")
            self._click_vnc_canvas()
            # Note: Real Ctrl+Alt+Del may not work in browser
            # noVNC usually provides a button for this
        except Exception as e:
            logger.error(f"Failed to send Ctrl+Alt+Del: {e}")

    def _type_char_with_shift(self, char: str):
        """
        Type a character with proper Shift key handling for special characters.

        Args:
            char: Single character to type
        """
        # Characters that require Shift on US keyboard
        shift_chars = {
            '!': '1', '@': '2', '#': '3', '$': '4', '%': '5',
            '^': '6', '&': '7', '*': '8', '(': '9', ')': '0',
            '_': '-', '+': '=', '{': '[', '}': ']', '|': '\\',
            ':': ';', '"': "'", '<': ',', '>': '.', '?': '/',
            '~': '`'
        }

        try:
            if char.isupper():
                # Uppercase letter - use Shift
                self.page.keyboard.press(f"Shift+{char.lower()}")
                time.sleep(0.1)
            elif char in shift_chars:
                # Special character requiring Shift
                base_key = shift_chars[char]
                self.page.keyboard.press(f"Shift+{base_key}")
                time.sleep(0.1)
            else:
                # Regular character
                self.page.keyboard.press(char)
                time.sleep(0.1)
        except Exception as e:
            logger.warning(f"Failed to type character '{char}': {e}")

    def _type_char_vnc(self, char: str):
        """
        Type a character through VNC with explicit Shift handling.
        Uses keyboard.down/up for Shift to work properly through VNC.

        Args:
            char: Single character to type
        """
        # Characters that require Shift on US keyboard
        shift_chars = {
            '!': '1', '@': '2', '#': '3', '$': '4', '%': '5',
            '^': '6', '&': '7', '*': '8', '(': '9', ')': '0',
            '_': '-', '+': '=', '{': '[', '}': ']', '|': '\\',
            ':': ';', '"': "'", '<': ',', '>': '.', '?': '/',
            '~': '`'
        }

        try:
            if char.isupper():
                # Uppercase letter - hold Shift, type lowercase, release Shift
                self.page.keyboard.down('Shift')
                time.sleep(0.05)
                self.page.keyboard.type(char.lower(), delay=50)
                time.sleep(0.05)
                self.page.keyboard.up('Shift')
            elif char in shift_chars:
                # Special character - hold Shift, type base key, release Shift
                base_key = shift_chars[char]
                self.page.keyboard.down('Shift')
                time.sleep(0.05)
                self.page.keyboard.type(base_key, delay=50)
                time.sleep(0.05)
                self.page.keyboard.up('Shift')
            else:
                # Regular character - just type it
                self.page.keyboard.type(char, delay=50)
        except Exception as e:
            logger.warning(f"Failed to type character '{char}': {e}")

    def _get_page_coords_from_vnc(self, vnc_x: int, vnc_y: int) -> tuple[float, float]:
        """
        Convert VNC coordinates to page coordinates.

        Args:
            vnc_x: X coordinate in VNC screen (0-1920)
            vnc_y: Y coordinate in VNC screen (0-1080)

        Returns:
            Tuple of (page_x, page_y) coordinates
        """
        try:
            canvas_selectors = ["canvas#noVNC_canvas", "canvas", "#noVNC_screen", ".noVNC_canvas"]

            for selector in canvas_selectors:
                try:
                    canvas = self.page.query_selector(selector)
                    if canvas:
                        bbox = canvas.bounding_box()
                        if bbox:
                            vnc_width = 1920
                            vnc_height = 1080
                            scale_x = bbox['width'] / vnc_width
                            scale_y = bbox['height'] / vnc_height
                            page_x = bbox['x'] + (vnc_x * scale_x)
                            page_y = bbox['y'] + (vnc_y * scale_y)
                            return (page_x, page_y)
                except:
                    continue

            # Fallback to VNC coords if canvas not found
            return (float(vnc_x), float(vnc_y))
        except Exception as e:
            logger.warning(f"Failed to convert VNC coords: {e}")
            return (float(vnc_x), float(vnc_y))


    def _capture_screenshot(self, name: str, verify_state: Optional[str] = None) -> tuple[str, Optional[Dict]]:
        """
        Capture a screenshot and optionally verify UI state with LLM.

        Args:
            name: Screenshot name (without extension)
            verify_state: Optional expected UI state to verify

        Returns:
            Tuple of (screenshot path, verification result dict or None)
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{name}.png"
        filepath = self.screenshot_dir / filename

        try:
            self.page.screenshot(path=str(filepath), full_page=True)
            logger.debug(f"Screenshot saved: {filepath}")
            self.screenshots.append(str(filepath))

            # Verify UI state if requested and LLM client is available
            verification = None
            if verify_state and self.llm_client:
                logger.info(f"Verifying UI state: {verify_state}")
                try:
                    verification = self.llm_client.verify_ui_state(
                        str(filepath),
                        verify_state
                    )
                    self.verification_results.append({
                        "screenshot": str(filepath),
                        "expected": verify_state,
                        "verification": verification
                    })

                    if verification.get("verified"):
                        logger.info(f"[OK] Verified: {verify_state} ({verification.get('confidence')} confidence)")
                    else:
                        logger.warning(f"[FAIL] NOT Verified: {verify_state}")
                        logger.warning(f"  LLM saw: {verification.get('description')}")
                except Exception as e:
                    logger.error(f"Verification failed: {e}")

            return str(filepath), verification
        except Exception as e:
            logger.error(f"Failed to capture screenshot: {e}")
            return "", None

    def _log_action(self, action: str, details: str):
        """
        Log an action to the action log.

        Args:
            action: Action name
            details: Action details
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details
        }
        self.action_log.append(entry)
        logger.debug(f"Action: {action} - {details}")

    def get_screenshots(self) -> List[str]:
        """Get list of screenshot paths."""
        return self.screenshots.copy()

    def get_action_log(self) -> List[Dict[str, Any]]:
        """Get action log."""
        return self.action_log.copy()

    def get_verification_results(self) -> List[Dict[str, Any]]:
        """Get AI verification results."""
        return self.verification_results.copy()
