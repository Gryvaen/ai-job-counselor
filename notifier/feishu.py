"""
Feishu (飞书) webhook notifier — sends rich text card messages.
"""

from models.job import Job
from models.match import MatchResult
from config.settings import settings
import httpx


class FeishuNotifier:
    """Wraps Feishu webhook API for job alert / resume advice / summary notifications."""

    def __init__(self, webhook: str | None = None):
        self.webhook = webhook or settings.feishu_webhook

    def send_job_alert(self, job: Job, match: MatchResult) -> bool:
        """Send a single job alert message to Feishu."""
        if not self.webhook:
            print("[notifier] Feishu webhook not configured, skipping.")
            return False

        cards = [
            {"tag": "div", "text": {"content": f"**【JobMatch 推荐】**", "tag": "lmd"}},
            {"tag": "hr"},
            {"tag": "div", "text": {"content": f"**{job.title}**", "tag": "lmd"}},
            {"tag": "div", "text": {"content": f"🏢 {job.company}  💰 {job.salary}  📍 {job.city}", "tag": "lmd"}},
            {"tag": "div", "text": {"content": f"⭐ 匹配度: {match.score}  💡 {match.suggest}", "tag": "lmd"}},
        ]

        if match.advantages:
            adv_text = "\n".join(f"• {a}" for a in match.advantages[:5])
            cards.append({"tag": "div", "text": {"content": f"**优势：**\n{adv_text}", "tag": "lmd"}})

        if match.missing:
            miss_text = "\n".join(f"• {m}" for m in match.missing[:5])
            cards.append({"tag": "div", "text": {"content": f"**缺失：**\n{miss_text}", "tag": "lmd"}})

        if job.url:
            cards.append({"tag": "action", "actions": [{"tag": "button", "text": {"content": "查看职位详情", "tag": "plain_text"}, "url": job.url, "type": "primary"}]})

        payload = {"msg_type": "interactive", "card": {"elements": cards, "header": {"title": {"content": f"🔔 {job.company} - {job.title}", "tag": "plain_text"}}}}
        return self._send(payload)

    def send_summary(self, results: list[tuple[Job, MatchResult]], total_scraped: int) -> bool:
        if not self.webhook or not results:
            return False

        content = f"**今日推送总结**\n"
        content += f"共采集 {total_scraped} 个岗位，推荐 {len(results)} 个\n\n"
        for job, match in results[:10]:
            content += f"• **{match.score}分** | {job.company} - {job.title} ({job.city}) {job.salary}\n"

        payload = {"msg_type": "interactive", "card": {"elements": [{"tag": "div", "text": {"content": content, "tag": "lmd"}}], "header": {"title": {"content": "📊 今日推荐", "tag": "plain_text"}}}}
        return self._send(payload)

    def send_resume_advice(self, resume_text: str) -> bool:
        payload = {"msg_type": "interactive", "card": {"elements": [{"tag": "div", "text": {"content": resume_text, "tag": "lmd"}}], "header": {"title": {"content": "📝 简历优化建议", "tag": "plain_text"}}}}
        return self._send(payload)

    def _send(self, payload: dict) -> bool:
        try:
            resp = httpx.post(self.webhook, json=payload, timeout=10)
            data = resp.json()
            if data.get("code") == 0 or data.get("StatusCode") == 0:
                print(f"[notifier] Feishu message sent successfully.")
                return True
            print(f"[notifier] Feishu API error: {data}")
        except Exception as e:
            print(f"[notifier] Failed to send to Feishu: {e}")
        return False
