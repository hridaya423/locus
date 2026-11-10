import { Suspense } from "react";
import type { Metadata } from "next";
import { ListsPage } from "@/components/saved-lists";

export const metadata: Metadata = { title: "Lists · locus" };

export default function Page() {
  return (
    <Suspense>
      <ListsPage />
    </Suspense>
  );
}
