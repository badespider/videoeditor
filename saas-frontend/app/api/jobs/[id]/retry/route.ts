/**
 * API Route: /api/jobs/[id]/retry
 * 
 * Retry a failed job.
 */

import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/db";

function getApiUrl() {
  const url =
    process.env.NEXT_PUBLIC_API_URL ||
    (process.env.NODE_ENV === "production" ? "" : "http://localhost:8000");
  if (process.env.NODE_ENV === "production" && !url) {
    throw new Error("Missing NEXT_PUBLIC_API_URL");
  }
  return url;
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const API_URL = getApiUrl();
    const session = await auth();
    const awaitedParams = await params;
    
    if (!session?.user?.id) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const job = await prisma.videoJob.findFirst({
      where: {
        id: awaitedParams.id,
        userId: session.user.id,
      },
    });

    if (!job) {
      return NextResponse.json({ error: "Job not found" }, { status: 404 });
    }

    if (job.status !== "FAILED") {
      return NextResponse.json(
        { error: "Can only retry failed jobs" },
        { status: 400 }
      );
    }

    // Retry in backend
    let newBackendJobId = job.backendJobId;
    if (job.backendJobId) {
      try {
        const response = await fetch(`${API_URL}/api/jobs/${job.backendJobId}/retry`, {
          method: "POST",
        });
        if (response.ok) {
          const data = await response.json();
          newBackendJobId = data.new_job_id;
        }
      } catch (error) {
        console.error("Failed to retry in backend:", error);
      }
    }

    // Create new job record
    const newJob = await prisma.videoJob.create({
      data: {
        userId: session.user.id,
        title: job.title ? `${job.title} (Retry)` : "Untitled Video (Retry)",
        sourceVideoUrl: job.sourceVideoUrl,
        backendJobId: newBackendJobId,
        status: "PENDING",
        progress: 0,
      },
    });

    return NextResponse.json({
      success: true,
      new_job_id: newJob.id,
      old_job_id: job.id,
    });
  } catch (error) {
    console.error("Failed to retry job:", error);
    return NextResponse.json(
      { error: "Failed to retry job" },
      { status: 500 }
    );
  }
}

