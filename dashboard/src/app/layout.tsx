import type { Metadata } from "next";
import { Outfit, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";
import { ThemeToggle } from "@/components/theme-toggle";
import { ThemeProvider } from "@/components/theme-provider";
const outfit = Outfit({
  variable: "--font-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Nivesh AI AMC Pipeline Dashboard",
  description: "Monitor and manage AMC ingestion, extraction, and drift alerts.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${outfit.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>

      </head>
      <body className="relative h-screen w-full flex bg-zinc-100 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-50 font-sans">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <Sidebar />
          <main className="relative flex-1 flex flex-col min-h-screen overflow-auto">
            <header className="sticky top-0 z-50 flex w-full h-[10%] items-center justify-end px-8 py-3 border-b border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950/40 backdrop-blur">
              <ThemeToggle />
            </header>
            <div className="h-full flex-1 flex flex-col">
              {children}
            </div>
          </main>
        </ThemeProvider>
      </body>
    </html>
  );
}
