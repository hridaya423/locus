import { Suspense } from "react";
import type { Metadata } from "next";
import { ListPage } from "@/components/saved-lists";

export const metadata: Metadata = { title: "List · locus" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <ListPage id={id} />
    </Suspense>
  );
}
