"""
notify_node.py — Send high-score job alerts via Feishu.
"""

from notifier import FeishuNotifier
from storage.db import get_engine, get_session, save_match, save_notification
from config.settings import settings
from models.agent_state import AgentState


def notify_node(state: AgentState) -> dict:
    match_results = state["match_results"]
    threshold = state["threshold"]
    jobs = state["jobs"]

    high_results = [r for r in match_results if r.score >= threshold]
    if not high_results:
        print("[agent/notify] No high-score matches to notify.")
        return {"notified": []}

    notifier = FeishuNotifier()
    notified_ids = []
    job_map = {j.id: j for j in jobs}

    for match in high_results:
        job = job_map.get(match.job_id)
        if not job:
            continue
        print(f"[agent/notify] Sending alert for {job.title} @ {job.company} (score={match.score})")
        notifier.send_job_alert(job, match)
        notified_ids.append(match.job_id)
        try:
            get_engine(settings.db_path)
            with get_session() as sess:
                save_match(sess, match)
                save_notification(sess, match.job_id, {
                    "score": match.score, "suggest": match.suggest,
                    "advantages": match.advantages, "missing": match.missing,
                })
                sess.commit()
        except Exception as e:
            print(f"[agent/notify] Persist failed for {match.job_id}: {e}")

    high_tuples = [(job_map[r.job_id], r) for r in high_results if r.job_id in job_map]
    notifier.send_summary(high_tuples, total_scraped=len(jobs))
    print(f"[agent/notify] Notified {len(notified_ids)} jobs via Feishu")
    return {"notified": notified_ids}
