"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { 
  ArrowLeft,
  Play, 
  Pause, 
  CheckCircle, 
  XCircle, 
  Clock, 
  Loader2,
  Download,
  RefreshCw,
  Trash2,
  RotateCcw,
  ExternalLink
} from "lucide-react";

import { DashboardHeader } from "@/components/dashboard/header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";

// Types
interface VideoJob {
  id: string;
  title: string | null;
  status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED" | "CANCELLED";
  progress: number;
  currentStep: string | null;
  errorMessage: string | null;
  sourceVideoUrl: string | null;
  outputVideoUrl: string | null;
  durationSeconds: number | null;
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
}

// Status badge component
function StatusBadge({ status }: { status: VideoJob["status"] }) {
  const config = {
    PENDING: { icon: Clock, label: "Pending", variant: "secondary" as const, color: "text-gray-500" },
    PROCESSING: { icon: Loader2, label: "Processing", variant: "default" as const, color: "text-blue-500" },
    COMPLETED: { icon: CheckCircle, label: "Completed", variant: "default" as const, color: "text-green-500" },
    FAILED: { icon: XCircle, label: "Failed", variant: "destructive" as const, color: "text-red-500" },
    CANCELLED: { icon: Pause, label: "Cancelled", variant: "secondary" as const, color: "text-orange-500" },
  };

  const { icon: Icon, label, variant, color } = config[status];
  const isAnimated = status === "PROCESSING";

  return (
    <Badge variant={variant} className={`gap-1 text-base px-3 py-1 ${color}`}>
      <Icon className={`h-4 w-4 ${isAnimated ? "animate-spin" : ""}`} />
      {label}
    </Badge>
  );
}

