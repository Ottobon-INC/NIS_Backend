import httpx
import os
import logging
from typing import Dict, Any, Optional, List
from app.services.providers.base import ResearchProvider
from app.core.config import settings

logger = logging.getLogger("networkos")

class GitHubProvider(ResearchProvider):
    def __init__(self):
        self.api_base = "https://api.github.com"
        self.token = getattr(settings, "GITHUB_TOKEN", None) or os.getenv("GITHUB_TOKEN", "")

    def get_provider_metadata(self) -> Dict[str, Any]:
        return {
            "source_id": "github",
            "name": "GitHub Developer Intelligence",
            "provider_type": "EXTERNAL_API",
            "supported_entity_types": ["person", "company"],
            "supported_intelligence_types": ["profile", "repositories", "technologies", "public_projects"],
            "requires_api_key": False,
            "requires_paid_license": False
        }

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "User-Agent": "NetworkOS-Research/1.0",
            "Accept": "application/vnd.github.v3+json"
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def search_person(self, query: str) -> Dict[str, Any]:
        """Searches GitHub users by name or handle and retrieves public profile and top repositories."""
        clean_query = query.strip()
        if not clean_query:
            return {"status": "EMPTY_QUERY", "error": "Query is empty"}

        timeout = getattr(settings, "WEB_REQUEST_TIMEOUT_SECONDS", 12)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                # 1. Search for users by name or login
                search_url = f"{self.api_base}/search/users"
                resp = await client.get(
                    search_url,
                    params={"q": f"{clean_query} in:name", "per_page": 3},
                    headers=self._get_headers()
                )

                if resp.status_code == 403:
                    return {"status": "RATE_LIMITED", "error": "GitHub API rate limit exceeded"}
                if resp.status_code != 200:
                    return {"status": "ERROR", "error": f"GitHub API error {resp.status_code}"}

                search_data = resp.json()
                items = search_data.get("items", [])

                # If no matches in:name, try searching login handle
                if not items:
                    resp_login = await client.get(
                        search_url,
                        params={"q": clean_query.replace(" ", ""), "per_page": 3},
                        headers=self._get_headers()
                    )
                    if resp_login.status_code == 200:
                        items = resp_login.json().get("items", [])

                if not items:
                    return {
                        "status": "SUCCESS",
                        "final_url": f"https://github.com/search?q={clean_query}&type=users",
                        "records_count": 0,
                        "text_content": f"No GitHub users found for query '{clean_query}'.",
                        "profiles": []
                    }

                # 2. Fetch full details for top matching user
                candidate = items[0]
                username = candidate.get("login")
                user_resp = await client.get(f"{self.api_base}/users/{username}", headers=self._get_headers())
                user_data = user_resp.json() if user_resp.status_code == 200 else candidate

                # 3. Fetch top public repos
                repos_resp = await client.get(
                    f"{self.api_base}/users/{username}/repos",
                    params={"sort": "updated", "per_page": 5},
                    headers=self._get_headers()
                )
                repos_data = repos_resp.json() if repos_resp.status_code == 200 else []

                repos_list = []
                technologies = set()
                if isinstance(repos_data, list):
                    for r in repos_data:
                        lang = r.get("language")
                        if lang:
                            technologies.add(lang)
                        repos_list.append({
                            "name": r.get("name"),
                            "description": r.get("description") or "No description",
                            "html_url": r.get("html_url"),
                            "stars": r.get("stargazers_count", 0),
                            "language": lang,
                            "topics": r.get("topics", [])
                        })

                name = user_data.get("name") or username
                bio = user_data.get("bio") or ""
                company = user_data.get("company") or ""
                location = user_data.get("location") or ""
                blog = user_data.get("blog") or ""
                public_repos_count = user_data.get("public_repos", 0)
                profile_url = user_data.get("html_url", f"https://github.com/{username}")

                summary_text = (
                    f"GitHub Profile: {name} (@{username})\n"
                    f"Profile URL: {profile_url}\n"
                    f"Bio: {bio}\n"
                    f"Company: {company}\n"
                    f"Location: {location}\n"
                    f"Website/Blog: {blog}\n"
                    f"Public Repositories: {public_repos_count}\n"
                    f"Top Technologies: {', '.join(sorted(technologies)) if technologies else 'Not specified'}\n\n"
                    f"Highlighted Repositories:\n"
                )
                for repo in repos_list[:4]:
                    summary_text += f"- {repo['name']} ({repo['language'] or 'General'}, ⭐ {repo['stars']}): {repo['description']} - {repo['html_url']}\n"

                return {
                    "status": "SUCCESS",
                    "final_url": profile_url,
                    "http_status": 200,
                    "title": f"GitHub: {name} (@{username})",
                    "text_content": summary_text,
                    "records_count": 1 + len(repos_list),
                    "extracted_data": {
                        "username": username,
                        "name": name,
                        "bio": bio,
                        "company": company,
                        "location": location,
                        "blog": blog,
                        "profile_url": profile_url,
                        "public_repos": public_repos_count,
                        "technologies": list(technologies),
                        "repositories": repos_list
                    }
                }

        except httpx.TimeoutException:
            return {"status": "TIMEOUT", "error": "GitHub request timed out"}
        except Exception as e:
            logger.error(f"GitHub provider error for {clean_query}: {e}")
            return {"status": "ERROR", "error": str(e)}

    async def fetch_public_webpage(self, url: str) -> Dict[str, Any]:
        """If given a full github.com/username URL, resolve username directly."""
        clean_url = url.strip()
        if "github.com/" in clean_url:
            username = clean_url.split("github.com/")[-1].split("/")[0].split("?")[0]
            return await self.search_person(username)
        return await self.search_person(clean_url)
