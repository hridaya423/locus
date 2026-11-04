import { Suspense } from "react";
import type { Metadata } from "next";
import { SettingsPage } from "@/components/settings-page";

export const metadata: Metadata = { title: "Settings · locus" };

export const dynamic = "force-dynamic";

export default function Page() {
  return (
    <Suspense>
      <SettingsPage />
    </Suspense>
  );
}
