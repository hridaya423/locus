import { SamplePage } from "@/components/sample";

export default async function Page({ params }: { params: Promise<{ accession: string; sample: string }> }) {
  const { accession, sample } = await params;
  return <SamplePage dataset={decodeURIComponent(accession)} accession={decodeURIComponent(sample)} />;
}
