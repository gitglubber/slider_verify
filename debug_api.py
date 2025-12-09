"""Debug script to test Slide API connection and list available resources."""
import sys
import json
from config import get_settings
from slide_client import SlideClient, SlideAPIError


def main():
    """Debug Slide API connection."""
    print("=" * 70)
    print("Slide API Debug Tool")
    print("=" * 70)
    print()

    # Load settings
    try:
        settings = get_settings()
        print("✓ Settings loaded successfully")
        print(f"  API Base URL: {settings.slide_api_base_url}")
        print(f"  API Key: {settings.slide_api_key[:10]}..." if settings.slide_api_key else "  API Key: NOT SET")
        print()
    except Exception as e:
        print(f"✗ Failed to load settings: {e}")
        print("  Make sure you have a .env file with SLIDE_API_KEY set")
        sys.exit(1)

    # Initialize client
    try:
        client = SlideClient(
            api_key=settings.slide_api_key,
            base_url=settings.slide_api_base_url
        )
        print("✓ Slide API client initialized")
        print()
    except Exception as e:
        print(f"✗ Failed to initialize client: {e}")
        sys.exit(1)

    # Test 1: List all agents
    print("-" * 70)
    print("Test 1: Listing ALL agents")
    print("-" * 70)
    try:
        agents = client.list_agents(limit=50)
        print(f"✓ Found {len(agents)} agents")
        print()

        if agents:
            print("Available agents:")
            print()

            for agent in agents:
                print(f"Agent ID: {agent.get('agent_id')}")
                print(f"  Hostname: {agent.get('hostname', 'N/A')}")
                print(f"  OS: {agent.get('os', 'N/A')}")
                print(f"  OS Version: {agent.get('os_version', 'N/A')}")
                print(f"  IP Address: {agent.get('ip_address', 'N/A')}")
                print(f"  Status: {agent.get('status', 'N/A')}")
                print()
        else:
            print("⚠ No agents found!")
            print()

    except SlideAPIError as e:
        print(f"✗ API Error: {e}")
    except Exception as e:
        print(f"✗ Unexpected error: {e}")

    print()

    # Test 2: List all snapshots
    print("-" * 70)
    print("Test 2: Listing ALL snapshots")
    print("-" * 70)
    try:
        snapshots = client.list_snapshots(limit=50)
        print(f"✓ Found {len(snapshots)} snapshots total")
        print()

        if snapshots:
            print("Available snapshots:")
            print()

            # Group by agent_id
            by_agent = {}
            for snapshot in snapshots:
                agent_id = snapshot.get("agent_id", "unknown")
                if agent_id not in by_agent:
                    by_agent[agent_id] = []
                by_agent[agent_id].append(snapshot)

            for agent_id, agent_snapshots in by_agent.items():
                print(f"Agent: {agent_id}")
                print(f"  Snapshots: {len(agent_snapshots)}")

                # Show the most recent snapshot details
                most_recent = sorted(
                    agent_snapshots,
                    key=lambda s: s.get("backup_ended_at", s.get("backup_started_at", "")),
                    reverse=True
                )[0]

                print(f"  Latest Snapshot ID: {most_recent.get('snapshot_id')}")
                print(f"  Backup Started: {most_recent.get('backup_started_at')}")
                print(f"  Backup Ended: {most_recent.get('backup_ended_at')}")
                print(f"  Agent ID: {most_recent.get('agent_id', 'N/A')}")
                print()
        else:
            print("⚠ No snapshots found!")
            print()
            print("This could mean:")
            print("  1. Your API key doesn't have access to any snapshots")
            print("  2. There are no backups/snapshots in your account")
            print("  3. The API endpoint or credentials are incorrect")
            print()

    except SlideAPIError as e:
        print(f"✗ API Error: {e}")
        print()
        print("Possible issues:")
        print("  1. Invalid API key")
        print("  2. Network connectivity problem")
        print("  3. API endpoint URL is incorrect")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        sys.exit(1)

    # Test 3: List VMs (if any)
    print("-" * 70)
    print("Test 3: Listing existing VMs")
    print("-" * 70)
    try:
        # List VMs endpoint
        response = client._request("GET", "/v1/restore/virt", params={"limit": 50})

        if "data" in response:
            vms = response["data"]
            print(f"✓ Found {len(vms)} existing VMs")

            if vms:
                print()
                for vm in vms:
                    print(f"VM ID: {vm.get('virt_id')}")
                    print(f"  Agent: {vm.get('agent_id')}")
                    print(f"  State: {vm.get('state')}")
                    print(f"  Snapshot: {vm.get('snapshot_id')}")
                    print(f"  Created: {vm.get('created_at')}")
                    print()
        else:
            print("✓ No existing VMs")

        print()

    except Exception as e:
        print(f"⚠ Could not list VMs: {e}")
        print()

    # Test 4: Raw API response
    print("-" * 70)
    print("Test 4: Raw snapshot API response (first snapshot)")
    print("-" * 70)
    try:
        response = client._request("GET", "/v1/snapshot", params={"limit": 1})
        print(json.dumps(response, indent=2))
        print()
    except Exception as e:
        print(f"✗ Failed to get raw response: {e}")
        print()

    print("=" * 70)
    print("Debug complete!")
    print("=" * 70)
    print()
    print("Next steps:")
    print("  1. Use one of the Agent IDs shown above with --agent-id")
    print("  2. Or use --all-agents to verify all agents automatically")
    print()
    print("Example:")
    if snapshots and by_agent:
        first_agent = list(by_agent.keys())[0]
        print(f"  python main.py --agent-id {first_agent}")
    print("  python main.py --all-agents")
    print()


if __name__ == "__main__":
    main()
