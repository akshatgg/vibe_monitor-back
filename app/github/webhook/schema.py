"""
GitHub Webhook Event Schemas

When users install/uninstall your GitHub App, GitHub sends webhook events to your API.
This file defines the structure of those webhook payloads.

Documentation: https://docs.github.com/en/webhooks/webhook-events-and-payloads
"""

from pydantic import BaseModel
from typing import Optional, Dict, Any, List


class GitHubAccount(BaseModel):
    """
    GitHub user or organization account

    Example:
    {
        "id": 123456,
        "login": "akshatgg",
        "type": "User"
    }
    """

    id: int
    login: str  # GitHub username or org name
    type: str  # "User" or "Organization"


class GitHubInstallation(BaseModel):
    """
    GitHub App installation details

    Example:
    {
        "id": 789012,
        "account": {...}
    }
    """

    id: int  # This is the installation_id you store in DB
    account: GitHubAccount


class InstallationWebhookPayload(BaseModel):
    """
    Webhook payload when app is installed/uninstalled

    GitHub sends this when:
    - installation.created: User installed the app ✅
    - installation.deleted: User uninstalled the app ❌ (WE HANDLE THIS!)
    - installation.suspend: App suspended
    - installation.unsuspend: App unsuspended

    Example payload for deletion:
    {
        "action": "deleted",
        "installation": {
            "id": 789012,
            "account": {
                "id": 123456,
                "login": "akshatgg",
                "type": "User"
            }
        }
    }
    """

    action: str  # "created", "deleted", "suspend", "unsuspend"
    installation: GitHubInstallation
    repositories: Optional[List[Dict[str, Any]]] = None
    sender: Optional[GitHubAccount] = None


class InstallationRepositoriesWebhookPayload(BaseModel):
    """
    Webhook payload when repository access changes

    GitHub sends this when:
    - installation_repositories.added: User gave app access to more repos
    - installation_repositories.removed: User revoked app access to some repos
    """

    action: str  # "added" or "removed"
    installation: GitHubInstallation
    repositories_added: Optional[List[Dict[str, Any]]] = None
    repositories_removed: Optional[List[Dict[str, Any]]] = None
    sender: Optional[GitHubAccount] = None
