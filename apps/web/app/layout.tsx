import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "面試練習室",
  description: "把每一道題目，變成可以解釋的知識。",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-Hant">
      <body>{children}</body>
    </html>
  );
}
