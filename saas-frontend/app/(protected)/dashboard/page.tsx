import Link from "next/link";
import { redirect } from "next/navigation";
import { Play, Plus, ArrowRight, Clock, CheckCircle, Loader2 } from "lucide-react";

import { getCurrentUser } from "@/lib/session";
import { constructMetadata } from "@/lib/utils";
import { prisma } from "@/lib/db";
import { Button } from "@/components/ui/button";
import { DashboardHeader } from "@/components/dashboard/header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";

export const metadata = constructMetadata({
  title: "Dashboard – Video Recap AI",
  description: "Create recap-ready edits faster for anime and movies.",
});

export default async function DashboardPage() {
  const user = await getCurrentUser();

  if (!user?.id) {
    redirect("/login");
  }

  // Fetch recent jobs and stats
  const [recentJobs, stats] = await Promise.all([
    prisma.videoJob.findMany({
      where: { userId: user.id },
      orderBy: { createdAt: "desc" },
      take: 5,
    }),
    prisma.videoJob.groupBy({
      by: ["status"],
      where: { userId: user.id },
      _count: true,
    }),
  ]);

  const statsMap = Object.fromEntries(
    stats.map((s) => [s.status, s._count])
  );

  const totalJobs = stats.reduce((acc, s) => acc + s._count, 0);
  const processingJobs = statsMap["PROCESSING"] || 0;
  const completedJobs = statsMap["COMPLETED"] || 0;

  return (
    <>
      <DashboardHeader
        heading="Dashboard"
        text={`Welcome back, ${user.name || "Creator"}! Ready to create something amazing?`}
      >
        <Button asChild>
          <Link href="/dashboard/jobs/new">
            <Plus className="h-4 w-4 mr-2" />
            New Video
          </Link>
        </Button>
      </DashboardHeader>

      <div className="space-y-6">
        {/* Stats Cards */}
        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Videos</CardTitle>
              <Play className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{totalJobs}</div>
              <p className="text-xs text-muted-foreground">
                All time processed videos
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Processing</CardTitle>
              <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-blue-600">{processingJobs}</div>
              <p className="text-xs text-muted-foreground">
                Currently in progress
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Completed</CardTitle>
              <CheckCircle className="h-4 w-4 text-green-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-green-600">{completedJobs}</div>
              <p className="text-xs text-muted-foreground">
                Ready to download
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Recent Jobs */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle>Recent Videos</CardTitle>
              <CardDescription>Your latest video processing jobs</CardDescription>
            </div>
            <Button variant="ghost" size="sm" asChild>
              <Link href="/dashboard/jobs">
                View All
                <ArrowRight className="h-4 w-4 ml-2" />
              </Link>
            </Button>
          </CardHeader>
          <CardContent>
            {recentJobs.length === 0 ? (
              <div className="text-center py-10">
                <Play className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                <h3 className="text-lg font-semibold mb-2">No videos yet</h3>
                <p className="text-muted-foreground mb-4">
                  Create your first video to get started with AI-powered editing.
                </p>
                <Button asChild>
                  <Link href="/dashboard/jobs/new">
                    <Plus className="h-4 w-4 mr-2" />
                    Create Your First Video
                  </Link>
                </Button>
              </div>
            ) : (
              <div className="space-y-4">
                {recentJobs.map((job) => (
                  <Link
                    key={job.id}
                    href={`/dashboard/jobs/${job.id}`}
                    className="flex items-center justify-between p-4 rounded-lg border hover:bg-muted/50 transition-colors"
                  >
                    <div className="flex items-center gap-4">
                      <div className="p-2 rounded-full bg-primary/10">
                        <Play className="h-4 w-4 text-primary" />
                      </div>
                      <div>
                        <p className="font-medium">{job.title || "Untitled Video"}</p>
                        <p className="text-sm text-muted-foreground">
                          {new Date(job.createdAt).toLocaleDateString()}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-4">
                      {job.status === "PROCESSING" && (
                        <div className="flex items-center gap-2">
                          <Progress value={job.progress} className="w-20 h-2" />
                          <span className="text-xs text-muted-foreground">{job.progress}%</span>
                        </div>
                      )}
                      <Badge
                        variant={
                          job.status === "COMPLETED"
                            ? "default"
                            : job.status === "FAILED"
                            ? "destructive"
                            : "secondary"
                        }
                      >
                        {job.status === "PROCESSING" && (
                          <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                        )}
                        {job.status === "COMPLETED" && (
                          <CheckCircle className="h-3 w-3 mr-1" />
                        )}
                        {job.status === "PENDING" && (
                          <Clock className="h-3 w-3 mr-1" />
                        )}
                        {job.status.charAt(0) + job.status.slice(1).toLowerCase()}
                      </Badge>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Quick Actions */}
        <div className="grid gap-4 md:grid-cols-2">
          <Card className="bg-gradient-to-br from-primary/10 to-primary/5">
            <CardHeader>
              <CardTitle>Create New Video</CardTitle>
              <CardDescription>
                Upload footage and let AI transform it into a compelling narrative.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button asChild>
                <Link href="/dashboard/jobs/new">
                  <Plus className="h-4 w-4 mr-2" />
                  Start Creating
                </Link>
              </Button>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Manage Subscription</CardTitle>
              <CardDescription>
                View your usage, upgrade your plan, or manage billing.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" asChild>
                <Link href="/dashboard/billing">
                  View Billing
                  <ArrowRight className="h-4 w-4 ml-2" />
                </Link>
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
