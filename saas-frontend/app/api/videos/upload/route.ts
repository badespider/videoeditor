/**
 * API Route: /api/videos/upload
 * 
 * Handles video file uploads by proxying to the backend.
 * Includes subscription validation and quota checking.
 */

import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/db";
import { getUserSubscriptionPlan } from "@/lib/subscription";
import { getCurrentUsage, hasRemainingQuota } from "@/lib/api/usage-service";
import { sign } from "jsonwebtoken";

const JWT_SECRET = process.env.AUTH_SECRET || "";

// Plan limits in minutes
const PLAN_LIMITS: Record<string, number> = {
  creator: 60,
  studio: 180,
};

function getApiUrl() {
  const url =
    process.env.NEXT_PUBLIC_API_URL ||
    (process.env.NODE_ENV === "production" ? "" : "http://localhost:8000");
  if (process.env.NODE_ENV === "production" && !url) {
    throw new Error("Missing NEXT_PUBLIC_API_URL");
  }
  return url;
}

export async function POST(request: NextRequest) {
  try {
    const API_URL = getApiUrl();
    const session = await auth();
    
    if (!session?.user?.id) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    // Get subscription and usage data
    const [subscriptionPlan, usage] = await Promise.all([
      getUserSubscriptionPlan(session.user.id),
      getCurrentUsage(session.user.id),
    ]);

    // Gate uploads by available minutes (subscription minutes OR top-ups).
    // If user has 0 minutes total, treat as payment required.
    if (usage.totalAvailableMinutes <= 0) {
      return NextResponse.json(
        {
          error: "payment_required",
          message: "You need minutes to process videos. Please buy minutes or subscribe.",
          details: {
            totalAvailableMinutes: usage.totalAvailableMinutes,
            minutesUsed: usage.minutesUsed,
            minutesLimit: usage.minutesLimit,
            topUpMinutesRemaining: usage.topUpMinutesRemaining,
          },
        },
        { status: 402 },
      );
    }

    // Check if user has remaining quota
    const remainingMinutes = usage.totalAvailableMinutes - usage.minutesUsed;
    if (remainingMinutes <= 0) {
      return NextResponse.json(
        {
          error: "quota_exceeded",
          message: `You've used all ${usage.minutesLimit} minutes for this billing period. Purchase a top-up or wait for your quota to reset.`,
          details: {
            minutesUsed: usage.minutesUsed,
            minutesLimit: usage.minutesLimit,
            topUpMinutesRemaining: usage.topUpMinutesRemaining,
            remainingMinutes: 0,
          },
        },
        { status: 402 },
      );
    }

    // Determine plan tier
    const subscriptionTier = subscriptionPlan.title?.toLowerCase() || "none";
    const planTier = subscriptionPlan.isPaid ? subscriptionTier : "topup";
    const isPriority = subscriptionPlan.isPaid && subscriptionTier === "studio";

    // Get the form data from the request
    const formData = await request.formData();

    // Create a JWT token with subscription info to pass to backend
    // This allows the backend to also validate and use subscription info
    const subscriptionToken = sign(
      {
        sub: session.user.id,
        email: session.user.email,
        name: session.user.name,
        plan_tier: planTier,
        minutes_limit: usage.minutesLimit,
        minutes_used: usage.minutesUsed,
        minutes_remaining: remainingMinutes,
        // "is_paid" is used by the backend gate; treat "has minutes" as paid access.
        // (true for subscription minutes or top-ups)
        is_paid: remainingMinutes > 0,
      },
      JWT_SECRET,
      { expiresIn: "1h" }
    );
    
    // Forward to backend with auth token
    const backendResponse = await fetch(`${API_URL}/api/videos/upload`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${subscriptionToken}`,
      },
      body: formData,
    });

    if (!backendResponse.ok) {
      const errorText = await backendResponse.text();
      console.error("Backend upload error:", errorText);
      
      // Try to parse backend error for better messages
      try {
        const errorData = JSON.parse(errorText);
        if (errorData.detail?.error === "quota_exceeded" || errorData.detail?.error === "payment_required") {
          return NextResponse.json(errorData.detail, { status: 402 });
        }
      } catch {
        // Not JSON, use generic error
      }
      
      return NextResponse.json(
        { error: "Upload failed", message: errorText },
        { status: backendResponse.status }
      );
    }

    const backendData = await backendResponse.json();

    // Create local database record
    const title = formData.get("title") as string || 
                  (formData.get("file") as File)?.name?.replace(/\.[^/.]+$/, "") || 
                  "Untitled Video";

    const job = await prisma.videoJob.create({
      data: {
        userId: session.user.id,
        title,
        sourceVideoUrl: backendData.video_id,
        backendJobId: backendData.job_id,
        status: "PENDING",
        progress: 0,
      },
    });

    console.log(`✅ Job created: ${job.id} (backend: ${backendData.job_id}, plan: ${planTier}, priority: ${isPriority})`);

    return NextResponse.json({
      job_id: job.id,
      backend_job_id: backendData.job_id,
      video_id: backendData.video_id,
      status: "pending",
      message: backendData.message,
      quota: {
        minutesUsed: usage.minutesUsed,
        minutesRemaining: remainingMinutes,
        planTier,
        isPriority,
      },
    });
  } catch (error) {
    console.error("Upload error:", error);
    return NextResponse.json(
      { error: "Failed to upload video" },
      { status: 500 }
    );
  }
}

// Configure body size limit for video uploads
export const config = {
  api: {
    bodyParser: false,
  },
};

