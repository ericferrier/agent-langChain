import asyncio

from app.services.jira_mock_couch import run_jira_worker_loop


if __name__ == "__main__":
    asyncio.run(run_jira_worker_loop())
