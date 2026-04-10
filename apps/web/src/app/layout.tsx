import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'ClaimRepro',
  description: 'Reproduce and verify scientific claims against immunology study data',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
