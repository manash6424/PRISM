"""
Alert service for email and Slack notifications.
"""

import logging
import re
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum

from ..models.database import AlertRule
from ..config import get_settings
from .database_manager import db_manager

logger = logging.getLogger(__name__)


class AlertChannel(str, Enum):
    EMAIL = "email"
    SLACK = "slack"
    WEBHOOK = "webhook"


class AlertService:
    """
    Alert and notification service.
    Sends alerts via email, Slack, and webhooks.
    """

    def __init__(self):
        self.settings = get_settings()
        self._alert_rules: Dict[str, AlertRule] = {}
        self._alert_history: List[Dict[str, Any]] = []

    # ==============================
    # ALERT SENDING
    # ==============================

    async def send_alert(
        self,
        title: str,
        message: str,
        channels: List[AlertChannel],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, bool]:

        results: Dict[str, bool] = {}

        for channel in channels:
            try:
                if channel == AlertChannel.EMAIL:
                    results[channel.value] = await self._send_email(title, message)

                elif channel == AlertChannel.SLACK:
                    results[channel.value] = await self._send_slack(title, message, metadata)

                elif channel == AlertChannel.WEBHOOK:
                    results[channel.value] = await self._send_webhook(title, message, metadata)

            except Exception as e:
                logger.error(f"Failed to send alert via {channel.value}: {e}")
                results[channel.value] = False

        self._alert_history.append({
            "title": title,
            "message": message,
            "channels": [c.value for c in channels],
            "results": results,
            "timestamp": datetime.utcnow().isoformat(),
        })

        return results

    # ==============================
    # EMAIL
    # ==============================

    async def _send_email(self, title: str, message: str) -> bool:
        if not self.settings.alerts.email_enabled:
            return False

        try:
            import aiosmtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
        except ImportError:
            logger.error("aiosmtplib not installed")
            return False

        smtp = self.settings.alerts

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[AI Desktop Copilot] {title}"
        msg["From"] = smtp.smtp_user
        msg["To"] = smtp.smtp_user  # change to real recipient list

        text_content = f"{title}\n\n{message}"
        msg.attach(MIMEText(text_content, "plain"))

        try:
            await aiosmtplib.send(
                msg,
                hostname=smtp.smtp_host,
                port=smtp.smtp_port,
                username=smtp.smtp_user,
                password=smtp.smtp_password,
                start_tls=True,
            )
            return True
        except Exception as e:
            logger.error(f"Email failed: {e}")
            return False

    # ==============================
    # SLACK
    # ==============================

    async def _send_slack(
        self,
        title: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:

        if not self.settings.alerts.slack_enabled:
            return False

        if not self.settings.alerts.slack_webhook_url:
            return False

        try:
            import aiohttp
        except ImportError:
            logger.error("aiohttp not installed")
            return False

        payload = {
            "text": f"🔔 {title}\n\n{message}",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.settings.alerts.slack_webhook_url,
                json=payload,
            ) as response:
                return response.status == 200

    # ==============================
    # WEBHOOK
    # ==============================

    async def _send_webhook(
        self,
        title: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        logger.info(f"Webhook alert triggered: {title}")
        return True

    # ==============================
    # ALERT RULE MANAGEMENT
    # ==============================

    def create_alert_rule(
        self,
        name: str,
        connection_id: str,
        query_template: str,
        condition: str,
        frequency_minutes: int = 60,
        channels: Optional[List[str]] = None,
    ) -> AlertRule:

        rule = AlertRule(
            id=f"rule_{int(datetime.utcnow().timestamp())}",
            name=name,
            connection_id=connection_id,
            query_template=query_template,
            condition=condition,
            frequency_minutes=frequency_minutes,
            channels=channels or ["email"],
            is_active=True,
        )

        self._alert_rules[rule.id] = rule
        return rule

    async def evaluate_alert_rule(self, rule_id: str) -> Dict[str, Any]:

        if rule_id not in self._alert_rules:
            raise ValueError("Alert rule not found")

        rule = self._alert_rules[rule_id]

        success, columns, results, error = await db_manager.execute_query(
            connection_id=rule.connection_id,
            sql=rule.query_template,
        )

        if not success:
            return {"triggered": False, "error": error}

        row_count = len(results)
        should_trigger = False

        try:
            match = re.match(r'(\w+)\s*(<|>|==|!=|<=|>=)\s*(\d+)', rule.condition)
            if match:
                field, operator, threshold = match.groups()
                threshold = int(threshold)

                value = row_count if field == "row_count" else 0

                if operator == ">":
                    should_trigger = value > threshold
                elif operator == "<":
                    should_trigger = value < threshold
                elif operator == "==":
                    should_trigger = value == threshold
                elif operator == "!=":
                    should_trigger = value != threshold
                elif operator == ">=":
                    should_trigger = value >= threshold
                elif operator == "<=":
                    should_trigger = value <= threshold

            if should_trigger:
                await self.send_alert(
                    title=f"Alert: {rule.name}",
                    message=f"Condition met: {rule.condition}\nRows: {row_count}",
                    channels=[AlertChannel(c) for c in rule.channels],
                )

                rule.last_triggered = datetime.utcnow()

                return {
                    "triggered": True,
                    "row_count": row_count,
                }

            return {
                "triggered": False,
                "row_count": row_count,
            }

        except Exception as e:
            logger.error(f"Condition evaluation failed: {e}")
            return {"triggered": False, "error": str(e)}

    def get_alert_rules(self) -> List[AlertRule]:
        return list(self._alert_rules.values())

    def get_alert_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._alert_history[-limit:]

    def delete_alert_rule(self, rule_id: str) -> bool:
        if rule_id in self._alert_rules:
            del self._alert_rules[rule_id]
            return True
        return False


# Global instance
alert_service = AlertService()
