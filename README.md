# Slide Verify - Automated VM Verification System

An automated system that uses the Slide API to create VM snapshots, perform verification tasks via noVNC, and generate comprehensive reports with AI-powered analysis.

## Security 

- **The LLM does NOT EVER SEE YOUR CREDENTIALS**
- **THE LLM DOES NOT EVER SEE YOUR CREDENTIALS**

- **Use a limited SLIDE API key - not an ADMIN API key - I used a client account key to limit the risk that I catastrophically broke everything..**


## Features

- **Automated VM Provisioning**: Automatically fetch the latest snapshot and boot a restore VM with network isolation
- **Browser-Based Automation**: Uses Playwright to interact with Windows Server via noVNC in the browser
- **AI-Powered Analysis**: OpenAI-compatible LLM integration for intelligent decision-making and report generation
- **Comprehensive Reporting**: Generates detailed HTML and JSON reports with timestamps and screenshots
- **Flexible Provider Support**: Works with OpenAI, vLLM, Ollama, and other OpenAI-compatible endpoints (MUST BE A VL model)
- **Automatic Cleanup**: Destroys VMs after verification to prevent resource waste
- **Can operate in headless**: Can be executed with playright headless. 
- **AI Interpretated "custom" instructions**: Use plain english to instruct the AI to perform a test task - ie "open cmd.exe and ping 127.0.0.1"

## Workflow

1. Retrieves the most recent snapshot from Slide API
2. Creates and boots a restore VM with `network=none` for network testing
3. Connects to the VM via noVNC in a browser (leverages the Slide.Recipes noVNC server)
4. Performs automated verification steps:
   - Logs into Windows Server
   - Executes PowerShell commands (with --ps-cmd flags)
5. Captures screenshots at each step
6. Generates AI-powered verification summary
7. Creates comprehensive reports (HTML and JSON)
8. Destroys the VM and cleans up resources

## Installation

### Prerequisites

- Python 3.8 or higher (tested with 3.13.5)
- Slide API access and API key
- OpenAI API key (or compatible provider i.e. ollama etc)

**Tested on windows - should work everywhere**

### Setup

1. **Clone this project**

2. **Install Python dependencies:**

pip install -r requirements.txt

3. **Install Playwright browsers:**

playwright install chromium

