/**
 * API Route: /api/jobs
 * 
 * Proxies job listing requests to the backend API.
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

export async function GET(request: NextRequest) {
  try {
    const API_URL = getApiUrl();
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

    // Sync a small number of non-terminal jobs with backend so the list doesn't get "stuck" for hours
    // (the job detail page already syncs, but many users only look at the list).
    const jobsToSync = jobs
      .filter(
        (j) =>
          !!j.backendJobId &&
          (j.status === "PENDING" ||
            j.status === "PROCESSING" ||
            (j.status === "COMPLETED" && !j.outputVideoUrl)),
      )
      .slice(0, 10);

    if (jobsToSync.length > 0) {
      await Promise.all(
        jobsToSync.map(async (job) => {
          try {
            const backendResponse = await fetch(`${API_URL}/api/jobs/${job.backendJobId}`);
            if (!backendResponse.ok) return;
            const backendData = await backendResponse.json();

            // Backend `/api/jobs/:id` returns JobProgress but not output_url; fetch /result when completed.
            let outputUrlFromResult: string | null = null;
            if (backendData.status === "completed") {
              try {
                const resultRes = await fetch(`${API_URL}/api/jobs/${job.backendJobId}/result`);
                if (resultRes.ok) {
                  const resultData = await resultRes.json();
                  outputUrlFromResult = resultData.output_url || null;
                }
              } catch {
                // ignore
              }
            }

            const statusMap: Record<
              string,
              "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED" | "CANCELLED"
            > = {
              pending: "PENDING",
              processing: "PROCESSING",
              completed: "COMPLETED",
              failed: "FAILED",
              cancelled: "CANCELLED",
            };

            const newStatus = statusMap[backendData.status] || job.status;
            const mergedOutputUrl =
              outputUrlFromResult || backendData.output_url || job.outputVideoUrl;

            const shouldUpdate =
              newStatus !== job.status ||
              backendData.progress !== job.progress ||
              backendData.current_step !== job.currentStep ||
              backendData.error_message !== job.errorMessage ||
              (newStatus === "COMPLETED" &&
                !!mergedOutputUrl &&
                mergedOutputUrl !== job.outputVideoUrl);

            if (!shouldUpdate) return;

            await prisma.videoJob.update({
              where: { id: job.id },
              data: {
                status: newStatus,
                progress: backendData.progress ?? job.progress,
                currentStep: backendData.current_step ?? job.currentStep,
                errorMessage: backendData.error_message ?? job.errorMessage,
                outputVideoUrl: mergedOutputUrl,
                durationSeconds: backendData.duration_seconds ?? job.durationSeconds,
                completedAt: backendData.completed_at ? new Date(backendData.completed_at) : job.completedAt,
              },
            });
          } catch {
            // ignore sync failures; we'll still return local DB state
          }
        }),
      );
    }

    // Re-read after sync so UI reflects any updates.
    const freshJobs =
      jobsToSync.length > 0
        ? await prisma.videoJob.findMany({
            where: { userId: session.user.id },
            orderBy: { createdAt: "desc" },
            take: 50,
          })
        : jobs;

    // Transform to expected format
    const formattedJobs = freshJobs.map((job) => ({
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

    return NextResponse.json({ jobs: formattedJobs, total: freshJobs.length });
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
    const API_URL = getApiUrl();
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

