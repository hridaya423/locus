import { Suspense } from "react";
import { PersonPage } from "@/components/person";

export default async function Page({ params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  // Suspense: the Follow control's sign-in prompt reads the query string (useSearchParams).
  return (
    <Suspense>
      <PersonPage name={decodeURIComponent(name)} />
    </Suspense>
  );
}
