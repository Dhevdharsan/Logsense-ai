import type { Metadata } from "next";
import "./globals.css";
import Link from "next/link";

export const metadata: Metadata = {
  title: "LogSense AI",
  description: "AI-powered log intelligence",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-950 text-gray-100 min-h-screen flex">
        <aside className="w-56 bg-gray-900 border-r border-gray-800 flex flex-col fixed h-full">
          <div className="p-4 border-b border-gray-800">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center text-white font-bold text-sm">LS</div>
              <div>
                <div className="font-bold text-white text-sm">LogSense AI</div>
                <div className="text-xs text-gray-500">MVP v0.1</div>
              </div>
            </div>
          </div>
          <nav className="flex-1 p-3 space-y-1">
            {[["/" , "▦", "Dashboard"], ["/logs", "☰", "Log Browser"], ["/anomalies", "⚠", "Anomalies"], ["/clusters", "◎", "Clusters"]].map(([href, icon, label]) => (
              <Link key={href} href={href} className="flex items-center gap-3 px-3 py-2 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 transition-colors text-sm">
                <span className="text-gray-500">{icon}</span>{label}
              </Link>
            ))}
          </nav>
          <div className="p-3 border-t border-gray-800 text-xs text-gray-600">LogSense AI — Local MVP</div>
        </aside>
        <main className="ml-56 flex-1 p-6">{children}</main>
      </body>
    </html>
  );
}
