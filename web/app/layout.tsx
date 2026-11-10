import type { Metadata } from "next";
import { Instrument_Serif, Inter_Tight, JetBrains_Mono } from "next/font/google";
import { MotionConfig } from "framer-motion";
import { AccountMenu } from "@/components/account-menu";
import { GuestImport } from "@/components/guest-import";
import { CommandPalette } from "@/components/command-palette";
import { Toaster } from "@/components/toast";
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
          <AccountMenu />
          <main className="flex-1 w-full px-5 pt-12 pb-[calc(6rem+var(--dock,0px))]">
            <GuestImport />
            {children}
          </main>
          <Toaster />
          <CommandPalette />
        </MotionConfig>
      </body>
    </html>
  );
}
