'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { api, ApiError, saveTokens } from '@/lib/api';

interface OtpOut {
  debug_code: string | null;
}

interface Tokens {
  access_token: string;
  refresh_token: string;
}

export default function LoginPage() {
  const router = useRouter();
  const [phone, setPhone] = useState('+7');
  const [code, setCode] = useState('');
  const [step, setStep] = useState<'phone' | 'code'>('phone');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const requestCode = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api<OtpOut>('/auth/otp/request', {
        method: 'POST',
        body: { phone },
        auth: false,
      });
      if (result.debug_code) setCode(result.debug_code);
      setStep('code');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка');
    } finally {
      setBusy(false);
    }
  };

  const login = async () => {
    setBusy(true);
    setError(null);
    try {
      const tokens = await api<Tokens>('/auth/otp/verify', {
        method: 'POST',
        body: { phone, code, locale: 'ru' },
        auth: false,
      });
      saveTokens(tokens.access_token, tokens.refresh_token);
      // Доступ к очередям всё равно проверяется на бэкенде (403 для не-staff).
      router.push('/verification');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="form">
      <h1>Komek · Модерация</h1>
      <p className="muted">Вход только для сотрудников (роль назначается администратором)</p>
      {step === 'phone' ? (
        <>
          <input
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            placeholder="+7 701 123 45 67"
            autoFocus
          />
          <button className="primary" onClick={requestCode} disabled={busy}>
            Получить код
          </button>
        </>
      ) : (
        <>
          <input
            value={code}
            onChange={(event) => setCode(event.target.value)}
            placeholder="Код из SMS"
            autoFocus
          />
          <button className="primary" onClick={login} disabled={busy}>
            Войти
          </button>
        </>
      )}
      {error ? <div className="error">{error}</div> : null}
    </div>
  );
}
