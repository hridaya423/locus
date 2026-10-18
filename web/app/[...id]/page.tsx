import { redirect } from "next/navigation";

export default async function Page({ params }: { params: Promise<{ id: string[] }> }) {
  const { id } = await params;
  redirect(`/?q=${encodeURIComponent(id.map(decodeURIComponent).join("/"))}`);
}
