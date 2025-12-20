/**
 * Job Service
 * 
 * Handles video job operations, syncing between the local database
 * and the backend API.
 */

import { prisma } from "@/lib/db";
import { apiClient, BackendJob, CreateJobRequest } from "./client";
import { JobStatus, VideoJob } from "@prisma/client";

// Map backend status to Prisma enum
function mapBackendStatus(status: BackendJob["status"]): JobStatus {
  const statusMap: Record<BackendJob["status"], JobStatus> = {
    pending: "PENDING",
    processing: "PROCESSING",
    completed: "COMPLETED",
    failed: "FAILED",
    cancelled: "CANCELLED",
  };
  return statusMap[status];
}

// Map Prisma status to backend status
function mapPrismaStatus(status: JobStatus): BackendJob["status"] {
  const statusMap: Record<JobStatus, BackendJob["status"]> = {
    PENDING: "pending",
    PROCESSING: "processing",
    COMPLETED: "completed",
    FAILED: "failed",
    CANCELLED: "cancelled",
  };
  return statusMap[status];
}

export interface CreateVideoJobInput {
  userId: string;
  title?: string;
  sourceVideoUrl?: string;
  config?: {
    enableCopyrightProtection?: boolean;
    enableVectorMatching?: boolean;
    voiceId?: string;
  };
}

export interface JobWithDetails extends VideoJob {
  backendData?: BackendJob;
}

/**
 * Create a new video processing job
 */
export async function createVideoJob(input: CreateVideoJobInput): Promise<VideoJob> {
  const { userId, title, sourceVideoUrl, config } = input;

  // First, create the job in the backend
  const backendResponse = await apiClient.createJob({
    video_url: sourceVideoUrl,
    user_id: userId,
    config: config ? {
      enable_copyright_protection: config.enableCopyrightProtection,
      enable_vector_matching: config.enableVectorMatching,
      voice_id: config.voiceId,
    } : undefined,
  });

  // Then, create the local database record
  const job = await prisma.videoJob.create({
    data: {
      userId,
      title: title || "Untitled Video",
      sourceVideoUrl,
      backendJobId: backendResponse.job_id,
      status: "PENDING",
      progress: 0,
    },
  });

  return job;
}

/**
 * Get a job by ID with synced backend status
 */
export async function getVideoJob(jobId: string, syncWithBackend = true): Promise<JobWithDetails | null> {
  const job = await prisma.videoJob.findUnique({
    where: { id: jobId },
  });

  if (!job) return null;

  // Optionally sync with backend for latest status
  if (syncWithBackend && job.backendJobId) {
    try {
      const backendJob = await apiClient.getJob(job.backendJobId);
      
      // Update local record if status changed
      if (mapBackendStatus(backendJob.status) !== job.status) {
        const updatedJob = await prisma.videoJob.update({
          where: { id: jobId },
          data: {
            status: mapBackendStatus(backendJob.status),
            progress: backendJob.progress,
            currentStep: backendJob.current_step,
            errorMessage: backendJob.error_message,
            outputVideoUrl: backendJob.output_url,
            durationSeconds: backendJob.duration_seconds,
            completedAt: backendJob.completed_at ? new Date(backendJob.completed_at) : null,
          },
        });
        return { ...updatedJob, backendData: backendJob };
      }

      return { ...job, backendData: backendJob };
    } catch (error) {
      // If backend is unreachable, return local data
      console.error("Failed to sync with backend:", error);
      return job;
    }
  }

  return job;
}

/**
 * List jobs for a user
 */
export async function listUserJobs(
  userId: string,
  options?: {
    status?: JobStatus;
    limit?: number;
    offset?: number;
    orderBy?: "createdAt" | "updatedAt";
    orderDir?: "asc" | "desc";
  }
): Promise<{ jobs: VideoJob[]; total: number }> {
  const { status, limit = 10, offset = 0, orderBy = "createdAt", orderDir = "desc" } = options || {};

  const where = {
    userId,
    ...(status && { status }),
  };

  const [jobs, total] = await Promise.all([
    prisma.videoJob.findMany({
      where,
      take: limit,
      skip: offset,
      orderBy: { [orderBy]: orderDir },
    }),
    prisma.videoJob.count({ where }),
  ]);

  return { jobs, total };
}

