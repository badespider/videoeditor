/**
 * API Route: /api/jobs/[id]
 * 
 * Handles individual job operations (get, delete).
 */

import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/db";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
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

    // Sync with backend if job is still processing
    if (job.backendJobId && (job.status === "PENDING" || job.status === "PROCESSING" || (job.status === "COMPLETED" && !job.outputVideoUrl))) {
      try {
        const backendResponse = await fetch(`${API_URL}/api/jobs/${job.backendJobId}`);
        if (backendResponse.ok) {
          const backendData = await backendResponse.json();

          // IMPORTANT:
          // Backend `/api/jobs/:id` returns JobProgress (status/progress/current_step),
          // but DOES NOT include `output_url`. The `output_url` lives on `/api/jobs/:id/result`.
          // If backend reports completed and we don't have output yet, fetch result to get the URL.
          let outputUrlFromResult: string | null = null;
          if (backendData.status === "completed") {
            try {
              const resultRes = await fetch(`${API_URL}/api/jobs/${job.backendJobId}/result`);
              if (resultRes.ok) {
                const resultData = await resultRes.json();
                outputUrlFromResult = resultData.output_url || null;
              }
            } catch (e) {
              console.error("Failed to fetch backend job result:", e);
            }
          }
          
          // Map backend status to our enum
          const statusMap: Record<string, "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED" | "CANCELLED"> = {
            pending: "PENDING",
            processing: "PROCESSING",
            completed: "COMPLETED",
            failed: "FAILED",
            cancelled: "CANCELLED",
          };

          // Update local record if status changed
          const newStatus = statusMap[backendData.status] || job.status;
          const mergedOutputUrl = outputUrlFromResult || backendData.output_url || job.outputVideoUrl;
          const shouldUpdate =
            newStatus !== job.status ||
            backendData.progress !== job.progress ||
            backendData.current_step !== job.currentStep ||
            backendData.error_message !== job.errorMessage ||
            (newStatus === "COMPLETED" && !!mergedOutputUrl && mergedOutputUrl !== job.outputVideoUrl);

          if (shouldUpdate) {
            const updatedJob = await prisma.videoJob.update({
              where: { id: job.id },
              data: {
                status: newStatus,
                progress: backendData.progress || job.progress,
                currentStep: backendData.current_step || job.currentStep,
                errorMessage: backendData.error_message || job.errorMessage,
                outputVideoUrl: mergedOutputUrl,
                durationSeconds: backendData.duration_seconds || job.durationSeconds,
                completedAt: backendData.completed_at ? new Date(backendData.completed_at) : job.completedAt,
              },
            });

            return NextResponse.json({
              id: updatedJob.id,
              title: updatedJob.title,
              status: updatedJob.status,
              progress: updatedJob.progress,
              currentStep: updatedJob.currentStep,
              errorMessage: updatedJob.errorMessage,
              sourceVideoUrl: updatedJob.sourceVideoUrl,
              outputVideoUrl: updatedJob.outputVideoUrl,
              durationSeconds: updatedJob.durationSeconds,
              createdAt: updatedJob.createdAt.toISOString(),
              updatedAt: updatedJob.updatedAt.toISOString(),
              completedAt: updatedJob.completedAt?.toISOString() || null,
            });
          }
        }
      } catch (error) {
        console.error("Failed to sync with backend:", error);
        // Continue with local data
      }
    }

    return NextResponse.json({
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
    });
  } catch (error) {
    console.error("Failed to fetch job:", error);
    return NextResponse.json(
      { error: "Failed to fetch job" },
      { status: 500 }
    );
  }
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
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

    // Delete from backend
    if (job.backendJobId) {
      try {
        await fetch(`${API_URL}/api/jobs/${job.backendJobId}`, {
          method: "DELETE",
        });
      } catch (error) {
        console.error("Failed to delete from backend:", error);
      }
    }

    // Delete local record
    await prisma.videoJob.delete({
      where: { id: job.id },
    });

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Failed to delete job:", error);
    return NextResponse.json(
      { error: "Failed to delete job" },
      { status: 500 }
    );
  }
}

