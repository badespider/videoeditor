/**
 * API Route: /api/jobs/[id]/cancel
 * 
 * Cancel a running job.
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

    if (job.status !== "PENDING" && job.status !== "PROCESSING") {
      return NextResponse.json(
        { error: "Can only cancel pending or processing jobs" },
        { status: 400 }
      );
    }

    // Cancel in backend
    if (job.backendJobId) {
      try {
        await fetch(`${API_URL}/api/jobs/${job.backendJobId}`, {
          method: "DELETE",
        });
      } catch (error) {
        console.error("Failed to cancel in backend:", error);
      }
    }

    // Update local record
    const updatedJob = await prisma.videoJob.update({
      where: { id: job.id },
      data: { status: "CANCELLED" },
    });

    return NextResponse.json({ success: true, job: updatedJob });
  } catch (error) {
    console.error("Failed to cancel job:", error);
    return NextResponse.json(
      { error: "Failed to cancel job" },
      { status: 500 }
    );
  }
}

