import asyncio
import json
import logging
import os

logger = logging.getLogger("networkos")

class AgentReachCLI:
    """Wrapper for executing the agent-reach CLI tool safely."""
    
    @staticmethod
    async def check_capabilities() -> dict:
        """
        Runs 'agent-reach doctor' or checks version to verify it is installed.
        Returns a dictionary of available capabilities based on the environment.
        """
        try:
            import shutil
            executable = shutil.which("agent-reach") or "agent-reach"
            process = await asyncio.create_subprocess_exec(
                executable, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
            
            if process.returncode == 0:
                logger.info(f"Agent-Reach is available. Version: {stdout.decode().strip()}")
                return {
                    "installed": True,
                    "supported_targets": ["github", "web", "twitter"] 
                }
            else:
                logger.warning(f"Agent-Reach returned non-zero exit code: {stderr.decode()}")
                return {"installed": False, "supported_targets": []}
                
        except (FileNotFoundError, asyncio.TimeoutError) as e:
            logger.warning(f"Agent-Reach CLI not found or timed out: {e}")
            return {"installed": False, "supported_targets": []}
            
    @staticmethod
    async def execute_search(target: str, query: str, timeout: float = 30.0) -> dict:
        """
        Executes 'agent-reach search --target <target> <query>' safely.
        """
        allowed_targets = ["github", "twitter", "reddit", "web"]
        if target not in allowed_targets:
            raise ValueError(f"Target '{target}' is not permitted.")
            
        try:
            # Fallback to Jina Reader since agent-reach CLI 'search' is discontinued
            import urllib.request
            import urllib.parse
            import json
            
            # If target is github, build github search URL
            url = ""
            if target == "github":
                url = f"https://github.com/search?q={urllib.parse.quote(query)}&type=users"
            else:
                url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
                
            req = urllib.request.Request(f"https://r.jina.ai/{url}")
            with urllib.request.urlopen(req, timeout=timeout) as response:
                content = response.read().decode('utf-8')
                return {"status": "SUCCESS", "data": {"raw_text": content}}
                
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    @staticmethod
    async def execute_read(url: str, timeout: float = 30.0) -> dict:
        """
        Executes 'agent-reach read <url>' safely.
        """
        try:
            import urllib.request
            req = urllib.request.Request(f"https://r.jina.ai/{url}")
            with urllib.request.urlopen(req, timeout=timeout) as response:
                content = response.read().decode('utf-8')
                return {"status": "SUCCESS", "data": {"raw_text": content}}
                
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}
