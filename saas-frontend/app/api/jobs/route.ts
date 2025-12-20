/**
 * API Route: /api/jobs
 * 
 * Proxies job listing requests to the backend API.
 */

import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/db";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    
    if (!session?.user?.id) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    // Get jobs from local database
    const jobs = await prisma.videoJob.findMany({
      where: { userId: session.user.id },
      orderBy: { createdAt: "desc" },
      take: 50,
    });

    // Transform to expected format
    const formattedJobs = jobs.map((job) => ({
      id: job.id,
      title: job.title,
      status: job.status,
      progress: job.progress,
      currentStep: job.currentStep,
      errorMessage: job.errorMessage,
      sourceVideoUrl: job.sourceVideoUrl,
      outputVideoUrl: job.outputVideoUrl,
      durationSeconds: job.durationSeconds,
      createdAt: job.createdAt.toISOString(),
      updatedAt: job.updatedAt.toISOString(),
      completedAt: job.completedAt?.toISOString() || null,
    }));

    return NextResponse.json({ jobs: formattedJobs, total: jobs.length });
  } catch (error) {
    console.error("Failed to fetch jobs:", error);
    return NextResponse.json(
      { error: "Failed to fetch jobs" },
      { status: 500 }
    );
  }
}

export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    
    if (!session?.user?.id) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const body = await request.json();

    // Create job in backend
    const backendResponse = await fetch(`${API_URL}/api/jobs`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...body,
        user_id: session.user.id,
      }),
    });

    if (!backendResponse.ok) {
      const error = await backendResponse.json();
      return NextResponse.json(error, { status: backendResponse.status });
    }

    const backendData = await backendResponse.json();

    // Create local database record
    const job = await prisma.videoJob.create({
      data: {
        userId: session.user.id,
        title: body.title || "Untitled Video",
        sourceVideoUrl: body.video_url,
        backendJobId: backendData.job_id,
        status: "PENDING",
        progress: 0,
      },
    });

    return NextResponse.json({
      job_id: job.id,
      backend_job_id: backendData.job_id,
      status: "pending",
    });
  } catch (error) {
    console.error("Failed to create job:", error);
    return NextResponse.json(
      { error: "Failed to create job" },
      { status: 500 }
    );
  }
}

