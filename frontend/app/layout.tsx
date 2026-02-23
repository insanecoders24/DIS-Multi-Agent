import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DIS — Document Intelligence System",
  description:
    "Regulatory-grade deterministic PDF structure extraction. Full evidence anchoring, traceability, and uncertainty reporting.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
