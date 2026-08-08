/** Контекст авторизации: текущий пользователь, вход по OTP, выход. */
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

import {
  api,
  clearTokens,
  hasTokens,
  saveTokens,
  type OtpRequestOut,
  type TokenPair,
  type User,
} from './api';
import { registerPushToken } from './push';

interface AuthContextValue {
  user: User | null;
  initializing: boolean;
  requestOtp: (phone: string) => Promise<OtpRequestOut>;
  verifyOtp: (phone: string, code: string, locale: 'ru' | 'kk') => Promise<void>;
  refreshUser: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [initializing, setInitializing] = useState(true);

  const refreshUser = useCallback(async () => {
    const me = await api<User>('/me');
    setUser(me);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        if (await hasTokens()) await refreshUser();
      } catch {
        await clearTokens();
      } finally {
        setInitializing(false);
      }
    })();
  }, [refreshUser]);

  const requestOtp = useCallback(
    (phone: string) =>
      api<OtpRequestOut>('/auth/otp/request', { method: 'POST', body: { phone }, auth: false }),
    [],
  );

  const verifyOtp = useCallback(
    async (phone: string, code: string, locale: 'ru' | 'kk') => {
      const tokens = await api<TokenPair>('/auth/otp/verify', {
        method: 'POST',
        body: { phone, code, locale },
        auth: false,
      });
      await saveTokens(tokens.access_token, tokens.refresh_token);
      await refreshUser();
      registerPushToken(); // fire-and-forget
    },
    [refreshUser],
  );

  const logout = useCallback(async () => {
    await clearTokens();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, initializing, requestOtp, verifyOtp, refreshUser, logout }),
    [user, initializing, requestOtp, verifyOtp, refreshUser, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
