"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { 
  Play, 
  Pause, 
  CheckCircle, 
  XCircle, 
  Clock, 
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
  Eye,
  Download
} from "lucide-react";

import { DashboardHeader } from "@/components/dashboard/header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toast } from "sonner";

// Types
interface VideoJob {
  id: string;
  title: string | null;
  status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED" | "CANCELLED";
  progress: number;
  currentStep: string | null;
  outputVideoUrl: string | null;
  durationSeconds: number | null;
  createdAt: string;
  updatedAt: string;
}

// Status badge component
function StatusBadge({ status }: { status: VideoJob["status"] }) {
  const config = {
    PENDING: { icon: Clock, label: "Pending", variant: "secondary" as const },
    PROCESSING: { icon: Loader2, label: "Processing", variant: "default" as const },
    COMPLETED: { icon: CheckCircle, label: "Completed", variant: "default" as const },
    FAILED: { icon: XCircle, label: "Failed", variant: "destructive" as const },
    CANCELLED: { icon: Pause, label: "Cancelled", variant: "secondary" as const },
  };

  const { icon: Icon, label, variant } = config[status];
  const isAnimated = status === "PROCESSING";

  return (
    <Badge variant={variant} className="gap-1">
      <Icon className={`h-3 w-3 ${isAnimated ? "animate-spin" : ""}`} />
      {label}
    </Badge>
  );
}

// Job row component
function JobRow({ job, onRefresh }: { job: VideoJob; onRefresh: () => void }) {
  const router = useRouter();

  const handleCancel = async () => {
    try {
      const response = await fetch(`/api/jobs/${job.id}/cancel`, { method: "POST" });
      if (response.ok) {
        toast.success("Job cancelled");
        onRefresh();
      } else {
        toast.error("Failed to cancel job");
      }
    } catch (error) {
      toast.error("Failed to cancel job");
    }
  };

  const handleDelete = async () => {
    try {
      const response = await fetch(`/api/jobs/${job.id}`, { method: "DELETE" });
      if (response.ok) {
        toast.success("Job deleted");
        onRefresh();
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

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <TableRow>
      <TableCell className="font-medium">
        <Link 
          href={`/dashboard/jobs/${job.id}`}
          className="hover:underline"
        >
          {job.title || "Untitled Video"}
        </Link>
      </TableCell>
      <TableCell>
        <StatusBadge status={job.status} />
      </TableCell>
      <TableCell>
        {job.status === "PROCESSING" ? (
          <div className="flex items-center gap-2 min-w-[120px]">
            <Progress value={job.progress} className="h-2 w-20" />
            <span className="text-xs text-muted-foreground">{job.progress}%</span>
          </div>
        ) : job.status === "COMPLETED" ? (
          <span className="text-green-600 dark:text-green-400">100%</span>
        ) : (
          <span className="text-muted-foreground">-</span>
        )}
      </TableCell>
      <TableCell className="text-muted-foreground text-sm">
        {job.currentStep || "-"}
      </TableCell>
      <TableCell>{formatDuration(job.durationSeconds)}</TableCell>
      <TableCell className="text-muted-foreground text-sm">
        {formatDate(job.createdAt)}
      </TableCell>
      <TableCell>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm">
              •••
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => router.push(`/dashboard/jobs/${job.id}`)}>
              <Eye className="mr-2 h-4 w-4" />
              View Details
            </DropdownMenuItem>
            {job.outputVideoUrl && (
              <DropdownMenuItem asChild>
                <a href={job.outputVideoUrl} target="_blank" rel="noopener noreferrer">
                  <Download className="mr-2 h-4 w-4" />
                  Download
                </a>
              </DropdownMenuItem>
            )}
            {(job.status === "PENDING" || job.status === "PROCESSING") && (
              <DropdownMenuItem onClick={handleCancel} className="text-orange-600">
                <Pause className="mr-2 h-4 w-4" />
                Cancel
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onClick={handleDelete} className="text-red-600">
              <Trash2 className="mr-2 h-4 w-4" />
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </TableCell>
    </TableRow>
  );
}

// Stats cards
function StatsCards({ jobs }: { jobs: VideoJob[] }) {
  const stats = {
    total: jobs.length,
    processing: jobs.filter(j => j.status === "PROCESSING").length,
    completed: jobs.filter(j => j.status === "COMPLETED").length,
    failed: jobs.filter(j => j.status === "FAILED").length,
  };

  return (
    <div className="grid gap-4 md:grid-cols-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Total Jobs</CardTitle>
          <Play className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">{stats.total}</div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Processing</CardTitle>
          <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold text-blue-600">{stats.processing}</div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Completed</CardTitle>
          <CheckCircle className="h-4 w-4 text-green-500" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold text-green-600">{stats.completed}</div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Failed</CardTitle>
          <XCircle className="h-4 w-4 text-red-500" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold text-red-600">{stats.failed}</div>
        </CardContent>
      </Card>
    </div>
  );
}

// Loading skeleton
function JobsTableSkeleton() {
  return (
    <div className="space-y-4">
      {[1, 2, 3].map((i) => (
        <div key={i} className="flex items-center space-x-4">
          <Skeleton className="h-12 w-full" />
        </div>
      ))}
    </div>
  );
}

// Main page component
export default function JobsPage() {
  const [jobs, setJobs] = useState<VideoJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const router = useRouter();

  const fetchJobs = async () => {
    try {
      const response = await fetch("/api/jobs");
      if (response.ok) {
        const data = await response.json();
        setJobs(data.jobs || []);
      }
    } catch (error) {
      console.error("Failed to fetch jobs:", error);
      toast.error("Failed to load jobs");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchJobs();
    
    // Auto-refresh every 10 seconds if there are processing jobs
    const interval = setInterval(() => {
      if (jobs.some(j => j.status === "PROCESSING")) {
        fetchJobs();
      }
    }, 10000);

    return () => clearInterval(interval);
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchJobs();
  };

  return (
    <>
      <DashboardHeader
        heading="Video Jobs"
        text="Create and manage your video processing jobs."
      >
        <div className="flex gap-2">
          <Button 
            variant="outline" 
            size="sm" 
            onClick={handleRefresh}
            disabled={refreshing}
          >
            <RefreshCw className={`h-4 w-4 mr-2 ${refreshing ? "animate-spin" : ""}`} />
            Refresh
          </Button>
          <Button onClick={() => router.push("/dashboard/jobs/new")}>
            <Plus className="h-4 w-4 mr-2" />
            New Job
          </Button>
        </div>
      </DashboardHeader>

      <div className="space-y-6">
        {/* Stats */}
        {!loading && <StatsCards jobs={jobs} />}

        {/* Jobs Table */}
        <Card>
          <CardHeader>
            <CardTitle>Recent Jobs</CardTitle>
            <CardDescription>
              Your video processing jobs and their current status.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <JobsTableSkeleton />
            ) : jobs.length === 0 ? (
              <div className="text-center py-10">
                <Play className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                <h3 className="text-lg font-semibold mb-2">No jobs yet</h3>
                <p className="text-muted-foreground mb-4">
                  Create your first video processing job to get started.
                </p>
                <Button onClick={() => router.push("/dashboard/jobs/new")}>
                  <Plus className="h-4 w-4 mr-2" />
                  Create Job
                </Button>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Title</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Progress</TableHead>
                    <TableHead>Current Step</TableHead>
                    <TableHead>Duration</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead className="w-[50px]"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {jobs.map((job) => (
                    <JobRow key={job.id} job={job} onRefresh={handleRefresh} />
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

