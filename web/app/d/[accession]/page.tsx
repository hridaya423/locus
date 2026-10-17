import { DatasetPage } from "@/components/dataset";

export default async function Page({ params }: { params: Promise<{ accession: string }> }) {
  const { accession } = await params;
  return <DatasetPage accession={decodeURIComponent(accession)} />;
}
