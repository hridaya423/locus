import { Suspense } from "react";
import { ListPage } from "@/components/your-list";

export default function Page() {
  return (
    <Suspense>
      <ListPage />
    </Suspense>
  );
}
