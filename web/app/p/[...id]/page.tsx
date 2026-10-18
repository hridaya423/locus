import { PaperPage } from "@/components/paper";

export default async function Page({ params }: { params: Promise<{ id: string[] }> }) {
  const { id } = await params;
  return <PaperPage id={id.map(decodeURIComponent).join("/")} />;
}