// Progress timeline component
function ProcessingTimeline({ currentStep, progress }: { currentStep: string | null; progress: number }) {
  const steps = [
    { name: "Queued", threshold: 0 },
    { name: "Analyzing", threshold: 10 },
    { name: "Generating Script", threshold: 25 },
    { name: "Voice Generation", threshold: 40 },
    { name: "Scene Matching", threshold: 55 },
    { name: "Video Processing", threshold: 70 },
    { name: "Final Assembly", threshold: 90 },
    { name: "Complete", threshold: 100 },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{currentStep || "Waiting..."}</span>
        <span className="text-muted-foreground">{progress}%</span>
      </div>
      <Progress value={progress} className="h-3" />
      <div className="flex justify-between text-xs text-muted-foreground">
        {steps.map((step, i) => (
          <div
            key={step.name}
            className={`flex flex-col items-center ${
              progress >= step.threshold ? "text-primary" : ""
            }`}
          >
            <div
              className={`w-2 h-2 rounded-full mb-1 ${
                progress >= step.threshold ? "bg-primary" : "bg-muted"
              }`}
            />
            <span className="hidden md:block">{step.name}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Loading skeleton
function JobDetailSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-8 w-48" />
      <div className="grid gap-6 md:grid-cols-2">
        <Skeleton className="h-48" />
        <Skeleton className="h-48" />
      </div>
    </div>
  );
}

// Main page component
export default function JobDetailPage() {
  const params = useParams();
  const router = useRouter();
  const jobId = params.id as string;

  const [job, setJob] = useState<VideoJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchJob = async () => {
    try {
      const response = await fetch(`/api/jobs/${jobId}`);
      if (response.ok) {
        const data = await response.json();
        setJob(data);
      } else if (response.status === 404) {
        toast.error("Job not found");
        router.push("/dashboard/jobs");
      }
    } catch (error) {
      console.error("Failed to fetch job:", error);
      toast.error("Failed to load job details");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchJob();

    // Auto-refresh for processing jobs
    const interval = setInterval(() => {
      if (job?.status === "PROCESSING" || job?.status === "PENDING") {
        fetchJob();
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [jobId, job?.status]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchJob();
  };

  const handleCancel = async () => {
    try {
      const response = await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" });
      if (response.ok) {
        toast.success("Job cancelled");
        fetchJob();
      } else {
        toast.error("Failed to cancel job");
      }
    } catch (error) {
      toast.error("Failed to cancel job");
    }
  };

  const handleRetry = async () => {
    try {
      const response = await fetch(`/api/jobs/${jobId}/retry`, { method: "POST" });
      if (response.ok) {
        const data = await response.json();
        toast.success("Job queued for retry");
        router.push(`/dashboard/jobs/${data.new_job_id}`);
      } else {
        toast.error("Failed to retry job");
      }
    } catch (error) {
      toast.error("Failed to retry job");
    }
  };

  const handleDelete = async () => {
    try {
      const response = await fetch(`/api/jobs/${jobId}`, { method: "DELETE" });
      if (response.ok) {
        toast.success("Job deleted");
        router.push("/dashboard/jobs");
      } else {
        toast.error("Failed to delete job");
      }
    } catch (error) {
      toast.error("Failed to delete job");
    }
  };

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return "-";
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return "-";
    return new Date(dateStr).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  if (loading) {
    return (
      <>
        <DashboardHeader heading="Job Details" text="Loading..." />
        <JobDetailSkeleton />
      </>
    );
  }

  if (!job) {
    return (
      <>
        <DashboardHeader heading="Job Not Found" text="The requested job could not be found." />
        <Button onClick={() => router.push("/dashboard/jobs")}>
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Jobs
        </Button>
      </>
    );
  }

  return (
    <>
      <DashboardHeader
        heading={job.title || "Untitled Video"}
        text={`Job ID: ${job.id}`}
      >
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing}>
            <RefreshCw className={`h-4 w-4 mr-2 ${refreshing ? "animate-spin" : ""}`} />
            Refresh
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link href="/dashboard/jobs">
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back
            </Link>
          </Button>
        </div>
      </DashboardHeader>

      <div className="space-y-6">
        {/* Status Card */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle>Status</CardTitle>
              <CardDescription>Current processing status</CardDescription>
            </div>
            <StatusBadge status={job.status} />
          </CardHeader>
          <CardContent>
            {(job.status === "PROCESSING" || job.status === "PENDING") && (
              <ProcessingTimeline currentStep={job.currentStep} progress={job.progress} />
            )}
            {job.status === "COMPLETED" && (
              <div className="flex items-center gap-4 p-4 bg-green-50 dark:bg-green-950 rounded-lg">
                <CheckCircle className="h-8 w-8 text-green-500" />
                <div>
                  <p className="font-medium text-green-700 dark:text-green-300">
                    Processing Complete!
                  </p>
                  <p className="text-sm text-green-600 dark:text-green-400">
                    Your video is ready to download.
                  </p>
                </div>
              </div>
            )}
            {job.status === "FAILED" && (
              <div className="p-4 bg-red-50 dark:bg-red-950 rounded-lg">
                <div className="flex items-center gap-4 mb-2">
                  <XCircle className="h-8 w-8 text-red-500" />
                  <div>
                    <p className="font-medium text-red-700 dark:text-red-300">
                      Processing Failed
                    </p>
                    <p className="text-sm text-red-600 dark:text-red-400">
                      {job.errorMessage || "An unknown error occurred"}
                    </p>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <div className="grid gap-6 md:grid-cols-2">
          {/* Details Card */}
          <Card>
            <CardHeader>
              <CardTitle>Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Created</span>
                <span>{formatDate(job.createdAt)}</span>
              </div>
              <Separator />
              <div className="flex justify-between">
                <span className="text-muted-foreground">Last Updated</span>
                <span>{formatDate(job.updatedAt)}</span>
              </div>
              <Separator />
              <div className="flex justify-between">
                <span className="text-muted-foreground">Completed</span>
                <span>{formatDate(job.completedAt)}</span>
              </div>
              <Separator />
              <div className="flex justify-between">
                <span className="text-muted-foreground">Duration</span>
                <span>{formatDuration(job.durationSeconds)}</span>
              </div>
            </CardContent>
          </Card>

          {/* Actions Card */}
          <Card>
            <CardHeader>
              <CardTitle>Actions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {job.outputVideoUrl && (
                <Button className="w-full" size="lg" asChild>
                  <a href={`/api/jobs/${job.id}/download`} target="_blank" rel="noopener noreferrer">
                    <Download className="h-4 w-4 mr-2" />
                    Download Video
                  </a>
                </Button>
              )}

              {job.status === "FAILED" && (
                <Button variant="outline" className="w-full" onClick={handleRetry}>
                  <RotateCcw className="h-4 w-4 mr-2" />
                  Retry Job
                </Button>
              )}

              {(job.status === "PENDING" || job.status === "PROCESSING") && (
                <Button variant="outline" className="w-full text-orange-600" onClick={handleCancel}>
                  <Pause className="h-4 w-4 mr-2" />
                  Cancel Job
                </Button>
              )}

              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button variant="outline" className="w-full text-red-600">
                    <Trash2 className="h-4 w-4 mr-2" />
                    Delete Job
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Delete Job?</AlertDialogTitle>
                    <AlertDialogDescription>
                      This action cannot be undone. This will permanently delete the job
                      and all associated files.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction onClick={handleDelete} className="bg-red-600">
                      Delete
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </CardContent>
          </Card>
        </div>

        {/* Video Preview (if completed) */}
        {job.status === "COMPLETED" && job.outputVideoUrl && (
          <Card>
            <CardHeader>
              <CardTitle>Video Preview</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="aspect-video bg-black rounded-lg overflow-hidden">
                <video
                  src={`/api/jobs/${job.id}/download`}
                  controls
                  className="w-full h-full"
                  poster="/_static/illustrations/rocket-crashed.svg"
                />
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </>
  );
}

