# MINIMAX AI OPERATOR CONFIGURATION
**Created:** 2025-09-20
**Purpose:** Autonomous GitHub operations using MiniMax models

## INTEGRATION SETUP:

### 1. MiniMax API Access:
```python
# config/minimax_config.py
MINIMAX_API_KEY = "your-key-here"
MINIMAX_API_HOST = "https://api.minimax.io"  # or https://api.minimaxi.com
MODEL = "MiniMax-Text-01"  # or "MiniMax-M1"
```

### 2. GitHub Integration:
```python
# Use existing github_api_protocol.py
from github_api_protocol import GitHubAPIProtocol

class MinimaxGitHubOperator:
    def __init__(self):
        self.github = GitHubAPIProtocol()
        self.minimax = MinimaxClient()
    
    def read_tasks(self):
        """Read tasks from MINIMAX_TASKS.md"""
        return self.github.get_file_content("MINIMAX_TASKS.md")
    
    def execute_task(self, task):
        """Send task to MiniMax for execution"""
        response = self.minimax.complete(task)
        return response
    
    def commit_results(self, files):
        """Commit generated files back to GitHub"""
        self.github.create_or_update_files(files)
```

### 3. Autonomous Loop:
```python
# minimax_autonomous.py
import time
import asyncio
from minimax_operator import MinimaxGitHubOperator

async def autonomous_loop():
    operator = MinimaxGitHubOperator()
    
    while True:
        # Check for new tasks every 5 minutes
        tasks = operator.read_tasks()
        
        if tasks and "PENDING" in tasks:
            # Execute with MiniMax
            result = operator.execute_task(tasks)
            
            # Commit results
            operator.commit_results(result)
            
            # Update task status
            operator.update_task_status("COMPLETED")
        
        await asyncio.sleep(300)  # 5 minutes

if __name__ == "__main__":
    asyncio.run(autonomous_loop())
```

## TASK FORMAT FOR MINIMAX:

### File: `MINIMAX_TASKS.md`
```markdown
# TASKS FOR MINIMAX OPERATOR
Status: PENDING
Priority: HIGH

## Task 1: Generate API endpoint
Create REST API endpoint for user management
Requirements:
- CRUD operations
- JWT authentication
- Input validation

## Task 2: Optimize existing code
Review and optimize monitoring_protocol.py
Focus on:
- Performance improvements
- Memory usage
- Error handling
```

## DEPLOYMENT OPTIONS:

### Option 1: GitHub Actions (Free tier)
```yaml
# .github/workflows/minimax_operator.yml
name: MiniMax Autonomous Operator
on:
  schedule:
    - cron: '*/30 * * * *'  # Every 30 minutes
  workflow_dispatch:  # Manual trigger

jobs:
  operate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run MiniMax Operator
        env:
          MINIMAX_API_KEY: ${{ secrets.MINIMAX_API_KEY }}
        run: python minimax_autonomous.py
```

### Option 2: VPS Deployment
```bash
# On any $5/month VPS
git clone https://github.com/guannko/super-system-eyelids
cd super-system-eyelids
pip install -r requirements.txt
export MINIMAX_API_KEY="your-key"
python minimax_autonomous.py &
```

### Option 3: Local with ngrok
```bash
# Run locally but expose webhook
ngrok http 8080
# Configure GitHub webhook to ngrok URL
```

## WHY MINIMAX:

1. **Cost**: 10x cheaper than GPT-4
2. **Context**: 4M tokens - can read entire codebases
3. **Open source**: Can run locally if needed
4. **MCP Support**: Direct integration available

## REALISTIC EXPECTATIONS:

### What it CAN do:
- Read task files from GitHub
- Generate code based on instructions
- Commit results back
- Update task status
- Run on schedule

### What it CAN'T do:
- True autonomy (still needs human oversight)
- Complex decision making
- Handle payment/billing
- Deploy to production without human
- Fix its own errors reliably

## NEXT STEPS:

1. Get MiniMax API key from https://api.minimax.io
2. Create minimax_operator.py based on template above
3. Set up GitHub Actions or VPS
4. Create first MINIMAX_TASKS.md with simple task
5. Test the loop

## COST ESTIMATE:

- MiniMax API: ~$0.20 per 1M tokens input
- GitHub Actions: Free (2000 minutes/month)
- Result: Almost free autonomous coding

---
**STATUS:** Configuration ready, awaiting implementation