import { Suspense } from "react";
import { BrowsePage } from "@/components/browse";

export default function Page() {
  return (
    <Suspense>
      <BrowsePage />
    </Suspense>
  );
}
