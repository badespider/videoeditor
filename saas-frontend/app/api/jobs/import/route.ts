/**
 * API Route: /api/jobs/import
 *
 * Creates a local Prisma `VideoJob` record after a successful direct-to-backend upload.
 * This keeps the dashboard consistent while the large file upload bypasses Vercel.
 */

import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/db";

export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user?.id) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const body = await request.json();
    const backendJobId = String(body?.backendJobId || "").trim();
    const videoId = String(body?.videoId || "").trim();
    const title = String(body?.title || "").trim() || "Untitled Video";

    if (!backendJobId || !videoId) {
      return NextResponse.json(
        { error: "Invalid payload", message: "backendJobId and videoId are required" },
        { status: 400 },
      );
    }

    const job = await prisma.videoJob.create({
      data: {
        userId: session.user.id,
        title,
        sourceVideoUrl: videoId,
        backendJobId,
        status: "PENDING",
        progress: 0,
      },
    });

    return NextResponse.json({ job_id: job.id });
  } catch (error) {
    console.error("Import job error:", error);
    return NextResponse.json({ error: "Failed to import job" }, { status: 500 });
  }
}


