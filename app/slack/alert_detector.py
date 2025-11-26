"""
Alert Detection Utility for Slack Messages
Detects if a message is an alert from monitoring tools like Grafana, Sentry, PagerDuty, etc.
"""

import re
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class AlertDetector:
    """
    Detects and parses alerts from various monitoring platforms
    """

    # Known monitoring bot names (lowercase for comparison)
    KNOWN_ALERT_BOTS = {
        "sentry": "sentry",
        "grafana": "grafana",
        "pagerduty": "pagerduty",
        "datadog": "datadog",
        "opsgenie": "opsgenie",
        "alertmanager": "grafana",
        "prometheus": "grafana",
    }

    @staticmethod
    def _get_bot_name(event: Optional[Dict[str, Any]]) -> Optional[str]:
        """
        Extract bot name from event's bot_profile.

        Args:
            event: The Slack event dictionary

        Returns:
            Lowercase bot name if found, None otherwise
        """
        if not event:
            return None

        bot_profile = event.get("bot_profile")
        if not bot_profile:
            return None

        bot_name = bot_profile.get("name")
        if not bot_name:
            return None

        return bot_name.lower()

    @staticmethod
    def _detect_platform_by_bot(event: Optional[Dict[str, Any]]) -> Optional[str]:
        """
        Detect alert platform by checking bot_profile.name.

        Args:
            event: The Slack event dictionary

        Returns:
            Platform name if detected, None otherwise
        """
        bot_name = AlertDetector._get_bot_name(event)
        if not bot_name:
            return None

        # Check if bot name matches any known alert bot
        for known_bot, platform in AlertDetector.KNOWN_ALERT_BOTS.items():
            if known_bot in bot_name:
                logger.info(f"Detected alert from bot: {bot_name} -> platform: {platform}")
                return platform

        return None


    @staticmethod
    def is_alert(
        message_text: str,
        bot_user_id: Optional[str] = None,
        event: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Check if a message appears to be an alert from a monitoring tool.

        Detection is based solely on bot_profile.name for known monitoring bots.

        Args:
            message_text: The Slack message text
            bot_user_id: The bot's user ID (to ignore bot mentions)
            event: The full Slack event dictionary

        Returns:
            True if message appears to be an alert, False otherwise
        """
        if not message_text:
            return False

        # Ignore messages that mention our bot (avoid loops)
        if bot_user_id and f"<@{bot_user_id}>" in message_text:
            logger.debug("Message mentions bot, ignoring for auto-detection")
            return False

        # Check bot_profile.name only
        if AlertDetector._detect_platform_by_bot(event):
            return True

        return False

    @staticmethod
    def extract_alert_info(
        message_text: str,
        event: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Optional[str]]:
        """
        Extract key information from an alert message.

        Args:
            message_text: The Slack message text
            event: The full Slack event dictionary

        Returns:
            Dictionary with alert metadata:
            - platform: grafana, sentry, pagerduty, etc.
            - severity: critical, high, medium, low, or None
            - service_name: Extracted service name if found
            - alert_name: Extracted alert name if found
        """
        info = {
            "platform": "generic",
            "severity": None,
            "service_name": None,
            "alert_name": None,
        }

        # Detect platform by bot name only
        platform = AlertDetector._detect_platform_by_bot(event)
        if platform:
            info["platform"] = platform

        # Extract severity
        severity_match = re.search(
            r"(critical|high|medium|low)\s*(severity|priority)?",
            message_text,
            re.IGNORECASE,
        )
        if severity_match:
            info["severity"] = severity_match.group(1).lower()

        # Extract alert name from Grafana format
        alertname_match = re.search(r'alertname=["\']*([^"\'\s,}]+)', message_text)
        if alertname_match:
            info["alert_name"] = alertname_match.group(1)

        # Extract alert name from square brackets (common format)
        bracket_match = re.search(r"\[([^\]]+)\]", message_text)
        if bracket_match and not info["alert_name"]:
            potential_name = bracket_match.group(1)
            # Filter out non-alert names
            if not any(
                x in potential_name.lower() for x in ["firing", "resolved", "sentry"]
            ):
                info["alert_name"] = potential_name

        # Extract service name
        service_patterns = [
            r"service[:\s]+([a-zA-Z0-9\-_]+)",
            r"(?:in|on|for)\s+([a-zA-Z0-9\-_]+)\s+service",
            r"([a-zA-Z0-9\-_]+)\s+is\s+(?:down|unavailable|degraded)",
        ]

        for pattern in service_patterns:
            match = re.search(pattern, message_text, re.IGNORECASE)
            if match:
                info["service_name"] = match.group(1)
                break

        logger.debug(f"Extracted alert info: {info}")
        return info

    @staticmethod
    def should_auto_respond(
        message_text: str,
        bot_user_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        event: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Determine if bot should automatically respond to this message.

        Args:
            message_text: The Slack message text
            bot_user_id: The bot's user ID
            channel_id: The Slack channel ID
            event: The full Slack event dictionary

        Returns:
            Tuple of (should_respond: bool, reason: str)
        """


        # Don't auto-respond to messages mentioning our bot
        if bot_user_id and f"<@{bot_user_id}>" in message_text:
            return False, "Message mentions bot (likely a reply)"

        # Check if it's an alert
        if not AlertDetector.is_alert(message_text, bot_user_id, event):
            return False, "Not detected as an alert"

        # Extract alert info for logging
        alert_info = AlertDetector.extract_alert_info(message_text, event)
        platform = alert_info.get("platform", "generic")
        severity = alert_info.get("severity", "unknown")

        logger.info(
            f"Auto-respond triggered for {platform} alert (severity: {severity}) in channel {channel_id}"
        )

        return True, f"Detected {platform} alert"


# Singleton instance
alert_detector = AlertDetector()
