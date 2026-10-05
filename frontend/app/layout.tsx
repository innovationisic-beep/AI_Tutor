import type { Metadata } from "next";
import { Inter, Patrick_Hand } from "next/font/google";
import { AuthProvider } from "@/components/providers/AuthProvider";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });

const patrickHand = Patrick_Hand({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-handwriting",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AI Tutor",
  description: "Learn with explanations, quizzes, and feedback",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} ${patrickHand.variable} min-h-screen font-sans`}>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
