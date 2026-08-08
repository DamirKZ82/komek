import type { Metadata } from 'next';

import './globals.css';
import { TopBar } from '@/components/TopBar';

export const metadata: Metadata = {
  title: 'Komek — админка',
  description: 'Модерация: верификация исполнителей, документы, жалобы',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>
        <TopBar />
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
