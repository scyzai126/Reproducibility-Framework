import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'ImmTrace',
  description: 'Trace immunology study claims to ImmPort subjects and data',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