4. **Configure environment variables:**

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` and set:

- `SLIDE_API_KEY`: Your Slide API key
- `OPENAI_API_KEY`: Your OpenAI API key (or compatible provider)
- `OPENAI_API_BASE_URL`: API endpoint (default: OpenAI, or use Ollama, vLLM, etc.)
- `OPENAI_MODEL`: Model name to use

**These can be overridden at the command line with --username and --password**
- `WINDOWS_USERNAME`: Windows Server username (default: Administrator)
- `WINDOWS_PASSWORD`: Windows Server password 



## Usage

### Basic Usage

My Recommended Run (add --headless if you hate fun and don't want to watch it work)

```bash
python main.py --agent-id a_agentID --username 'vmUser' --password 'YourVMPasswordHere' --ps-cmd-1 "Get-Service" --ps-cmd-2 "AnotherPSCmdlet"
```

### Advanced Options

**Verify ALL agents (most recent snapshot for each):**

Keep in mind they will try the same password... so I would limit to the above for now unless you implement some kind of credential vault. 

```bash
python main.py --all-agents
```

This will:
- Retrieve all available agents
- Get the most recent snapshot for each agent
- Run verification on each agent sequentially
- Generate individual reports for each agent
- Provide a summary of all verifications

**Filter by specific agent ID:**

```bash
python main.py --agent-id your-agent-id
```
**Execute powershell cmdlet**

```bash 
python main.py --agent-id your-agent-id --ps-cmd-1 "Get-serivce | FL" 
```
or more commands

```bash
python main.py --agent-id your-agent-id --ps-cmd-1 "Get-Service" --ps-cmd-2 "Get-Uptime" 
```

up to three ps-cmd-x commands. 

**Run in headless mode (no browser window):**

```bash
python main.py --headless
```

**Custom verification steps:**

This one is a WIP...

```bash
python main.py --steps "Open CMD.exe and ping 127.0.0.1"
```

**Verify all agents with custom steps:**

```bash
python main.py --all-agents --headless --steps "Custom step 1, Custom step 2"
```

### Debugging 

**Show password in terminal for debug - I had initial trouble with the vnc typing....  so this was helpful**

```bash 
python main.py --show-password 
```

**Pause login for a period so you can manaully click the reveal password button in the login page**

```bash 
python main.py --pause
``` 

- **Default is 30 seconds, if you need longer**

```bash
python main.py --pause --pause-duration 60
```

## Configuration

### OpenAI-Compatible Providers

The system supports any OpenAI-compatible API endpoint. Configure in `.env` (VL capable models only. QWEN3-VL-8B is good for local):

**OpenAI (default):**
```env
OPENAI_API_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4-turbo-preview
```

**Ollama (local):**
```env
OPENAI_API_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=qwen3-vl:8b
```

**OpenRouter:**
```env
OPENAI_API_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=anthropic/claude-3-opus
```

**Together AI:**
```env
OPENAI_API_BASE_URL=https://api.together.xyz/v1
OPENAI_MODEL=mistralai/Mixtral-8x7B-Instruct-v0.1
```

**Nebius:**
```env
OPENAI_API_BASE_URL=https://api.studio.nebius.ai/v1
OPENAI_MODEL=your-model-name
```

**Hugging Face:**
```env
OPENAI_API_BASE_URL=https://api-inference.huggingface.co/v1
OPENAI_MODEL=VL Model
```

## Output

After running, you'll find:

1. **HTML Report**: `reports/verification_report_YYYYMMDD_HHMMSS.html`
   - Interactive report with screenshots
   - AI-generated summary and analysis
   - Complete action log with timestamps
   - Success/failure indicators for each step

2. **JSON Report**: `reports/verification_report_YYYYMMDD_HHMMSS.json`
   - Machine-readable format
   - Complete verification data
   - Can be used for further automation or analysis

3. **Screenshots**: `screenshots/YYYYMMDD_HHMMSS_*.png`
   - Screenshots captured at each verification step
   - Timestamped for easy tracking

4. **Log File**: `verification.log`
   - Detailed application logs
   - Useful for debugging

## Modules

### SlideClient (`slide_client.py`)

Handles all interactions with the Slide API:
- List and retrieve snapshots
- Create VMs from snapshots
- Start/stop VMs
- Get noVNC URLs
- Destroy VMs

### LLMClient (`llm_client.py`)

Manages AI interactions:
- Generate task instructions
- Analyze verification results
- Make automation decisions
- Supports any OpenAI-compatible endpoint

### VMAutomation (`vm_automation.py`)

Automates Windows Server operations:
- Connect to VMs via noVNC
- Login to Windows
- Navigate UI (Services Manager, Server Manager, etc.)
- Execute PowerShell commands
- Capture screenshots
- Log all actions

### ReportGenerator (`report_generator.py`)

Creates verification reports:
- Generate HTML reports with styling
- Export JSON data
- Include screenshots and timestamps
- Display AI summaries


### HTML Template is is (`Templates/report_template.html`)

## Troubleshooting

### Connection Issues

If you can't connect to the VM:
- Check that the VM is actually running (`wait_for_vm_ready` timeout)
- Verify the noVNC URL is accessible
- Try increasing `VM_BOOT_TIMEOUT` in `.env`

### Login Issues

If Windows login fails:
- Verify credentials in `.env`
- Check if Ctrl+Alt+Del is required (handled automatically)
- Increase wait times if the VM is slow

### Playwright Issues

If browser automation fails:
- Ensure Playwright browsers are installed: `playwright install chromium`
- Try running without headless mode to see what's happening
- Check browser console for errors

### API Issues

If Slide API calls fail:
- Verify your `SLIDE_API_KEY` is correct
- Check API endpoint URL
- Review logs in `verification.log`

### LLM Issues

If AI analysis fails:
- Verify your API key and endpoint
- Check that the model name is correct for your provider
- Some providers may have different API formats

## Security Considerations

- **Network Isolation**: VMs are created with `network=none` to prevent access
- **Credentials**: Never commit `.env` file with real credentials
- **API Keys**: Rotate API keys regularly
- **Cleanup**: VMs are automatically destroyed after verification

## Extending the System

### Adding Custom Verification Steps

Pass custom steps via command line:

```bash
python main.py --steps "Step 1, Step 2, Step 3"
```

Or modify `main.py` to add programmatic steps.

### Adding New Automation Actions

Extend `VMAutomation` class in `vm_automation.py`:

```python
def check_iis_status(self):
    """Check IIS status."""
    # Your automation logic here
    pass
```

### Customizing Reports

Modify the HTML template in `templates/report_template.html` to change report styling or layout.

### Using Different LLM Providers

Simply update `OPENAI_API_BASE_URL` and `OPENAI_MODEL` in `.env`. The system works with any OpenAI-compatible API.

## License

This project is provided as-is for use with the Slide API.

## Support

For issues related to:
- **Slide API**: Contact Slide support
- **This application**: Check logs in `verification.log` and review error messages

## Contributing

Feel free to extend and modify this system for your needs. Key areas for improvement:
- OCR integration for more viable text
- More sophisticated error handling
- Parallel VM testing
- Integration with PSA
- Create seperate report templates for seperate clients. 
