"""Slide API client for snapshot and VM management."""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
import requests


logger = logging.getLogger(__name__)


class SlideAPIError(Exception):
    """Exception raised for Slide API errors."""
    pass


class SlideClient:
    """Client for interacting with the Slide API."""

    def __init__(self, api_key: str, base_url: str = "https://api.slide.tech"):
        """
        Initialize Slide API client.

        Args:
            api_key: Slide API key
            base_url: Base URL for Slide API
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        })

    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Make an API request.

        Args:
            method: HTTP method
            endpoint: API endpoint
            **kwargs: Additional arguments for requests

        Returns:
            Response JSON data

        Raises:
            SlideAPIError: If the API request fails
        """
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json() if response.content else {}
        except requests.exceptions.RequestException as e:
            # Try to get error details from response
            error_detail = ""
            try:
                if hasattr(e, 'response') and e.response is not None:
                    error_detail = f"\nResponse: {e.response.text}"
            except:
                pass

            logger.error(f"Slide API request failed: {e}{error_detail}")
            raise SlideAPIError(f"API request failed: {e}{error_detail}") from e

    def list_agents(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        List all agents.

        Args:
            limit: Maximum number of agents to return

        Returns:
            List of agent objects with details like hostname, OS, etc.
        """
        params = {"limit": limit}
        response = self._request("GET", "/v1/agent", params=params)
        return response.get("data", [])

    def get_agent_details(self, agent_id: str) -> Dict[str, Any]:
        """
        Get details for a specific agent.

        Args:
            agent_id: Agent ID

        Returns:
            Agent details including hostname, OS, etc.
        """
        response = self._request("GET", f"/v1/agent/{agent_id}")

        # Handle response structure with "data" array
        if "data" in response and isinstance(response["data"], list):
            if len(response["data"]) > 0:
                return response["data"][0]
            else:
                raise SlideAPIError(f"No agent data found for {agent_id}")

        # Fallback for direct response
        return response

    def list_snapshots(
        self,
        agent_id: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        List available snapshots.

        Args:
            agent_id: Optional agent ID to filter by
            limit: Maximum number of snapshots to return

        Returns:
            List of snapshot objects
        """
        params = {"limit": limit}
        if agent_id:
            params["agent_id"] = agent_id

        response = self._request("GET", "/v1/snapshot", params=params)
        # API returns data in "data" field, not "snapshots"
        return response.get("data", [])

    def get_latest_snapshot(
        self,
        agent_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get the most recent snapshot.

        Args:
            agent_id: Optional agent ID to filter by

        Returns:
            Latest snapshot object or None if no snapshots found
        """
        snapshots = self.list_snapshots(agent_id=agent_id, limit=1)
        if not snapshots:
            logger.warning("No snapshots found")
            return None

        # Sort by backup_ended_at to ensure we get the latest
        snapshots_sorted = sorted(
            snapshots,
            key=lambda s: s.get("backup_ended_at", s.get("backup_started_at", "")),
            reverse=True
        )
        latest = snapshots_sorted[0]
        logger.info(
            f"Found latest snapshot: {latest.get('snapshot_id')} "
            f"from {latest.get('backup_started_at', latest.get('backup_ended_at'))}"
        )
        return latest

    def get_latest_snapshots_by_agent(
        self,
        limit_per_agent: int = 1
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get the most recent snapshot(s) for each agent.

        Args:
            limit_per_agent: Number of snapshots to return per agent (default: 1 for most recent)

        Returns:
            Dictionary mapping agent_id to snapshot info
            Example: {
                "a_if5d91z4t2pn": {"id": "s_k01kus7qa288", "backup_time": "2025-12-04...", ...},
                "a_xyz123": {"id": "s_abc456", "backup_time": "2025-12-03...", ...}
            }
        """
        # Get all snapshots (API limit is 50 per request)
        all_snapshots = self.list_snapshots(limit=50)

        # Group by agent_id
        snapshots_by_agent = {}
        for snapshot in all_snapshots:
            agent_id = snapshot.get("agent_id")
            if not agent_id:
                continue

            if agent_id not in snapshots_by_agent:
                snapshots_by_agent[agent_id] = []

            snapshots_by_agent[agent_id].append(snapshot)

        # Sort each agent's snapshots by backup_time and take the most recent
        latest_by_agent = {}
        for agent_id, snapshots in snapshots_by_agent.items():
            sorted_snapshots = sorted(
                snapshots,
                key=lambda s: s.get("backup_ended_at", s.get("backup_started_at", "")),
                reverse=True
            )

            if limit_per_agent == 1:
                latest_by_agent[agent_id] = sorted_snapshots[0]
            else:
                latest_by_agent[agent_id] = sorted_snapshots[:limit_per_agent]

            logger.info(
                f"Agent {agent_id}: Latest snapshot {sorted_snapshots[0].get('snapshot_id')} "
                f"from {sorted_snapshots[0].get('backup_ended_at')}"
            )

        logger.info(f"Found latest snapshots for {len(latest_by_agent)} agents")
        return latest_by_agent

    def create_vm(
        self,
        snapshot_id: str,
        device_id: str,
        network: str = "network-none",
        cpu: Optional[int] = None,
        memory: Optional[int] = None,
        name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a VM from a snapshot.

        Args:
            snapshot_id: Snapshot ID to restore from
            device_id: Device ID where the snapshot is stored (required)
            network: Network mode (network-none, network-nat, network-bridged)
            cpu: Number of CPUs (optional)
            memory: Memory in MB (optional)
            name: VM name (optional)

        Returns:
            VM creation response with virt_id
        """
        payload = {
            "snapshot_id": snapshot_id,
            "device_id": device_id,
            "network_type": network
        }
        if cpu:
            payload["cpu"] = cpu
        if memory:
            payload["memory"] = memory
        if name:
            payload["name"] = name

        logger.info(
            f"Creating VM from snapshot {snapshot_id} with network={network}"
        )
        response = self._request("POST", "/v1/restore/virt", json=payload)
        virt_id = response.get("virt_id")
        logger.info(f"VM created successfully: {virt_id}")
        return response

    def start_vm(self, virt_id: str) -> Dict[str, Any]:
        """
        Start a VM.

        Args:
            virt_id: Virtual machine ID

        Returns:
            Start operation response
        """
        logger.info(f"Starting VM: {virt_id}")
        response = self._request("POST", f"/v1/restore/virt/{virt_id}/start")
        logger.info(f"VM {virt_id} started successfully")
        return response

    def get_vm_details(self, virt_id: str) -> Dict[str, Any]:
        """
        Get VM details.

        Args:
            virt_id: Virtual machine ID

        Returns:
            VM details including status and configuration
        """
        response = self._request("GET", f"/v1/restore/virt/{virt_id}")

        # Handle response structure with "data" array
        if "data" in response and isinstance(response["data"], list):
            if len(response["data"]) > 0:
                return response["data"][0]
            else:
                raise SlideAPIError(f"No VM data found for {virt_id}")

        # Fallback for direct response
        return response

    def get_vnc_url(self, virt_id: str) -> str:
        """
        Get noVNC URL for VM access.

        Args:
            virt_id: Virtual machine ID

        Returns:
            noVNC URL for browser-based access in the format:
            https://slide.recipes/mcpTools/vncViewer.php?id={virt_id}&ws={websocket_uri}&password={vnc_password}
        """
        # Get VM details which includes VNC information
        vm_details = self.get_vm_details(virt_id)

        # Extract VNC information
        vnc_data = vm_details.get("vnc", [])
        vnc_password = vm_details.get("vnc_password", "")

        if not vnc_data or len(vnc_data) == 0:
            raise SlideAPIError(f"No VNC data available for VM {virt_id}")

        # Get the websocket URI (using cloud type)
        websocket_uri = None
        for vnc_entry in vnc_data:
            if vnc_entry.get("type") == "cloud":
                websocket_uri = vnc_entry.get("websocket_uri")
                break

        if not websocket_uri:
            raise SlideAPIError(f"No websocket URI found for VM {virt_id}")

        # Construct the noVNC viewer URL
        # Note: password parameter needs trailing '=' as per Slide API format
        from urllib.parse import quote

        vnc_url = (
            f"https://slide.recipes/mcpTools/vncViewer.php?"
            f"id={virt_id}&"
            f"ws={quote(websocket_uri, safe='')}&"
            f"password={vnc_password}="
        )

        logger.info(f"Constructed VNC URL for VM {virt_id}: {vnc_url}")
        return vnc_url

    def stop_vm(self, virt_id: str) -> Dict[str, Any]:
        """
        Stop a VM.

        Args:
            virt_id: Virtual machine ID

        Returns:
            Stop operation response
        """
        logger.info(f"Stopping VM: {virt_id}")
        response = self._request("POST", f"/v1/restore/virt/{virt_id}/stop")
        logger.info(f"VM {virt_id} stopped successfully")
        return response

    def destroy_vm(self, virt_id: str) -> bool:
        """
        Destroy a VM and clean up resources.

        Args:
            virt_id: Virtual machine ID

        Returns:
            True if destroyed successfully
        """
        logger.info(f"Destroying VM: {virt_id}")
        try:
            self._request("DELETE", f"/v1/restore/virt/{virt_id}")
            logger.info(f"VM {virt_id} destroyed successfully")
            return True
        except SlideAPIError as e:
            logger.error(f"Failed to destroy VM {virt_id}: {e}")
            return False

    def wait_for_vm_ready(
        self,
        virt_id: str,
        timeout: int = 300,
        check_interval: int = 5
    ) -> bool:
        """
        Wait for VM to be ready.

        Args:
            virt_id: Virtual machine ID
            timeout: Maximum wait time in seconds
            check_interval: Time between status checks in seconds

        Returns:
            True if VM is ready, False if timeout
        """
        import time

        logger.info(f"Waiting for VM {virt_id} to be ready (timeout: {timeout}s)")
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                details = self.get_vm_details(virt_id)
                # Check "state" field (Slide API uses "state" not "status")
                state = details.get("state", "").lower()
                logger.debug(f"VM {virt_id} state: {state}")

                if state == "running":
                    logger.info(f"VM {virt_id} is ready")
                    return True

                time.sleep(check_interval)
            except SlideAPIError as e:
                logger.warning(f"Error checking VM status: {e}")
                time.sleep(check_interval)

        logger.error(f"Timeout waiting for VM {virt_id} to be ready")
        return False
