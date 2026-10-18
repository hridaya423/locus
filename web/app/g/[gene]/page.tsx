import { Suspense } from "react";
import { GenePage } from "@/components/gene";

export default async function Page({ params }: { params: Promise<{ gene: string }> }) {
  const { gene } = await params;
  return (
    <Suspense>
      <GenePage gene={decodeURIComponent(gene)} />
    </Suspense>
  );
}
