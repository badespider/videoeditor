/**
 * API Route: /api/webhooks/jobs
 * 
 * Webhook endpoint for backend to update job status.
 * This allows the backend to push status updates to the frontend database.
 */

import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";

// Webhook secret for verification (should be set in both backend and frontend)
const WEBHOOK_SECRET = process.env.WEBHOOK_SECRET || "your-webhook-secret";

export async function POST(request: NextRequest) {
  try {
    // Verify webhook secret
    const authHeader = request.headers.get("authorization");
    if (authHeader !== `Bearer ${WEBHOOK_SECRET}`) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const body = await request.json();
    const { backend_job_id, status, progress, current_step, error_message, output_url, duration_seconds, completed_at } = body;

    if (!backend_job_id) {
      return NextResponse.json({ error: "Missing backend_job_id" }, { status: 400 });
    }

    // Find job by backend job ID
    const job = await prisma.videoJob.findFirst({
      where: { backendJobId: backend_job_id },
    });

    if (!job) {
      return NextResponse.json({ error: "Job not found" }, { status: 404 });
    }

    // Map backend status to Prisma enum
    const statusMap: Record<string, "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED" | "CANCELLED"> = {
      pending: "PENDING",
      processing: "PROCESSING",
      completed: "COMPLETED",
      failed: "FAILED",
      cancelled: "CANCELLED",
    };

    // Update job
    const updatedJob = await prisma.videoJob.update({
      where: { id: job.id },
      data: {
        ...(status && { status: statusMap[status] || job.status }),
        ...(progress !== undefined && { progress }),
        ...(current_step && { currentStep: current_step }),
        ...(error_message && { errorMessage: error_message }),
        ...(output_url && { outputVideoUrl: output_url }),
        ...(duration_seconds && { durationSeconds: duration_seconds }),
        ...(completed_at && { completedAt: new Date(completed_at) }),
      },
    });

    // If job completed, record usage
    if (status === "completed" && duration_seconds) {
      const billingPeriod = new Date().toISOString().slice(0, 7); // YYYY-MM
      
      await prisma.usageRecord.create({
        data: {
          userId: job.userId,
          videoJobId: job.id,
          minutesUsed: duration_seconds / 60,
          billingPeriod,
        },
      });
    }

    return NextResponse.json({ success: true, job_id: updatedJob.id });
  } catch (error) {
    console.error("Webhook error:", error);
    return NextResponse.json(
      { error: "Failed to process webhook" },
      { status: 500 }
    );
  }
}

