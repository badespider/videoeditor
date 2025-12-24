/**
 * API Route: /api/jobs/[id]/download
 *
 * Returns a fresh, non-expired download URL by fetching the backend job result
 * and redirecting the browser to the latest presigned output_url.
 *
 * This avoids storing/using expired presigned URLs in the frontend DB.
 */

import { NextResponse } from "next/server";

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

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const API_URL = getApiUrl();
    const session = await auth();
    const awaitedParams = await params;

    if (!session?.user?.id) {
      return new NextResponse("Unauthorized", { status: 401 });
    }

    const job = await prisma.videoJob.findFirst({
      where: { id: awaitedParams.id, userId: session.user.id },
      select: { backendJobId: true, status: true },
    });

    if (!job) {
      return new NextResponse("Job not found", { status: 404 });
    }

    if (!job.backendJobId) {
      return new NextResponse("Missing backend job id", { status: 400 });
    }

    // Always fetch fresh result URL (backend now regenerates presigned output_url per request).
    const resultRes = await fetch(
      `${API_URL}/api/jobs/${job.backendJobId}/result`,
      { method: "GET" },
    );

    if (!resultRes.ok) {
      const text = await resultRes.text().catch(() => "");
      return new NextResponse(text || "Unable to fetch job result", {
        status: resultRes.status,
      });
    }

    const resultData = (await resultRes.json()) as { output_url?: string | null };
    const url = resultData.output_url;
    if (!url) {
      return new NextResponse("Output not available yet", { status: 409 });
    }

    const res = NextResponse.redirect(url, 307);
    // Avoid caching redirects to time-limited URLs
    res.headers.set("Cache-Control", "no-store");
    return res;
  } catch (e) {
    console.error("Download redirect failed:", e);
    return new NextResponse("Download failed", { status: 500 });
  }
}

