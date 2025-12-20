"""
Redis-backed smoke test for atomic job status transitions.

Run from repo root (PowerShell):
  python backend\\scripts\\job_atomic_smoke.py
"""

from __future__ import annotations

import sys
import threading
import time


def main() -> int:
    # Allow `from app...` imports when running directly from repo root.
    sys.path.insert(0, "backend")

    from app.services.job_manager import JobManager  # noqa: WPS433
    from app.models import JobStatus  # noqa: WPS433

    jm = JobManager()
    jm.redis.ping()
    print("redis:ping ok")

    # 1) Completed should not flip to failed
    job1 = jm.create_job(video_id="vid_test", filename="test.mp4")
    jm.complete_job_if_not_failed(job_id=job1, output_url="out1", scenes=[{"index": 0}])
    applied = jm.fail_job_if_not_completed(job_id=job1, error_message="late error")
    job1d = jm.get_job(job1)
    print("test1 late-fail-applied", applied)
    print("test1 status", job1d["status"])
    assert job1d["status"] == JobStatus.COMPLETED.value
    assert applied is False

    # 2) Failed should not flip to completed
    job2 = jm.create_job(video_id="vid_test2", filename="test2.mp4")
    jm.fail_job_if_not_completed(job_id=job2, error_message="cancelled")
    applied2 = jm.complete_job_if_not_failed(job_id=job2, output_url="out2", scenes=[{"index": 0}])
    job2d = jm.get_job(job2)
    print("test2 complete-after-fail-applied", applied2)
    print("test2 status", job2d["status"])
    assert job2d["status"] == JobStatus.FAILED.value
    assert applied2 is False

    # 3) Concurrency: one completes, one fails; final is terminal and stable.
    job3 = jm.create_job(video_id="vid_test3", filename="test3.mp4")
    results = []

    def do_complete() -> None:
        results.append(("complete", jm.complete_job_if_not_failed(job_id=job3, output_url="out3", scenes=[])))

    def do_fail() -> None:
        time.sleep(0.01)
        results.append(("fail", jm.fail_job_if_not_completed(job_id=job3, error_message="boom")))

    t1 = threading.Thread(target=do_complete)
    t2 = threading.Thread(target=do_fail)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    job3d = jm.get_job(job3)
    print("test3 results", results)
    print("test3 final status", job3d["status"])
    assert job3d["status"] in (JobStatus.COMPLETED.value, JobStatus.FAILED.value)

    # Cleanup
    jm.delete_job(job1)
    jm.delete_job(job2)
    jm.delete_job(job3)

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


