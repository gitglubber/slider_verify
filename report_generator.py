"""Generate verification reports with screenshots and timestamps."""
import logging
import base64
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from jinja2 import Template
import json


logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generate HTML and JSON verification reports."""

    def __init__(self, output_dir: str = "reports"):
        """
        Initialize report generator.

        Args:
            output_dir: Directory to save reports
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_report(
        self,
        snapshot_info: Dict[str, Any],
        vm_info: Dict[str, Any],
        agent_info: Optional[Dict[str, Any]] = None,
        action_log: List[Dict[str, Any]] = None,
        screenshots: List[str] = None,
        steps_completed: List[Dict[str, Any]] = None,
        llm_summary: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Dict[str, str]:
        """
        Generate verification report.

        Args:
            snapshot_info: Snapshot details from Slide API
            vm_info: VM details from Slide API
            action_log: List of actions performed
            screenshots: List of screenshot paths
            steps_completed: List of completed steps with results
            llm_summary: Optional test summary
            start_time: Start time of verification
            end_time: End time of verification

        Returns:
            Dictionary with paths to generated report files
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Calculate duration
        duration = None
        if start_time and end_time:
            duration = str(end_time - start_time)

        # Prepare report data
        report_data = {
            "timestamp": timestamp,
            "start_time": start_time.isoformat() if start_time else None,
            "end_time": end_time.isoformat() if end_time else None,
            "duration": duration,
            "snapshot": snapshot_info,
            "vm": vm_info,
            "agent": agent_info or {},
            "actions": action_log or [],
            "screenshots": screenshots or [],
            "steps": steps_completed or [],
            "summary": llm_summary,
            "success_count": sum(1 for s in (steps_completed or []) if s.get("success")),
            "total_steps": len(steps_completed or [])
        }

        # Generate JSON report
        json_path = self._generate_json_report(report_data, timestamp)

        # Generate HTML report
        html_path = self._generate_html_report(report_data, timestamp)

        logger.info(f"Reports generated: JSON={json_path}, HTML={html_path}")

        return {
            "json": json_path,
            "html": html_path
        }

    def _generate_json_report(
        self,
        report_data: Dict[str, Any],
        timestamp: str
    ) -> str:
        """Generate JSON report."""
        filename = f"verification_report_{timestamp}.json"
        filepath = self.output_dir / filename

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2, default=str)

            logger.info(f"JSON report saved: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.error(f"Failed to generate JSON report: {e}")
            raise

    def _encode_image_to_base64(self, image_path: str) -> str:
        """
        Encode an image file to base64 for embedding in HTML.

        Args:
            image_path: Path to the image file

        Returns:
            Base64 encoded string with data URI prefix
        """
        try:
            with open(image_path, "rb") as img_file:
                encoded = base64.b64encode(img_file.read()).decode('utf-8')
                return f"data:image/png;base64,{encoded}"
        except Exception as e:
            logger.error(f"Failed to encode image {image_path}: {e}")
            return ""

    def _generate_html_report(
        self,
        report_data: Dict[str, Any],
        timestamp: str
    ) -> str:
        """Generate HTML report with embedded screenshots."""
        filename = f"verification_report_{timestamp}.html"
        filepath = self.output_dir / filename

        # Encode all screenshots to base64
        screenshot_data = []
        for screenshot_path in report_data.get("screenshots", []):
            try:
                encoded_image = self._encode_image_to_base64(screenshot_path)
                screenshot_name = Path(screenshot_path).name
                screenshot_data.append({
                    "path": screenshot_path,
                    "name": screenshot_name,
                    "base64": encoded_image
                })
            except Exception as e:
                logger.warning(f"Failed to process screenshot {screenshot_path}: {e}")

        # Add encoded screenshots to report data
        report_data["screenshot_data"] = screenshot_data

        # Load HTML template from file
        template_path = Path(__file__).parent / "templates" / "report_template.html"

        try:
            with open(template_path, "r", encoding="utf-8") as f:
                html_template = f.read()
        except FileNotFoundError:
            logger.error(f"Template file not found: {template_path}")
            raise
        except Exception as e:
            logger.error(f"Failed to load template file: {e}")
            raise

        try:
            template = Template(html_template)
            html_content = template.render(**report_data)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_content)

            logger.info(f"HTML report saved: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.error(f"Failed to generate HTML report: {e}")
            raise

    def generate_quick_summary(
        self,
        steps_completed: List[Dict[str, Any]],
        duration: Optional[str] = None
    ) -> str:
        """
        Generate a quick text summary.

        Args:
            steps_completed: List of completed steps
            duration: Optional duration string

        Returns:
            Text summary
        """
        total = len(steps_completed)
        success = sum(1 for s in steps_completed if s.get("success"))
        success_rate = (success / total * 100) if total > 0 else 0

        summary = f"""
Verification Complete
{'='*50}
Total Steps: {total}
Successful: {success}
Failed: {total - success}
Success Rate: {success_rate:.1f}%
"""

        if duration:
            summary += f"Duration: {duration}\n"

        summary += "\nStep Results:\n"
        for step in steps_completed:
            status = "[OK]" if step.get("success") else "[FAIL]"
            summary += f"  {status} Step {step.get('step_number')}: {step.get('description')}\n"

        return summary
