import type { Metadata } from "next";
import { Instrument_Serif, Inter_Tight, JetBrains_Mono } from "next/font/google";
import Link from "next/link";
import { MotionConfig } from "framer-motion";
import { Wordmark } from "@/components/logo";
import "./globals.css";

const serif = Instrument_Serif({ variable: "--font-instrument", subsets: ["latin"], weight: "400" });
const body = Inter_Tight({ variable: "--font-body", subsets: ["latin"], weight: ["400", "500", "600"] });
const mono = JetBrains_Mono({ variable: "--font-mono", subsets: ["latin"], weight: ["400", "500"] });

export const metadata: Metadata = {
  title: "locus",
  description: "Ask in plain English. Land on the exact public omics dataset.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${serif.variable} ${body.variable} ${mono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-background text-foreground font-sans">
        <MotionConfig reducedMotion="user">
          <header className="border-b border-rule px-5 py-3.5">
            <div className="mx-auto flex w-full max-w-3xl items-center justify-between">
              <Link href="/" aria-label="locus home"><Wordmark className="text-[28px]" /></Link>
              <span className="label text-muted-foreground" title="GEO, ArrayExpress, ENA, PRIDE, MassIVE, MetaboLights, CELLxGENE and 11 more">891k datasets · 18 repositories</span>
            </div>
          </header>
          <main className="flex-1 w-full px-5 pt-12 pb-24">{children}</main>
        </MotionConfig>
      </body>
    </html>
  );
}
