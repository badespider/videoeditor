import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/session";
import { constructMetadata } from "@/lib/utils";
import { prisma } from "@/lib/db";
import { getUsageHistory, getCurrentUsage } from "@/lib/api/usage-service";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DashboardHeader } from "@/components/dashboard/header";
import { Progress } from "@/components/ui/progress";
import { Play, Clock, CheckCircle, TrendingUp } from "lucide-react";

export const metadata = constructMetadata({
  title: "Analytics – Video Recap AI",
  description: "View your video processing analytics and usage trends.",
});

export default async function ChartsPage() {
  const user = await getCurrentUser();

  if (!user?.id) {
    redirect("/login");
  }

  // Fetch real analytics data
  const [usageHistory, currentUsage, jobStats] = await Promise.all([
    getUsageHistory(user.id, 6),
    getCurrentUsage(user.id),
    prisma.videoJob.groupBy({
      by: ["status"],
      where: { userId: user.id },
      _count: true,
    }),
  ]);

  const statsMap = Object.fromEntries(
    jobStats.map((s) => [s.status, s._count])
  );

  const totalJobs = jobStats.reduce((acc, s) => acc + s._count, 0);
  const completedJobs = statsMap["COMPLETED"] || 0;
  const processingJobs = statsMap["PROCESSING"] || 0;
  const failedJobs = statsMap["FAILED"] || 0;

  // Calculate max usage for chart scaling
  const maxUsage = Math.max(...usageHistory.map((h) => h.minutesUsed), currentUsage.minutesLimit);

  return (
    <>
      <DashboardHeader 
        heading="Analytics" 
        text="Track your video processing usage and performance." 
      />
      
      <div className="flex flex-col gap-6">
        {/* Summary Stats */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Videos</CardTitle>
              <Play className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{totalJobs}</div>
              <p className="text-xs text-muted-foreground">All time processed</p>
            </CardContent>
          </Card>
          
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Success Rate</CardTitle>
              <CheckCircle className="h-4 w-4 text-green-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-green-600">
                {totalJobs > 0 ? Math.round((completedJobs / totalJobs) * 100) : 0}%
              </div>
              <p className="text-xs text-muted-foreground">
                {completedJobs} completed, {failedJobs} failed
              </p>
            </CardContent>
          </Card>
          
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Minutes Used</CardTitle>
              <Clock className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{currentUsage.minutesUsed.toFixed(1)}</div>
              <p className="text-xs text-muted-foreground">
                of {currentUsage.totalAvailableMinutes} available
              </p>
            </CardContent>
          </Card>
          
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Quota Used</CardTitle>
              <TrendingUp className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{currentUsage.percentUsed}%</div>
              <Progress value={currentUsage.percentUsed} className="mt-2 h-2" />
            </CardContent>
          </Card>
        </div>

        {/* Usage History Chart */}
        <Card>
          <CardHeader>
            <CardTitle>Usage History</CardTitle>
            <CardDescription>
              Your video processing minutes over the last 6 months
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {usageHistory.map((month) => {
                const percentage = maxUsage > 0 ? (month.minutesUsed / maxUsage) * 100 : 0;
                const monthName = new Date(month.period + "-01").toLocaleDateString("en-US", {
                  month: "short",
                  year: "numeric",
                });
                
                return (
                  <div key={month.period} className="space-y-1">
                    <div className="flex items-center justify-between text-sm">
                      <span className="font-medium">{monthName}</span>
                      <span className="text-muted-foreground">
                        {month.minutesUsed.toFixed(1)} min
                      </span>
                    </div>
                    <div className="h-3 w-full bg-muted rounded-full overflow-hidden">
                      <div
                        className="h-full bg-primary transition-all duration-500"
                        style={{ width: `${Math.max(percentage, 2)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>

        {/* Job Status Breakdown */}
        <Card>
          <CardHeader>
            <CardTitle>Job Status Breakdown</CardTitle>
            <CardDescription>
              Distribution of your video processing jobs by status
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="text-center p-4 rounded-lg bg-yellow-50 dark:bg-yellow-950">
                <div className="text-2xl font-bold text-yellow-600">{statsMap["PENDING"] || 0}</div>
                <div className="text-sm text-muted-foreground">Pending</div>
              </div>
              <div className="text-center p-4 rounded-lg bg-blue-50 dark:bg-blue-950">
                <div className="text-2xl font-bold text-blue-600">{processingJobs}</div>
                <div className="text-sm text-muted-foreground">Processing</div>
              </div>
              <div className="text-center p-4 rounded-lg bg-green-50 dark:bg-green-950">
                <div className="text-2xl font-bold text-green-600">{completedJobs}</div>
                <div className="text-sm text-muted-foreground">Completed</div>
              </div>
              <div className="text-center p-4 rounded-lg bg-red-50 dark:bg-red-950">
                <div className="text-2xl font-bold text-red-600">{failedJobs}</div>
                <div className="text-sm text-muted-foreground">Failed</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
