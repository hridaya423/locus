import { PersonPage } from "@/components/person";

export default async function Page({ params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  return <PersonPage name={decodeURIComponent(name)} />;
}
