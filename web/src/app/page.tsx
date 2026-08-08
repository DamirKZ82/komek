'use client';

import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

import { hasTokens } from '@/lib/api';

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(hasTokens() ? '/verification' : '/login');
  }, [router]);
  return null;
}
