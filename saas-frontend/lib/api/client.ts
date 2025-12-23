/**
 * API Client for Video Editor Backend
 * 
 * This module provides a type-safe interface to communicate with the 
 * FastAPI video processing backend.
 */

import { env } from "@/env.mjs";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === "production" ? "" : "http://localhost:8000");

// Types
export interface BackendJob {
  id: string;
  status: "pending" | "processing" | "completed" | "failed" | "cancelled";
  progress: number;
  current_step?: string;
  error_message?: string;
  created_at: string;
  updated_at: string;
  completed_at?: string;
  output_url?: string;
  duration_seconds?: number;
}

export interface CreateJobRequest {
  video_url?: string;
  user_id: string;
  config?: {
    enable_copyright_protection?: boolean;
    enable_vector_matching?: boolean;
    voice_id?: string;
  };
}

export interface CreateJobResponse {
  job_id: string;
  status: string;
}

export interface UploadResponse {
  url: string;
  key: string;
}

export interface ApiError {
  detail: string;
  status_code: number;
}

// API Client class
class VideoEditorApiClient {
  private baseUrl: string;
  private authToken?: string;

  constructor(baseUrl: string = API_BASE_URL) {
    if (process.env.NODE_ENV === "production" && !baseUrl) {
      // Fail fast in production if the backend URL isn't configured.
      throw new Error("Missing NEXT_PUBLIC_API_URL in production");
    }
    this.baseUrl = baseUrl;
  }

  /**
   * Set the authentication token for API requests
   */
  setAuthToken(token: string) {
    this.authToken = token;
  }

  /**
   * Make an authenticated request to the backend
   */
  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    
    const headers: HeadersInit = {
      "Content-Type": "application/json",
      ...options.headers,
    };

    if (this.authToken) {
      (headers as Record<string, string>)["Authorization"] = `Bearer ${this.authToken}`;
    }

    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({
        detail: "Unknown error occurred",
      }));
      throw new ApiClientError(
        error.detail || "Request failed",
        response.status
      );
    }

    return response.json();
  }

  // ============ Job Operations ============

  /**
   * Create a new video processing job
   */
  async createJob(data: CreateJobRequest): Promise<CreateJobResponse> {
    return this.request<CreateJobResponse>("/api/jobs", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  /**
   * Get job status and details
   */
  async getJob(jobId: string): Promise<BackendJob> {
    return this.request<BackendJob>(`/api/jobs/${jobId}`);
  }

  /**
   * List all jobs for the authenticated user
   */
  async listJobs(params?: {
    status?: string;
    limit?: number;
    offset?: number;
  }): Promise<{ jobs: BackendJob[]; total: number }> {
    const searchParams = new URLSearchParams();
    if (params?.status) searchParams.set("status", params.status);
    if (params?.limit) searchParams.set("limit", params.limit.toString());
    if (params?.offset) searchParams.set("offset", params.offset.toString());

    const query = searchParams.toString();
    return this.request<{ jobs: BackendJob[]; total: number }>(
      `/api/jobs${query ? `?${query}` : ""}`
    );
  }

  /**
   * Cancel a running job
   */
  async cancelJob(jobId: string): Promise<{ success: boolean }> {
    return this.request<{ success: boolean }>(`/api/jobs/${jobId}/cancel`, {
      method: "POST",
    });
  }

  /**
   * Delete a job and its associated files
   */
  async deleteJob(jobId: string): Promise<{ success: boolean }> {
    return this.request<{ success: boolean }>(`/api/jobs/${jobId}`, {
      method: "DELETE",
    });
  }

  /**
   * Retry a failed job
   */
  async retryJob(jobId: string): Promise<CreateJobResponse> {
    return this.request<CreateJobResponse>(`/api/jobs/${jobId}/retry`, {
      method: "POST",
    });
  }

  // ============ Upload Operations ============

  /**
   * Get a presigned URL for uploading a video
   */
  async getUploadUrl(filename: string, contentType: string): Promise<UploadResponse> {
    return this.request<UploadResponse>("/api/upload/presign", {
      method: "POST",
      body: JSON.stringify({ filename, content_type: contentType }),
    });
  }

  /**
   * Upload a file directly to the backend
   */
  async uploadFile(file: File, onProgress?: (progress: number) => void): Promise<UploadResponse> {
    const formData = new FormData();
    formData.append("file", file);

    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      
      xhr.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable && onProgress) {
          const progress = Math.round((event.loaded / event.total) * 100);
          onProgress(progress);
        }
      });

      xhr.addEventListener("load", () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText));
        } else {
          reject(new ApiClientError("Upload failed", xhr.status));
        }
      });

      xhr.addEventListener("error", () => {
        reject(new ApiClientError("Upload failed", 0));
      });

      xhr.open("POST", `${this.baseUrl}/api/upload`);
      if (this.authToken) {
        xhr.setRequestHeader("Authorization", `Bearer ${this.authToken}`);
      }
      xhr.send(formData);
    });
  }

  // ============ Preview Operations ============

  /**
   * Get a preview of the generated script
   */
  async getScriptPreview(jobId: string): Promise<{ script: string; scenes: any[] }> {
    return this.request<{ script: string; scenes: any[] }>(`/api/preview/${jobId}/script`);
  }

  /**
   * Get video preview frames
   */
  async getPreviewFrames(jobId: string): Promise<{ frames: string[] }> {
    return this.request<{ frames: string[] }>(`/api/preview/${jobId}/frames`);
  }

  // ============ Health Check ============

  /**
   * Check if the backend is healthy
   */
  async healthCheck(): Promise<{ status: string; version: string }> {
    return this.request<{ status: string; version: string }>("/health");
  }
}

// Custom error class for API errors
export class ApiClientError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
  }
}

// Export singleton instance
export const apiClient = new VideoEditorApiClient();

// Export class for custom instances
export { VideoEditorApiClient };

