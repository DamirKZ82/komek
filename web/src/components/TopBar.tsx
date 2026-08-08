'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';

import { clearTokens, hasTokens } from '@/lib/api';

export function TopBar() {
  const pathname = usePathname();
  const router = useRouter();
  if (pathname === '/login') return null;

  const links = [
    { href: '/dashboard', label: 'Дашборд' },
    { href: '/verification', label: 'Верификация' },
    { href: '/complaints', label: 'Жалобы' },
    { href: '/reviews', label: 'Отзывы' },
    { href: '/finance', label: 'Финансы' },
    { href: '/settings', label: 'Настройки' },
  ];

  return (
    <div className="topbar">
      <div className="container">
        <span className="brand">Komek · Модерация</span>
        {links.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={pathname.startsWith(link.href) ? 'active' : ''}
          >
            {link.label}
          </Link>
        ))}
        <span className="spacer" />
        {hasTokens() ? (
          <a
            href="/login"
            onClick={(event) => {
              event.preventDefault();
              clearTokens();
              router.push('/login');
            }}
          >
            Выйти
          </a>
        ) : null}
      </div>
    </div>
  );
}