/**
 * Cancel a job
 */
export async function cancelVideoJob(jobId: string, userId: string): Promise<VideoJob> {
  const job = await prisma.videoJob.findFirst({
    where: { id: jobId, userId },
  });

  if (!job) {
    throw new Error("Job not found");
  }

  if (job.status === "COMPLETED" || job.status === "CANCELLED") {
    throw new Error("Cannot cancel a completed or already cancelled job");
  }

  // Cancel in backend
  if (job.backendJobId) {
    await apiClient.cancelJob(job.backendJobId);
  }

  // Update local record
  return prisma.videoJob.update({
    where: { id: jobId },
    data: { status: "CANCELLED" },
  });
}

/**
 * Delete a job
 */
export async function deleteVideoJob(jobId: string, userId: string): Promise<void> {
  const job = await prisma.videoJob.findFirst({
    where: { id: jobId, userId },
  });

  if (!job) {
    throw new Error("Job not found");
  }

  // Delete from backend
  if (job.backendJobId) {
    try {
      await apiClient.deleteJob(job.backendJobId);
    } catch (error) {
      console.error("Failed to delete from backend:", error);
    }
  }

  // Delete local record
  await prisma.videoJob.delete({
    where: { id: jobId },
  });
}

/**
 * Retry a failed job
 */
export async function retryVideoJob(jobId: string, userId: string): Promise<VideoJob> {
  const job = await prisma.videoJob.findFirst({
    where: { id: jobId, userId },
  });

  if (!job) {
    throw new Error("Job not found");
  }

  if (job.status !== "FAILED") {
    throw new Error("Can only retry failed jobs");
  }

  // Retry in backend
  if (job.backendJobId) {
    const response = await apiClient.retryJob(job.backendJobId);
    
    // Update local record
    return prisma.videoJob.update({
      where: { id: jobId },
      data: {
        status: "PENDING",
        progress: 0,
        errorMessage: null,
        currentStep: null,
        backendJobId: response.job_id,
      },
    });
  }

  throw new Error("No backend job to retry");
}

/**
 * Sync job status from backend webhook
 */
export async function syncJobFromWebhook(backendJobId: string, data: Partial<BackendJob>): Promise<VideoJob | null> {
  const job = await prisma.videoJob.findFirst({
    where: { backendJobId },
  });

  if (!job) return null;

  return prisma.videoJob.update({
    where: { id: job.id },
    data: {
      ...(data.status && { status: mapBackendStatus(data.status) }),
      ...(data.progress !== undefined && { progress: data.progress }),
      ...(data.current_step && { currentStep: data.current_step }),
      ...(data.error_message && { errorMessage: data.error_message }),
      ...(data.output_url && { outputVideoUrl: data.output_url }),
      ...(data.duration_seconds && { durationSeconds: data.duration_seconds }),
      ...(data.completed_at && { completedAt: new Date(data.completed_at) }),
    },
  });
}

/**
 * Get job statistics for a user
 */
export async function getUserJobStats(userId: string): Promise<{
  total: number;
  pending: number;
  processing: number;
  completed: number;
  failed: number;
}> {
  const [total, pending, processing, completed, failed] = await Promise.all([
    prisma.videoJob.count({ where: { userId } }),
    prisma.videoJob.count({ where: { userId, status: "PENDING" } }),
    prisma.videoJob.count({ where: { userId, status: "PROCESSING" } }),
    prisma.videoJob.count({ where: { userId, status: "COMPLETED" } }),
    prisma.videoJob.count({ where: { userId, status: "FAILED" } }),
  ]);

  return { total, pending, processing, completed, failed };
}

