# Rule: Agent Restrictions

**CRITICAL CONSTRAINTS**:

1. **No GitHub API Fetches**:
   Under no circumstances should the agent attempt to fetch data from, or make HTTP requests to, `api.github.com` or `github.com` using tools such as `read_url_content`, `run_command` (e.g., `curl`, `wget`), or any web search/browser tools. This triggers ESET Antivirus security incidents on the host machine.

2. **No External Infrastructure Commands**:
   The agent MUST NOT run any external infrastructure or network commands directly. This includes, but is not limited to:
   - `kubectl` commands
   - `gcloud` commands
   - `terraform` commands
   
   If such operations are required to diagnose or fix an issue, the agent must output the commands in its response and politely ask the USER to run them manually.
