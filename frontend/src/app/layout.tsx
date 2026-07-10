import type { Metadata } from "next";
import { headers } from "next/headers";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";
import { DemoBanner } from "@/components/demo-banner";
import { DemoModeProvider } from "@/lib/demo";

const geistSans = GeistSans;
const geistMono = GeistMono;

export const metadata: Metadata = {
  title: "Seeker OS",
  description: "Structured job search pipeline",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const headerList = await headers();
  const cookieTheme = headerList.get("cookie")?.match(/seeker-os-theme=(dark|light)/)?.[1];
  const isDark = cookieTheme === "dark";

  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased${isDark ? " dark" : ""}`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('seeker-os-theme');var d=t?t==='dark':window.matchMedia('(prefers-color-scheme: dark)').matches;if(d)document.documentElement.classList.add('dark');}catch(e){}})();`,
          }}
        />
        <DemoModeProvider>
          <DemoBanner />
          <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 overflow-auto p-4 md:p-6">{children}</main>
          </div>
        </DemoModeProvider>
      </body>
    </html>
  );
}
