import asyncio

from app.services.reference_lookup_jira import run_reference_worker_loop


if __name__ == "__main__":
    asyncio.run(run_reference_worker_loop())
