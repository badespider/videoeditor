-- Add idempotency constraint for usage records.
-- A given job should only create one usage record per billing period.

CREATE UNIQUE INDEX "usage_records_video_job_id_billing_period_key"
ON "usage_records" ("video_job_id", "billing_period");

