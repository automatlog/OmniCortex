import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { HealthMonitor } from "@/components/HealthMonitor";
import { AuthGate } from "@/components/AuthGate";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "OmniCortex Admin",
  description: "Admin Dashboard for OmniCortex AI Platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.className} bg-neutral-950 text-white antialiased`}>
        <AuthGate>
          <HealthMonitor />
          <Sidebar />
          <main className="ml-64 min-h-screen p-6">
            {children}
          </main>
        </AuthGate>
      </body>
    </html>
  );
}
