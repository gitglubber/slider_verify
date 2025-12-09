"""OpenAI-compatible LLM client for agentic operations."""
import logging
import base64
from pathlib import Path
from typing import List, Dict, Any, Optional
from openai import OpenAI


logger = logging.getLogger(__name__)


class LLMClient:
    """Client for interacting with OpenAI-compatible LLM endpoints."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4-turbo-preview"
    ):
        """
        Initialize LLM client.

        Args:
            api_key: API key for the LLM service
            base_url: Base URL for OpenAI-compatible endpoint
            model: Model name to use
        """
        self.model = model
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )
        logger.info(f"Initialized LLM client with model: {model} at {base_url}")

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        """
        Send a chat completion request.

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            Generated response content
        """
        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature
            }
            if max_tokens:
                kwargs["max_tokens"] = max_tokens

            response = self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            logger.debug(f"LLM response: {content[:100]}...")
            return content
        except Exception as e:
            logger.error(f"LLM request failed: {e}")
            raise

    def _encode_image(self, image_path: str) -> str:
        """
        Encode image to base64 string.

        Args:
            image_path: Path to image file

        Returns:
            Base64 encoded image string
        """
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def analyze_screenshot(
        self,
        screenshot_path: str,
        prompt: str,
        system_prompt: Optional[str] = None
    ) -> str:
        """
        Analyze a screenshot with vision capabilities.

        Args:
            screenshot_path: Path to screenshot image
            prompt: Analysis prompt
            system_prompt: Optional system prompt

        Returns:
            Analysis results
        """
        try:
            # Encode the image
            base64_image = self._encode_image(screenshot_path)

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})

            # Create message with image
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}"
                        }
                    }
                ]
            })

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=500
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Screenshot analysis failed: {e}")
            # Fallback to text-only if vision not supported
            logger.warning("Vision analysis failed, returning error message")
            return f"ERROR: Could not analyze screenshot - {str(e)}"

    def verify_ui_state(
        self,
        screenshot_path: str,
        expected_state: str,
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Verify if a screenshot shows the expected UI state.

        Args:
            screenshot_path: Path to screenshot
            expected_state: What should be visible (e.g., "Windows login screen")
            context: Optional additional context

        Returns:
            Dictionary with 'verified' (bool), 'confidence' (str), 'description' (str)
        """
        context_str = f"\n\nContext: {context}" if context else ""

        prompt = f"""Analyze this screenshot and determine if it shows: {expected_state}{context_str}

Respond in this EXACT format:
VERIFIED: yes/no
CONFIDENCE: high/medium/low
DESCRIPTION: Brief description of what you actually see

Be precise and honest. If you're not sure, say so."""

        try:
            response = self.analyze_screenshot(
                screenshot_path,
                prompt,
                system_prompt="You are a UI verification assistant. Analyze screenshots accurately and honestly."
            )

            # Parse response
            result = {
                "verified": False,
                "confidence": "low",
                "description": response,
                "raw_response": response
            }

            lines = response.upper().split('\n')
            for line in lines:
                if 'VERIFIED:' in line:
                    result["verified"] = 'YES' in line
                elif 'CONFIDENCE:' in line:
                    conf = line.split(':', 1)[1].strip().lower()
                    if conf in ['high', 'medium', 'low']:
                        result["confidence"] = conf
                elif 'DESCRIPTION:' in line:
                    result["description"] = line.split(':', 1)[1].strip()

            status = "[OK]" if result['verified'] else "[FAIL]"
            logger.info(
                f"UI Verification: {expected_state} = "
                f"{status} "
                f"({result['confidence']} confidence)"
            )

            return result

        except Exception as e:
            logger.error(f"UI verification failed: {e}")
            return {
                "verified": False,
                "confidence": "error",
                "description": f"Error during verification: {str(e)}",
                "raw_response": ""
            }

    def detect_login_fields(
        self,
        screenshot_path: str
    ) -> Dict[str, Any]:
        """
        Detect which login fields are visible on the Windows login screen.

        Args:
            screenshot_path: Path to screenshot

        Returns:
            Dictionary with 'has_username' (bool), 'has_password' (bool), 'description' (str), 'displayed_username' (str)
        """
        prompt = """Analyze this Windows login screen and tell me which input fields are CURRENTLY EDITABLE and what username (if any) is displayed.

Important distinctions:
- USERNAME FIELD: An EDITABLE text input where you can TYPE a different username. If you see a username displayed but it's NOT an editable field (just text/label), answer NO.
- PASSWORD FIELD: An EMPTY input field where you need to type the password.
- DISPLAYED USERNAME: The username shown on screen (even if not editable)

If the username is already filled in and you just need to enter a password, then:
- USERNAME_FIELD: no (it's pre-filled, not editable)
- PASSWORD_FIELD: yes (you need to type the password)
- DISPLAYED_USERNAME: [the username you see]

If both username AND password fields are empty and editable:
- USERNAME_FIELD: yes
- PASSWORD_FIELD: yes
- DISPLAYED_USERNAME: none

Respond in this EXACT format:
USERNAME_FIELD: yes/no
PASSWORD_FIELD: yes/no
DISPLAYED_USERNAME: [username shown or "none"]
DESCRIPTION: What you see on the login screen

Be precise about what is EDITABLE vs just displayed."""

        try:
            response = self.analyze_screenshot(
                screenshot_path,
                prompt,
                system_prompt="You are a UI analysis assistant. Identify which login fields need user input."
            )

            # Log raw response for debugging
            logger.debug(f"Raw LLM response for field detection:\n{response}")

            # Parse response
            result = {
                "has_username": False,
                "has_password": False,
                "displayed_username": None,
                "description": "",
                "raw_response": response
            }

            lines = response.split('\n')
            for line in lines:
                line_upper = line.upper()
                if 'USERNAME_FIELD:' in line_upper or 'USERNAME FIELD:' in line_upper:
                    result["has_username"] = 'YES' in line_upper
                elif 'PASSWORD_FIELD:' in line_upper or 'PASSWORD FIELD:' in line_upper:
                    result["has_password"] = 'YES' in line_upper
                elif 'DISPLAYED_USERNAME:' in line_upper or 'DISPLAYED USERNAME:' in line_upper:
                    username = line.split(':', 1)[1].strip() if ':' in line else ""
                    result["displayed_username"] = username if username.lower() != "none" else None
                elif 'DESCRIPTION:' in line_upper:
                    result["description"] = line.split(':', 1)[1].strip() if ':' in line else ""

            # If parsing failed completely, log the raw response
            if not result["description"]:
                logger.warning(f"Failed to parse field detection response. Raw response:\n{response}")
                result["description"] = response[:200]  # Use first 200 chars as description

            logger.info(
                f"Login fields detected: username={result['has_username']}, "
                f"password={result['has_password']}"
            )
            logger.info(f"  Detection reasoning: {result['description']}")

            return result

        except Exception as e:
            logger.error(f"Login field detection failed: {e}")
            # Default to both fields if detection fails
            return {
                "has_username": True,
                "has_password": True,
                "description": f"Error during detection: {str(e)}",
                "raw_response": ""
            }

    def generate_task_instructions(
        self,
        task_description: str,
        context: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Generate step-by-step instructions for a task.

        Args:
            task_description: Description of the task to perform
            context: Optional context information (VM details, etc.)

        Returns:
            List of step-by-step instructions
        """
        context_str = ""
        if context:
            context_str = "\n\nContext:\n" + "\n".join(
                f"- {k}: {v}" for k, v in context.items()
            )

        prompt = f"""Given the following task, generate clear step-by-step instructions
for automation. Each step should be specific and actionable.

Task: {task_description}{context_str}

Provide the steps as a numbered list. Be specific about UI elements,
commands, and verification points."""

        messages = [
            {
                "role": "system",
                "content": "You are an automation expert. Generate precise, "
                "actionable steps for Windows Server administration tasks."
            },
            {"role": "user", "content": prompt}
        ]

        response = self.chat(messages, temperature=0.3)
        return self._parse_steps(response)

    def analyze_verification_results(
        self,
        steps_completed: List[Dict[str, Any]],
        screenshots: List[str]
    ) -> str:
        """
        Analyze verification results and generate summary.

        Args:
            steps_completed: List of completed steps with details
            screenshots: List of screenshot paths

        Returns:
            Verification summary and analysis
        """
        from datetime import datetime

        steps_summary = "\n".join([
            f"{i+1}. {step.get('description', 'Unknown')}: "
            f"{'Success' if step.get('success') else 'Failed'}"
            for i, step in enumerate(steps_completed)
        ])

        current_date = datetime.now().strftime("%B %d, %Y")

        prompt = f"""Analyze the following BCDR (Business Continuity/Disaster Recovery) test results and provide a professional summary.

Today's Date: {current_date}

Steps Completed:
{steps_summary}

Total Screenshots: {len(screenshots)}

IMPORTANT GUIDELINES:
- Do NOT comment on usernames, credentials, or account naming conventions
- Do NOT criticize the number of screenshots - they are necessary for comprehensive verification
- Focus ONLY on technical success/failure of the verification steps
- This is a BCDR test, not a security audit
- Include the actual current date ({current_date}) in your summary
- Service checks verify existence and status, which is appropriate for disaster recovery validation

Provide:
1. Overall success status (did all steps complete successfully?)
2. Key findings (what was verified and confirmed working)
3. Any TECHNICAL issues or concerns (failures, errors, unexpected behavior)
4. Brief recommendations for BCDR improvements (if any)

Format as a professional BCDR test summary. Keep it concise and focused on disaster recovery validation."""

        messages = [
            {
                "role": "system",
                "content": "You are a BCDR (Business Continuity/Disaster Recovery) specialist analyzing automated "
                "disaster recovery test results. Provide clear, professional assessments focused on system "
                "availability and recovery validation. Do not perform security audits or criticize account naming. "
                "Focus on whether the system recovered successfully and key services are operational."
            },
            {"role": "user", "content": prompt}
        ]

        return self.chat(messages, temperature=0.5)

    def decide_next_action(
        self,
        current_step: str,
        screenshot_description: str,
        expected_outcome: str
    ) -> Dict[str, Any]:
        """
        Decide the next action based on current state.

        Args:
            current_step: Current step being executed
            screenshot_description: Description of what's visible
            expected_outcome: What should be visible/happening

        Returns:
            Dictionary with 'action', 'reason', and 'success' keys
        """
        prompt = f"""Based on the current automation state, determine if the step
was successful and what action to take next.

Current Step: {current_step}
Current State: {screenshot_description}
Expected Outcome: {expected_outcome}

Respond in the following format:
SUCCESS: yes/no
REASON: brief explanation
NEXT_ACTION: continue/retry/abort"""

        messages = [
            {
                "role": "system",
                "content": "You are an automation decision engine. Analyze the "
                "current state and determine if automation should proceed."
            },
            {"role": "user", "content": prompt}
        ]

        response = self.chat(messages, temperature=0.2)
        return self._parse_decision(response)

    def _parse_steps(self, response: str) -> List[str]:
        """Parse step-by-step instructions from LLM response."""
        lines = response.strip().split("\n")
        steps = []

        for line in lines:
            line = line.strip()
            # Match numbered lists like "1.", "1)", etc.
            if line and (
                line[0].isdigit() or
                line.startswith("-") or
                line.startswith("*")
            ):
                # Remove numbering
                step = line.lstrip("0123456789.-*) \t")
                if step:
                    steps.append(step)

        return steps

    def _parse_decision(self, response: str) -> Dict[str, Any]:
        """Parse decision from LLM response."""
        decision = {
            "success": False,
            "reason": "",
            "action": "continue"
        }

        lines = response.upper().split("\n")
        for line in lines:
            if "SUCCESS:" in line:
                decision["success"] = "YES" in line
            elif "REASON:" in line:
                decision["reason"] = line.split("REASON:", 1)[1].strip()
            elif "NEXT_ACTION:" in line or "NEXT ACTION:" in line:
                action = line.split(":", 1)[1].strip().lower()
                if action in ["continue", "retry", "abort"]:
                    decision["action"] = action

        return decision
