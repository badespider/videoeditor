"use client";

import * as React from "react";
import { SessionProvider } from "next-auth/react";
import { ThemeProvider } from "next-themes";

import { Analytics } from "@/components/analytics";
import ModalProvider from "@/components/modals/providers";
import { Toaster } from "@/components/ui/sonner";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <ThemeProvider
        attribute="class"
        defaultTheme="system"
        enableSystem
        disableTransitionOnChange
      >
        <ModalProvider>{children}</ModalProvider>
        <Analytics />
        <Toaster richColors closeButton />
      </ThemeProvider>
    </SessionProvider>
  );
}

