import Link from "next/link";
import { Zap } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export function UpgradeCard() {
  return (
    <Card className="md:max-xl:rounded-none md:max-xl:border-none md:max-xl:shadow-none bg-gradient-to-br from-primary/10 to-primary/5">
      <CardHeader className="md:max-xl:px-4">
        <CardTitle className="flex items-center gap-2">
          <Zap className="h-5 w-5 text-primary" />
          Need More Minutes?
        </CardTitle>
        <CardDescription>
          Upgrade your plan or buy a top-up to process more videos.
        </CardDescription>
      </CardHeader>
      <CardContent className="md:max-xl:px-4">
        <Button size="sm" className="w-full" asChild>
          <Link href="/dashboard/billing">
            View Plans
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}
