"use client";

import { useState, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useDropzone } from "react-dropzone";
import { 
  Upload, 
  FileVideo, 
  FileText, 
  X, 
  Sparkles, 
  Shield, 
  Loader2,
  Info,
  AlertTriangle,
  Clock
} from "lucide-react";

import { DashboardHeader } from "@/components/dashboard/header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { toast } from "sonner";

// Usage data type
interface UsageData {
  minutesUsed: number;
  minutesLimit: number;
  topUpMinutesRemaining: number;
  totalAvailableMinutes: number;
  percentUsed: number;
  remainingMinutes: number;
  canProcess: boolean;
  hasSubscription: boolean;
  planTier?: string;
}

// File drop zone component
function FileDropZone({
  accept,
  onDrop,
  file,
  onRemove,
  label,
  description,
  icon: Icon,
}: {
  accept: Record<string, string[]>;
  onDrop: (files: File[]) => void;
  file: File | null;
  onRemove: () => void;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept,
    maxFiles: 1,
  });

  if (file) {
    return (
      <div className="border rounded-lg p-4 bg-muted/50">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Icon className="h-8 w-8 text-primary" />
            <div>
              <p className="font-medium">{file.name}</p>
              <p className="text-sm text-muted-foreground">
                {(file.size / (1024 * 1024)).toFixed(2)} MB
              </p>
            </div>
          </div>
          <Button variant="ghost" size="icon" onClick={onRemove}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div
      {...getRootProps()}
      className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
        isDragActive ? "border-primary bg-primary/5" : "border-muted-foreground/25 hover:border-primary/50"
      }`}
    >
      <input {...getInputProps()} />
      <Icon className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
      <p className="font-medium mb-1">{label}</p>
      <p className="text-sm text-muted-foreground">{description}</p>
    </div>
  );
}

// Main page component
export default function NewJobPage() {
  const router = useRouter();
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [scriptFile, setScriptFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [characterGuide, setCharacterGuide] = useState("");
  const [targetDuration, setTargetDuration] = useState("");
  const [seriesId, setSeriesId] = useState("");
  const [enableAiMatching, setEnableAiMatching] = useState(true);
  const [enableCopyrightProtection, setEnableCopyrightProtection] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  
  // Usage/quota state
  const [usage, setUsage] = useState<UsageData | null>(null);
  const [loadingUsage, setLoadingUsage] = useState(true);
  
  // Fetch usage data on mount
  useEffect(() => {
    async function fetchUsage() {
      try {
        const res = await fetch("/api/usage");
        if (res.ok) {
          const data = await res.json();
          setUsage(data);
        }
      } catch (error) {
        console.error("Failed to fetch usage:", error);
      } finally {
        setLoadingUsage(false);
      }
    }
    fetchUsage();
  }, []);
  
  // Calculate if user can upload based on quota
  const remainingMinutes = usage ? Math.max(0, usage.totalAvailableMinutes - usage.minutesUsed) : 0;
  const canUpload = remainingMinutes > 0;

  const handleVideosDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      setVideoFile(acceptedFiles[0]);
      // Auto-fill title from filename
      if (!title) {
        const name = acceptedFiles[0].name.replace(/\.[^/.]+$/, "");
        setTitle(name);
      }
    }
  }, [title]);

  const handleScriptDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      setScriptFile(acceptedFiles[0]);
    }
  }, []);

  const handleSubmit = async () => {
    if (!videoFile) {
      toast.error("Please select a video file");
      return;
    }

    setUploading(true);
    setUploadProgress(0);

    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL;
      if (!apiBase) {
        throw new Error("Missing NEXT_PUBLIC_API_URL");
      }

      // Get a short-lived backend JWT (small request to Vercel).
      const tokenRes = await fetch("/api/backend/token");
      if (!tokenRes.ok) {
        const err = await tokenRes.json().catch(() => ({}));
        throw new Error(err?.message || "Unable to authorize upload");
      }
      const { token: backendToken } = (await tokenRes.json()) as { token: string };
      if (!backendToken) {
        throw new Error("Missing backend token");
      }

      // Quick connectivity/CORS check (gives a better error than XHR "network error")
      try {
        await fetch(`${apiBase}/health`, { method: "GET" });
      } catch {
        throw new Error(
          "Cannot reach backend from browser (likely CORS or wrong NEXT_PUBLIC_API_URL). " +
            "Ensure NEXT_PUBLIC_API_URL is https://videoeditor-production-352d.up.railway.app and Railway CORS_ORIGINS includes https://app.videorecapai.com",
        );
      }

      const formData = new FormData();
      formData.append("file", videoFile);
      if (scriptFile) {
        formData.append("script", scriptFile);
      }
      if (targetDuration) {
        formData.append("target_duration_minutes", targetDuration);
      }
      if (characterGuide) {
        formData.append("character_guide", characterGuide);
      }
      if (seriesId) {
        formData.append("series_id", seriesId);
      }
      formData.append("enable_scene_matcher", enableAiMatching.toString());
      formData.append("enable_copyright_protection", enableCopyrightProtection.toString());

      // Upload with progress tracking
      const xhr = new XMLHttpRequest();
      
      xhr.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable) {
          const progress = Math.round((event.loaded / event.total) * 100);
          setUploadProgress(progress);
        }
      });

      const response = await new Promise<{ job_id: string; video_id: string; message?: string }>((resolve, reject) => {
        xhr.addEventListener("load", () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(JSON.parse(xhr.responseText));
          } else {
            // Parse error response for better messages
            try {
              const errorData = JSON.parse(xhr.responseText);
              if (errorData.error === "quota_exceeded") {
                reject(new Error(`Quota exceeded: ${errorData.message}`));
              } else if (errorData.error === "payment_required") {
                reject(new Error(`Payment required: ${errorData.message}`));
              } else {
                reject(new Error(errorData.message || "Upload failed"));
              }
            } catch {
              reject(new Error(xhr.responseText || "Upload failed"));
            }
          }
        });
        xhr.timeout = 10 * 60 * 1000; // 10 minutes
        xhr.addEventListener("timeout", () =>
          reject(new Error("Upload timed out. Try a smaller file or check your connection.")),
        );
        xhr.addEventListener("error", () => {
          // When CORS blocks the response, browsers surface it as a generic network error (status=0).
          reject(
            new Error(
              "Upload failed - network/CORS error. " +
                "Check DevTools Console for a CORS message. " +
                "Fix: set Railway CORS_ORIGINS to include https://app.videorecapai.com and ensure NEXT_PUBLIC_API_URL is correct.",
            ),
          );
        });
        
        // IMPORTANT: upload directly to backend to avoid Vercel function payload limits.
        xhr.open("POST", `${apiBase}/api/videos/upload`);
        xhr.setRequestHeader("Authorization", `Bearer ${backendToken}`);
        xhr.send(formData);
      });

      // Create local DB record for dashboard (small request to Vercel).
      const importRes = await fetch("/api/jobs/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          backendJobId: response.job_id,
          videoId: response.video_id,
          title: title || videoFile.name.replace(/\.[^/.]+$/, ""),
        }),
      });
      if (!importRes.ok) {
        throw new Error("Upload succeeded but failed to create local job record");
      }
      const imported = await importRes.json();

      toast.success("Video uploaded! Processing will begin shortly.");
      router.push(`/dashboard/jobs/${imported.job_id}`);
    } catch (error) {
      console.error("Upload error:", error);
      const message = error instanceof Error ? error.message : "Failed to upload video";
      
      // Check for quota/payment errors and suggest action
      if (message.includes("quota") || message.includes("Quota")) {
        toast.error(message, {
          action: {
            label: "Buy Top-up",
            onClick: () => router.push("/dashboard/billing"),
          },
        });
      } else if (message.includes("payment") || message.includes("Payment")) {
        toast.error(message, {
          action: {
            label: "Upgrade",
            onClick: () => router.push("/dashboard/billing"),
          },
        });
      } else {
        toast.error(message);
      }
    } finally {
      setUploading(false);
    }
  };

  return (
    <TooltipProvider>
      <>
        <DashboardHeader
          heading="Create New Job"
          text="Upload a video and configure processing options."
        />

        <div className="grid gap-6 lg:grid-cols-3">
          {/* Main upload area */}
          <div className="lg:col-span-2 space-y-6">
            {/* Video Upload */}
            <Card>
              <CardHeader>
                <CardTitle>Video File</CardTitle>
                <CardDescription>
                  Upload the video you want to process. Supported formats: MP4, MOV, AVI, MKV.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <FileDropZone
                  accept={{
                    "video/*": [".mp4", ".mov", ".avi", ".mkv", ".webm"],
                  }}
                  onDrop={handleVideosDrop}
                  file={videoFile}
                  onRemove={() => setVideoFile(null)}
                  label="Drop your video here"
                  description="or click to browse"
                  icon={FileVideo}
                />
              </CardContent>
            </Card>

            {/* Script Upload (Optional) */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  Narration Script
                  <span className="text-xs font-normal text-muted-foreground">(Optional)</span>
                </CardTitle>
                <CardDescription>
                  Upload a custom script for the AI to narrate. If not provided, the AI will generate one automatically.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <FileDropZone
                  accept={{
                    "text/*": [".txt", ".md"],
                  }}
                  onDrop={handleScriptDrop}
                  file={scriptFile}
                  onRemove={() => setScriptFile(null)}
                  label="Drop your script here"
                  description="or click to browse (.txt, .md)"
                  icon={FileText}
                />
              </CardContent>
            </Card>

            {/* Job Details */}
            <Card>
              <CardHeader>
                <CardTitle>Job Details</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="title">Title</Label>
                  <Input
                    id="title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Enter a title for this job"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="duration" className="flex items-center gap-2">
                    Target Duration (minutes)
                    <Tooltip>
                      <TooltipTrigger>
                        <Info className="h-4 w-4 text-muted-foreground" />
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>Approximate target length for the final video.</p>
                        <p>Leave empty for automatic duration.</p>
                      </TooltipContent>
                    </Tooltip>
                  </Label>
                  <Input
                    id="duration"
                    type="number"
                    value={targetDuration}
                    onChange={(e) => setTargetDuration(e.target.value)}
                    placeholder="e.g., 10"
                    min="1"
                    max="60"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="series" className="flex items-center gap-2">
                    Series ID
                    <Tooltip>
                      <TooltipTrigger>
                        <Info className="h-4 w-4 text-muted-foreground" />
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>Use the same Series ID for episodes of the same show</p>
                        <p>to maintain consistent character names.</p>
                      </TooltipContent>
                    </Tooltip>
                  </Label>
                  <Input
                    id="series"
                    value={seriesId}
                    onChange={(e) => setSeriesId(e.target.value)}
                    placeholder="e.g., breaking-bad"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="characters" className="flex items-center gap-2">
                    Character Guide
                    <Tooltip>
                      <TooltipTrigger>
                        <Info className="h-4 w-4 text-muted-foreground" />
                      </TooltipTrigger>
                      <TooltipContent className="max-w-xs">
                        <p>Map character descriptions to proper names.</p>
                        <p className="mt-1 text-xs">Example:</p>
                        <p className="text-xs">Woman with powers = The Ancient One</p>
                        <p className="text-xs">Skeptical man = Doctor Strange</p>
                      </TooltipContent>
                    </Tooltip>
                  </Label>
                  <Textarea
                    id="characters"
                    value={characterGuide}
                    onChange={(e) => setCharacterGuide(e.target.value)}
                    placeholder="Woman with powers = The Ancient One&#10;Skeptical man = Doctor Strange"
                    rows={3}
                  />
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Sidebar with options */}
          <div className="space-y-6">
            {/* AI Features */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Sparkles className="h-5 w-5 text-primary" />
                  AI Features
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="ai-matching">AI Clip Matching</Label>
                    <p className="text-xs text-muted-foreground">
                      Intelligently match clips to script
                    </p>
                  </div>
                  <Switch
                    id="ai-matching"
                    checked={enableAiMatching}
                    onCheckedChange={setEnableAiMatching}
                  />
                </div>

                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="copyright" className="flex items-center gap-1">
                      <Shield className="h-4 w-4" />
                      Copyright Protection
                    </Label>
                    <p className="text-xs text-muted-foreground">
                      Apply visual transforms to avoid detection
                    </p>
                  </div>
                  <Switch
                    id="copyright"
                    checked={enableCopyrightProtection}
                    onCheckedChange={setEnableCopyrightProtection}
                  />
                </div>
              </CardContent>
            </Card>

            {/* Usage/Quota Status */}
            {!loadingUsage && usage && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Clock className="h-4 w-4" />
                    Your Quota
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Used</span>
                      <span>{usage.minutesUsed.toFixed(1)} / {usage.totalAvailableMinutes} min</span>
                    </div>
                    <Progress value={usage.percentUsed} className="h-2" />
                    <p className="text-xs text-muted-foreground">
                      {remainingMinutes.toFixed(1)} minutes remaining this month
                    </p>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Quota Warning/Error */}
            {!loadingUsage && usage && !usage.canProcess && (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>No Minutes Available</AlertTitle>
                <AlertDescription>
                  You need minutes to process videos.{" "}
                  <Link href="/dashboard/billing" className="underline font-medium">
                    Get minutes
                  </Link>
                </AlertDescription>
              </Alert>
            )}

            {!loadingUsage && usage && usage.canProcess && remainingMinutes <= 0 && (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Quota Exceeded</AlertTitle>
                <AlertDescription>
                  You&apos;ve used all your minutes for this month.{" "}
                  <Link href="/dashboard/billing" className="underline font-medium">
                    Buy a top-up
                  </Link>{" "}
                  to continue processing.
                </AlertDescription>
              </Alert>
            )}

            {!loadingUsage && usage && usage.canProcess && remainingMinutes > 0 && remainingMinutes < 10 && (
              <Alert>
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Low Quota</AlertTitle>
                <AlertDescription>
                  You have only {remainingMinutes.toFixed(1)} minutes remaining.{" "}
                  <Link href="/dashboard/billing" className="underline">
                    Consider a top-up
                  </Link>
                </AlertDescription>
              </Alert>
            )}

            {/* Submit */}
            <Card>
              <CardContent className="pt-6">
                {uploading ? (
                  <div className="space-y-4">
                    <div className="flex items-center justify-center gap-2">
                      <Loader2 className="h-5 w-5 animate-spin" />
                      <span>Uploading...</span>
                    </div>
                    <Progress value={uploadProgress} />
                    <p className="text-center text-sm text-muted-foreground">
                      {uploadProgress}% complete
                    </p>
                  </div>
                ) : (
                  <Button 
                    className="w-full" 
                    size="lg"
                    onClick={handleSubmit}
                    disabled={!videoFile || !canUpload}
                  >
                    <Upload className="h-4 w-4 mr-2" />
                    Start Processing
                  </Button>
                )}

                {!videoFile && canUpload && (
                  <p className="text-center text-sm text-muted-foreground mt-4">
                    Please select a video file to continue
                  </p>
                )}

                {!canUpload && !loadingUsage && (
                  <p className="text-center text-sm text-destructive mt-4">
                    Buy minutes to process videos
                  </p>
                )}
              </CardContent>
            </Card>

            {/* Info */}
            <Card className="bg-muted/50">
              <CardContent className="pt-6">
                <h4 className="font-medium mb-2">Processing Info</h4>
                <ul className="text-sm text-muted-foreground space-y-1">
                  <li>• Processing typically takes 5-15 minutes</li>
                  <li>• You&apos;ll be notified when complete</li>
                  <li>• Videos are stored securely</li>
                </ul>
              </CardContent>
            </Card>
          </div>
        </div>
      </>
    </TooltipProvider>
  );
}

