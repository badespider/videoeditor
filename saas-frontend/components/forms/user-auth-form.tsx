"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { signIn } from "next-auth/react";
import { useForm } from "react-hook-form";
import * as z from "zod";

import { cn } from "@/lib/utils";
import { userAuthSchema } from "@/lib/validations/auth";
import { buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { Icons } from "@/components/shared/icons";

interface UserAuthFormProps extends React.HTMLAttributes<HTMLDivElement> {
  type?: string;
}

type FormData = z.infer<typeof userAuthSchema>;

export function UserAuthForm({ className, type, ...props }: UserAuthFormProps) {
  const [providers, setProviders] = React.useState<Record<string, any> | null>(
    null,
  );
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormData>({
    resolver: zodResolver(userAuthSchema),
  });
  const [isLoading, setIsLoading] = React.useState<boolean>(false);
  const [isGoogleLoading, setIsGoogleLoading] = React.useState<boolean>(false);
  const [isDevLoading, setIsDevLoading] = React.useState<boolean>(false);
  const searchParams = useSearchParams();

  React.useEffect(() => {
    let mounted = true;
    fetch("/api/auth/providers")
      .then((r) => r.json())
      .then((data) => {
        if (mounted) setProviders(data);
      })
      .catch(() => {
        if (mounted) setProviders({});
      });
    return () => {
      mounted = false;
    };
  }, []);

  async function onSubmit(data: FormData) {
    if (!providers) return;

    // Prefer email magic-link (resend) when configured; otherwise use dev credentials.
    const hasResend = Boolean((providers as any)?.resend);
    const hasDev = Boolean((providers as any)?.credentials);

    if (hasResend) {
      setIsLoading(true);

      const signInResult = await signIn("resend", {
        email: data.email.toLowerCase(),
        redirect: false,
        callbackUrl: searchParams?.get("from") || "/dashboard",
      });

      setIsLoading(false);

      if (!signInResult?.ok) {
        return toast.error("Something went wrong.", {
          description: "Your sign in request failed. Please try again.",
        });
      }

      return toast.success("Check your email", {
        description:
          "We sent you a login link. Be sure to check your spam too.",
      });
    }

    if (hasDev) {
      setIsDevLoading(true);
      const signInResult = await signIn("credentials", {
        email: data.email.toLowerCase(),
        redirect: false,
        callbackUrl: searchParams?.get("from") || "/dashboard",
      });
      setIsDevLoading(false);

      if (!signInResult?.ok) {
        return toast.error("Dev sign in failed.", {
          description: "Please try again.",
        });
      }

      return toast.success("Signed in (dev)", {
        description: "Redirecting to dashboard…",
      });
    }

    return toast.error("No auth providers configured.", {
      description:
        "Set Google/Resend env vars, or run in development mode for Dev Login.",
    });
  }

  return (
    <div className={cn("grid gap-6", className)} {...props}>
      <form onSubmit={handleSubmit(onSubmit)}>
        <div className="grid gap-2">
          <div className="grid gap-1">
            <Label className="sr-only" htmlFor="email">
              Email
            </Label>
            <Input
              id="email"
              placeholder="name@example.com"
              type="email"
              autoCapitalize="none"
              autoComplete="email"
              autoCorrect="off"
              disabled={isLoading || isGoogleLoading}
              {...register("email")}
            />
            {errors?.email && (
              <p className="px-1 text-xs text-red-600">
                {errors.email.message}
              </p>
            )}
          </div>
          <button
            className={cn(buttonVariants())}
            disabled={isLoading || isGoogleLoading || isDevLoading}
            type="submit"
          >
            {(isLoading || isDevLoading) && (
              <Icons.spinner className="mr-2 size-4 animate-spin" />
            )}
            {providers && (providers as any)?.resend
              ? type === "register"
                ? "Sign Up with Email"
                : "Sign In with Email"
              : "Sign In (Dev)"}
          </button>
        </div>
      </form>

      {!!providers?.google && (
        <>
          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <span className="w-full border-t" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-background px-2 text-muted-foreground">
                Or continue with
              </span>
            </div>
          </div>
          <button
            type="button"
            className={cn(buttonVariants({ variant: "outline" }))}
            onClick={() => {
              setIsGoogleLoading(true);
              const from = searchParams?.get("from") || "/dashboard";
              const buy = searchParams?.get("buy");
              const plan = searchParams?.get("plan");
              const callbackUrl = (() => {
                const qs = new URLSearchParams();
                if (buy) qs.set("buy", buy);
                if (plan) qs.set("plan", plan);
                const q = qs.toString();
                return q ? `${from}${from.includes("?") ? "&" : "?"}${q}` : from;
              })();
              signIn("google", { callbackUrl });
            }}
            disabled={isLoading || isGoogleLoading || isDevLoading}
          >
            {isGoogleLoading ? (
              <Icons.spinner className="mr-2 size-4 animate-spin" />
            ) : (
              <Icons.google className="mr-2 size-4" />
            )}{" "}
            Google
          </button>
        </>
      )}
    </div>
  );
}
