import type { Metadata } from "next";
import { FollowingPage } from "@/components/following";

export const metadata: Metadata = { title: "Following · locus" };

export default function Page() {
  return <FollowingPage />;
}
