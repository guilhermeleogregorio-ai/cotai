import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Comprador IA",
  description: "Plataforma de compras e cotações com agentes de IA",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-br">
      <body>{children}</body>
    </html>
  );
}
