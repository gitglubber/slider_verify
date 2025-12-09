"""
Slide Verify - Automated VM Verification System

This application uses the Slide API to:
1. Get the most recent snapshot
2. Boot a restore VM with network-none
3. Use Playwright to interact with the VM via noVNC
4. Perform automated verification steps (login, check services, etc.)
5. Generate a comprehensive report with screenshots
6. Destroy the VM to clean up
"""
import logging
import sys
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from config import get_settings
from slide_client import SlideClient, SlideAPIError
from llm_client import LLMClient
from vm_automation import VMAutomation, VMAutomationError
from report_generator import ReportGenerator


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('verification.log')
    ]
)
logger = logging.getLogger(__name__)


class VerificationOrchestrator:
    """Orchestrate the complete VM verification workflow."""

    def __init__(self):
        """Initialize the orchestrator with all necessary clients."""
        logger.info("Initializing Verification Orchestrator")

        # Load settings
        self.settings = get_settings()

        # Initialize clients
        self.slide_client = SlideClient(
            api_key=self.settings.slide_api_key,
            base_url=self.settings.slide_api_base_url
        )

        self.llm_client = LLMClient(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_api_base_url,
            model=self.settings.openai_model
        )

        self.report_generator = ReportGenerator(
            output_dir=self.settings.report_output_dir
        )

        # State tracking
        self.vm_id: Optional[str] = None
        self.snapshot_info: Optional[dict] = None
        self.agent_info: Optional[dict] = None
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None

    def run_verification_for_all_agents(
        self,
        headless: bool = False,
        custom_steps: Optional[List[str]] = None
    ) -> List[dict]:
        """
        Run verification for the most recent snapshot of each agent.

        Args:
            headless: Run browser in headless mode
            custom_steps: Optional custom verification steps

        Returns:
            List of verification results for each agent
        """
        logger.info("="*70)
        logger.info("Running Verification for All Agents")
        logger.info("="*70)

        # Get latest snapshots for all agents
        logger.info("Retrieving latest snapshots for all agents...")
        snapshots_by_agent = self.slide_client.get_latest_snapshots_by_agent()

        if not snapshots_by_agent:
            logger.error("No snapshots found for any agents")
            return []

        logger.info(f"Found {len(snapshots_by_agent)} agents to verify")

        results = []
        for agent_id, snapshot in snapshots_by_agent.items():
            logger.info("="*70)
            logger.info(f"Starting verification for agent: {agent_id}")
            logger.info(f"Snapshot: {snapshot.get('snapshot_id')}")
            logger.info("="*70)

            # Set snapshot info for this verification
            self.snapshot_info = snapshot

            # Run verification for this agent
            result = self.run_verification(
                agent_id=agent_id,
                headless=headless,
                custom_steps=custom_steps
            )

            result["agent_id"] = agent_id
            results.append(result)

            # Brief pause between agents
            if len(snapshots_by_agent) > 1:
                logger.info("Pausing briefly before next agent...")
                import time
                time.sleep(5)

        # Summary
        logger.info("="*70)
        logger.info("All Agent Verifications Complete")
        logger.info("="*70)
        successful = sum(1 for r in results if r.get("success"))
        logger.info(f"Results: {successful}/{len(results)} agents verified successfully")

        for result in results:
            status = "[OK]" if result.get("success") else "[FAIL]"
            logger.info(f"  {status} Agent {result.get('agent_id')}: {result.get('snapshot_id', 'N/A')}")

        return results

    def run_verification(
        self,
        agent_id: Optional[str] = None,
        headless: bool = False,
        custom_steps: Optional[List[str]] = None,
        show_password: bool = False,
        pause_before_login: bool = False,
        pause_duration: int = 30,
        ps_commands: Optional[List[str]] = None
    ) -> dict:
        """
        Run the complete verification workflow.

        Args:
            agent_id: Optional agent ID to filter snapshots
            headless: Run browser in headless mode
            custom_steps: Optional custom verification steps
            show_password: Show password characters as they are typed (for debugging)

        Returns:
            Dictionary with verification results and report paths
        """
        self.start_time = datetime.now()
        logger.info("="*70)
        logger.info("Starting VM Verification Workflow")
        logger.info("="*70)

        try:
            # Step 1: Get latest snapshot
            logger.info("Step 1: Retrieving latest snapshot")
            self.snapshot_info = self._get_latest_snapshot(agent_id)
            if not self.snapshot_info:
                raise ValueError("No snapshot found")

            # Get agent details for better reporting
            snapshot_agent_id = self.snapshot_info.get("agent_id")
            if snapshot_agent_id:
                try:
                    self.agent_info = self.slide_client.get_agent_details(snapshot_agent_id)
                    logger.info(
                        f"Agent: {self.agent_info.get('hostname', 'Unknown')} "
                        f"({self.agent_info.get('os', 'Unknown OS')})"
                    )
                except Exception as e:
                    logger.warning(f"Could not fetch agent details: {e}")
                    self.agent_info = None

            # Step 2: Create and start VM
            logger.info("Step 2: Creating VM from snapshot")
            vm_info = self._create_and_start_vm()

            # Step 3: Get noVNC URL
            logger.info("Step 3: Retrieving noVNC access URL")
            novnc_url = self._get_novnc_url()

            # Step 4: Perform automated verification
            logger.info("Step 4: Performing automated verification")
            verification_results = self._perform_verification(
                novnc_url,
                headless,
                custom_steps,
                show_password,
                pause_before_login,
                pause_duration,
                ps_commands
            )

            # Check if login failed
            login_failed = verification_results.get("login_failed", False)

            # Step 5: Generate report (even if login failed)
            logger.info("Step 5: Generating verification report")
            self.end_time = datetime.now()
            report_paths = self._generate_report(
                vm_info,
                verification_results
            )

            if login_failed:
                logger.error("="*70)
                logger.error("Verification FAILED - Login Unsuccessful")
                logger.error(f"Error: {verification_results.get('error', 'Login verification failed')}")
                logger.error(f"HTML Report: {report_paths['html']}")
                logger.error(f"JSON Report: {report_paths['json']}")
                logger.error("="*70)

                return {
                    "success": False,
                    "login_failed": True,
                    "snapshot_id": self.snapshot_info.get("snapshot_id"),
                    "vm_id": self.vm_id,
                    "reports": report_paths,
                    "results": verification_results,
                    "error": verification_results.get("error", "Login failed")
                }
            else:
                logger.info("="*70)
                logger.info("Verification Completed Successfully")
                logger.info(f"HTML Report: {report_paths['html']}")
                logger.info(f"JSON Report: {report_paths['json']}")
                logger.info("="*70)

                return {
                    "success": True,
                    "snapshot_id": self.snapshot_info.get("snapshot_id"),
                    "vm_id": self.vm_id,
                    "reports": report_paths,
                    "results": verification_results
                }

        except Exception as e:
            logger.error(f"Verification failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

        finally:
            # Step 6: Cleanup - Destroy VM
            if self.vm_id:
                logger.info("Step 6: Cleaning up - Destroying VM")
                self._cleanup_vm()

    def _get_device_id_from_snapshot(self) -> str:
        """
        Extract device_id from snapshot locations.
        Prefers 'cloud' type device for remote access.
        """
        locations = self.snapshot_info.get("locations", [])

        if not locations:
            raise ValueError("Snapshot has no locations/devices")

        # Try to find cloud device first (best for compute availability - cloud slides have 512GB ram)
        for loc in locations:
            if loc.get("type") == "cloud":
                device_id = loc.get("device_id")
                logger.info(f"Using cloud device: {device_id}")
                return device_id

        # Fall back to first available device
        device_id = locations[0].get("device_id")
        device_type = locations[0].get("type", "unknown")
        logger.info(f"Using {device_type} device: {device_id}")
        return device_id

    def _get_latest_snapshot(self, agent_id: Optional[str] = None) -> dict:
        """Get the latest snapshot from Slide API."""
        snapshot = self.slide_client.get_latest_snapshot(agent_id=agent_id)
        if not snapshot:
            raise ValueError("No snapshots available")

        logger.info(
            f"Using snapshot: {snapshot.get('snapshot_id')} "
            f"from {snapshot.get('backup_ended_at', snapshot.get('backup_started_at'))}"
        )
        return snapshot

    def _create_and_start_vm(self) -> dict:
        """Create VM from snapshot and start it."""
        snapshot_id = self.snapshot_info.get("snapshot_id")

        # Get device_id from snapshot locations (prefer cloud type for remote access)
        device_id = self._get_device_id_from_snapshot()

        # Create VM with network-none for isolation
        vm_response = self.slide_client.create_vm(
            snapshot_id=snapshot_id,
            device_id=device_id,
            network="network-none",
            name=f"verify_{snapshot_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )

        self.vm_id = vm_response.get("virt_id")
        logger.info(f"VM created: {self.vm_id}")

        # VM starts automatically, wait for it to be ready
        logger.info("Waiting for VM to be ready (starts automatically)...")
        if not self.slide_client.wait_for_vm_ready(
            self.vm_id,
            timeout=self.settings.vm_boot_timeout
        ):
            raise VMAutomationError("VM failed to become ready within timeout period")

        # Get VM details
        vm_details = self.slide_client.get_vm_details(self.vm_id)
        logger.info(f"VM state: {vm_details.get('state')}")

        return vm_details

    def _get_novnc_url(self) -> str:
        """Get noVNC URL for the VM."""
        novnc_url = self.slide_client.get_vnc_url(self.vm_id)
        if not novnc_url:
            raise VMAutomationError("Failed to get noVNC URL")

        logger.info(f"noVNC URL obtained: {novnc_url[:50]}...")
        return novnc_url

    def _perform_verification(
        self,
        novnc_url: str,
        headless: bool,
        custom_steps: Optional[List[str]] = None,
        show_password: bool = False,
        pause_before_login: bool = False,
        pause_duration: int = 30,
        ps_commands: Optional[List[str]] = None
    ) -> dict:
        """Perform the automated verification steps."""
        steps_completed = []

        with VMAutomation(
            screenshot_dir=self.settings.screenshot_dir,
            headless=headless,
            llm_client=self.llm_client,  # Pass LLM client for vision verification
            show_password=show_password,  # Pass debug flag
            pause_before_login=pause_before_login,  # Pass pause flag
            pause_duration=pause_duration  # Pass pause duration
        ) as vm_auto:
            # Connect to VM
            logger.info("Connecting to VM via noVNC")
            vm_auto.connect_to_vm(novnc_url, wait_time=10)
            steps_completed.append({
                "step_number": 1,
                "description": "Connected to VM via noVNC",
                "success": True,
                "timestamp": datetime.now().isoformat()
            })

            # Wait for Windows desktop - give it plenty of time to boot
            logger.info("Waiting for Windows desktop")
            vm_auto.wait_for_windows_desktop(timeout=120)
            steps_completed.append({
                "step_number": 2,
                "description": "Windows desktop loaded",
                "success": True,
                "timestamp": datetime.now().isoformat()
            })

            # Login to Windows - wait for login screen to be ready first
            logger.info("Logging into Windows")
            login_success = False
            try:
                vm_auto.login_windows(
                    username=self.settings.windows_username,
                    password=self.settings.windows_password,
                    max_wait_for_login_screen=self.settings.vm_login_screen_timeout
                )
                login_success = True
                logger.info("[OK] Login successful!")

                steps_completed.append({
                    "step_number": 3,
                    "description": f"Login as {self.settings.windows_username} "
                                 f"({'verified by AI' if self.llm_client else 'unverified'})",
                    "success": True,
                    "timestamp": datetime.now().isoformat()
                })
            except VMAutomationError as e:
                logger.error(f"[FAIL] Login failed: {e}")
                steps_completed.append({
                    "step_number": 3,
                    "description": f"Login as {self.settings.windows_username} FAILED",
                    "success": False,
                    "timestamp": datetime.now().isoformat()
                })

                # Get screenshots and action log even on login failure
                all_screenshots = vm_auto.get_screenshots()
                screenshots = []
                include_from_here = False
                for screenshot in all_screenshots:
                    # Start including from any login-related screenshot
                    if "03_login" in screenshot or "04_login" in screenshot or "04_logged" in screenshot:
                        include_from_here = True
                    if include_from_here:
                        screenshots.append(screenshot)

                action_log = vm_auto.get_action_log()

                logger.error(f"Login failed - generating failure report with {len(screenshots)} screenshots")

                # Return early with login failure documented
                return {
                    "steps_completed": steps_completed,
                    "screenshots": screenshots if screenshots else all_screenshots,  # Include all if none matched filter
                    "action_log": action_log,
                    "login_failed": True,
                    "error": str(e)
                }

            # Login successful - continue with remaining verification steps
            if not login_success:
                # This shouldn't happen but just in case
                logger.error("Login did not succeed - stopping verification")
                return {
                    "steps_completed": steps_completed,
                    "screenshots": vm_auto.get_screenshots(),
                    "action_log": vm_auto.get_action_log(),
                    "login_failed": True
                }
            # Run PowerShell commands if provided
            if ps_commands and len(ps_commands) > 0:
                for i, ps_cmd in enumerate(ps_commands, 1):
                    logger.info(f"Running PowerShell command {i}/{len(ps_commands)}: {ps_cmd}")
                    ps_success = vm_auto.run_powershell_interactive(ps_cmd)
                    steps_completed.append({
                        "step_number": len(steps_completed) + 1,
                        "description": f"Execute PowerShell command {i}: {ps_cmd}",
                        "success": ps_success,
                        "timestamp": datetime.now().isoformat()
                    })
            else:
                logger.info("No PowerShell commands specified - skipping PowerShell verification")

            # Perform custom steps if provided
            if custom_steps:
                logger.info(f"Performing {len(custom_steps)} custom steps")
                custom_results = vm_auto.perform_custom_steps(custom_steps)
                steps_completed.extend(custom_results)

            # Get screenshots and action log
            # Filter screenshots to only include from login onwards (04_logged_in and after)
            all_screenshots = vm_auto.get_screenshots()
            screenshots = []
            include_from_here = False
            for screenshot in all_screenshots:
                # Start including from the first "04_logged_in" screenshot
                if "04_logged_in" in screenshot or "04_login" in screenshot:
                    include_from_here = True
                if include_from_here:
                    screenshots.append(screenshot)

            logger.info(f"Filtered screenshots: {len(all_screenshots)} total -> {len(screenshots)} included in report")
            action_log = vm_auto.get_action_log()

            logger.info(
                f"Verification complete: {len(steps_completed)} steps, "
                f"{len(screenshots)} screenshots"
            )

            return {
                "steps_completed": steps_completed,
                "screenshots": screenshots,
                "action_log": action_log
            }

    def _generate_report(self, vm_info: dict, verification_results: dict) -> dict:
        """Generate verification report."""
        # Get test summary
        logger.info("Generating BCDR test summary")
        try:
            llm_summary = self.llm_client.analyze_verification_results(
                steps_completed=verification_results["steps_completed"],
                screenshots=verification_results["screenshots"]
            )
        except Exception as e:
            logger.warning(f"Failed to generate test summary: {e}")
            llm_summary = "Test summary not available"

        # Generate reports
        report_paths = self.report_generator.generate_report(
            snapshot_info=self.snapshot_info,
            vm_info=vm_info,
            agent_info=self.agent_info,
            action_log=verification_results["action_log"],
            screenshots=verification_results["screenshots"],
            steps_completed=verification_results["steps_completed"],
            llm_summary=llm_summary,
            start_time=self.start_time,
            end_time=self.end_time
        )

        # Print quick summary
        duration = str(self.end_time - self.start_time) if self.end_time else None
        quick_summary = self.report_generator.generate_quick_summary(
            verification_results["steps_completed"],
            duration
        )
        print(quick_summary)

        return report_paths

    def _cleanup_vm(self):
        """Destroy the VM and clean up resources."""
        if not self.vm_id:
            return

        logger.info(f"Destroying VM: {self.vm_id}")
        try:
            success = self.slide_client.destroy_vm(self.vm_id)
            if success:
                logger.info("VM destroyed successfully")
            else:
                logger.warning("Failed to destroy VM")
        except Exception as e:
            logger.error(f"Error destroying VM: {e}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Slide Verify - Automated VM Verification System"
    )
    parser.add_argument(
        "--agent-id",
        help="Agent ID to filter snapshots (omit to verify all agents)",
        default=None
    )
    parser.add_argument(
        "--all-agents",
        help="Verify the most recent snapshot for ALL agents",
        action="store_true"
    )
    parser.add_argument(
        "--headless",
        help="Run browser in headless mode",
        action="store_true"
    )
    parser.add_argument(
        "--steps",
        help="Custom verification steps (comma-separated)",
        default=None
    )
    parser.add_argument(
        "--username",
        help="Windows username (overrides WINDOWS_USERNAME from .env)",
        default=None
    )
    parser.add_argument(
        "--password",
        help="Windows password (overrides WINDOWS_PASSWORD from .env)",
        default=None
    )
    parser.add_argument(
        "--show-password",
        help="Show password characters as they are typed (for debugging)",
        action="store_true"
    )
    parser.add_argument(
        "--pause",
        help="Pause after typing password to allow manual verification",
        action="store_true"
    )
    parser.add_argument(
        "--pause-duration",
        help="Duration of pause in seconds (default: 30)",
        type=int,
        default=30
    )
    parser.add_argument(
        "--ps-cmd-1",
        help="First PowerShell command to run interactively (Win+R > powershell.exe > run command)",
        default=None
    )
    parser.add_argument(
        "--ps-cmd-2",
        help="Second PowerShell command to run interactively (Win+R > powershell.exe > run command)",
        default=None
    )
    parser.add_argument(
        "--ps-cmd-3",
        help="Third PowerShell command to run interactively (Win+R > powershell.exe > run command)",
        default=None
    )

    args = parser.parse_args()

    # Parse custom steps
    custom_steps = None
    if args.steps:
        custom_steps = [s.strip() for s in args.steps.split(",")]

    # Collect PowerShell commands into a list
    ps_commands = []
    if args.ps_cmd_1:
        ps_commands.append(args.ps_cmd_1)
    if args.ps_cmd_2:
        ps_commands.append(args.ps_cmd_2)
    if args.ps_cmd_3:
        ps_commands.append(args.ps_cmd_3)

    # Run verification
    orchestrator = VerificationOrchestrator()

    # Override credentials if provided via command line
    if args.username:
        orchestrator.settings.windows_username = args.username
        logger.info(f"Using username from command line: {args.username}")
    if args.password:
        orchestrator.settings.windows_password = args.password
        logger.info("Using password from command line")

    if args.all_agents:
        # Run verification for all agents
        results = orchestrator.run_verification_for_all_agents(
            headless=args.headless,
            custom_steps=custom_steps
        )
        # Exit with success if at least one agent verified successfully
        success = any(r.get("success") for r in results)
        sys.exit(0 if success else 1)
    else:
        # Run verification for single agent or latest snapshot
        result = orchestrator.run_verification(
            agent_id=args.agent_id,
            headless=args.headless,
            show_password=args.show_password,
            pause_before_login=args.pause,
            pause_duration=args.pause_duration,
            custom_steps=custom_steps,
            ps_commands=ps_commands
        )
        # Exit with appropriate code
        sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
