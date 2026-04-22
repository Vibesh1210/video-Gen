import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Lip-Sync Studio",
  description: "Text + face → lip-synced video.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
