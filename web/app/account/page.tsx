import { Suspense } from "react";
import type { Metadata } from "next";
import { AccountPage } from "@/components/account-page";

export const metadata: Metadata = { title: "Account · locus" };

export const dynamic = "force-dynamic";

export default function Page() {
  return (
    <Suspense>
      <AccountPage />
    </Suspense>
  );
}
