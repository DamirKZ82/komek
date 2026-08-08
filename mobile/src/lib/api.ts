/**
 * Клиент Komek API: авторизация Bearer-токеном, автоматический refresh.
 * Базовый URL задаётся переменной EXPO_PUBLIC_API_URL (для устройства — IP машины с бэкендом).
 */
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

export const API_URL =
  process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

const ACCESS_KEY = 'komek_access_token';
const REFRESH_KEY = 'komek_refresh_token';

// SecureStore не работает в вебе — фолбэк на localStorage (dev-режим).
async function storageGet(key: string): Promise<string | null> {
  if (Platform.OS === 'web') return globalThis.localStorage?.getItem(key) ?? null;
  return SecureStore.getItemAsync(key);
}

async function storageSet(key: string, value: string): Promise<void> {
  if (Platform.OS === 'web') {
    globalThis.localStorage?.setItem(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value);
}

async function storageDelete(key: string): Promise<void> {
  if (Platform.OS === 'web') {
    globalThis.localStorage?.removeItem(key);
    return;
  }
  await SecureStore.deleteItemAsync(key);
}

export async function saveTokens(access: string, refresh: string): Promise<void> {
  await storageSet(ACCESS_KEY, access);
  await storageSet(REFRESH_KEY, refresh);
}

export async function clearTokens(): Promise<void> {
  await storageDelete(ACCESS_KEY);
  await storageDelete(REFRESH_KEY);
}

export async function hasTokens(): Promise<boolean> {
  return (await storageGet(ACCESS_KEY)) !== null;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function tryRefresh(): Promise<boolean> {
  const refresh = await storageGet(REFRESH_KEY);
  if (!refresh) return false;
  const resp = await fetch(`${API_URL}/api/v1/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!resp.ok) {
    await clearTokens();
    return false;
  }
  const data = await resp.json();
  await saveTokens(data.access_token, data.refresh_token);
  return true;
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown; auth?: boolean; retry?: boolean } = {},
): Promise<T> {
  const { method = 'GET', body, auth = true, retry = true } = options;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (auth) {
    const token = await storageGet(ACCESS_KEY);
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  const resp = await fetch(`${API_URL}/api/v1${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (resp.status === 401 && auth && retry && (await tryRefresh())) {
    return api<T>(path, { method, body, auth, retry: false });
  }

  if (!resp.ok) {
    let code = 'unknown';
    let message = `HTTP ${resp.status}`;
    try {
      const payload = await resp.json();
      code = payload?.error?.code ?? code;
      message = payload?.error?.message ?? message;
    } catch {
      // тело не JSON — оставляем дефолт
    }
    throw new ApiError(resp.status, code, message);
  }
  return (await resp.json()) as T;
}

// --- Типы ответов API (минимум, который нужен экранам) ---

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  is_new_user: boolean;
}

export interface OtpRequestOut {
  expires_in: number;
  resend_after: number;
  debug_code: string | null;
}

export interface User {
  id: string;
  phone: string;
  first_name: string | null;
  last_name: string | null;
  locale: 'ru' | 'kk';
  is_customer: boolean;
  is_provider: boolean;
  /** Заполнено после прохождения KYC — даёт значок «проверенный» (п. 4.3 ТЗ). */
  identity_verified_at: string | null;
}

export interface Service {
  id: string;
  category_id: string;
  code: string;
  name: string;
  allowed_price_units: string[];
  supports_urgent: boolean;
}

export interface Category {
  id: string;
  code: string;
  vertical: 'children' | 'elderly' | 'disability' | 'pets';
  name: string;
  icon: string | null;
  services: Service[];
}

export interface ProviderCard {
  user_id: string;
  first_name: string | null;
  last_name: string | null;
  headline: string | null;
  verification_level: 'level_0' | 'level_1' | 'level_2' | 'level_3';
  experience_years: number;
  rating_avg: string | null;
  rating_count: number;
  completed_orders_count: number;
  min_price: string | null;
  price_unit: string | null;
  accepts_urgent: boolean;
  languages: string[];
  is_favorite: boolean;
}

export interface ProviderDetail extends ProviderCard {
  about: string | null;
  education: string | null;
  work_radius_km: number;
  documents_valid_until: string | null;
  services: {
    id: string;
    service_id: string;
    service_name: string | null;
    price: string;
    price_unit: string;
  }[];
}

export interface Order {
  id: string;
  code: string;
  status: string;
  service_id: string;
  provider_user_id: string | null;
  scheduled_start: string;
  scheduled_end: string;
  estimated_total: string;
  final_total: string | null;
  unit_price: string;
  is_urgent: boolean;
  comment: string | null;
  responses_count: number;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ThreadPeer {
  id: string;
  first_name: string | null;
  last_name: string | null;
  avatar_key: string | null;
}

export interface ChatThread {
  id: string;
  peer: ThreadPeer;
  last_order_id: string | null;
  contacts_unlocked: boolean;
  last_message_at: string | null;
  last_message_preview: string | null;
  unread_count: number;
}

export interface ChatMessage {
  id: string;
  thread_id: string;
  sender_id: string | null;
  message_type: 'text' | 'image' | 'audio' | 'system';
  body: string | null;
  contacts_masked: boolean;
  has_attachment: boolean;
  duration_seconds: number | null;
  created_at: string;
}

/** Читает токен так же, как api(): нужен для multipart и прямых ссылок на файлы. */
export async function getAccessToken(): Promise<string | null> {
  const { Platform } = await import('react-native');
  if (Platform.OS === 'web') return globalThis.localStorage?.getItem('komek_access_token') ?? null;
  const SecureStore = await import('expo-secure-store');
  return SecureStore.getItemAsync('komek_access_token');
}

/** Отправка фото/голосового в диалог (multipart). */
export async function sendChatAttachment(
  threadId: string,
  file: { uri: string; name: string; mimeType: string },
  extra: { caption?: string; durationSeconds?: number } = {},
): Promise<ChatMessage> {
  const form = new FormData();
  if (extra.caption) form.append('caption', extra.caption);
  if (extra.durationSeconds !== undefined) {
    form.append('duration_seconds', String(Math.round(extra.durationSeconds)));
  }
  if (file.uri.startsWith('data:') || file.uri.startsWith('blob:')) {
    const blob = await (await fetch(file.uri)).blob();
    form.append('file', blob, file.name);
  } else {
    form.append('file', { uri: file.uri, name: file.name, type: file.mimeType } as unknown as Blob);
  }

  const token = await getAccessToken();
  const resp = await fetch(`${API_URL}/api/v1/chats/${threadId}/attachments`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
  });
  if (!resp.ok) {
    let message = `HTTP ${resp.status}`;
    let code = 'unknown';
    try {
      const payload = await resp.json();
      code = payload?.error?.code ?? code;
      message = payload?.error?.message ?? message;
    } catch {
      // не JSON
    }
    throw new ApiError(resp.status, code, message);
  }
  return (await resp.json()) as ChatMessage;
}

export function attachmentUrl(threadId: string, messageId: string): string {
  return `${API_URL}/api/v1/chats/${threadId}/attachments/${messageId}`;
}

export interface VerificationRequest {
  id: string;
  target_level: string;
  status: 'submitted' | 'in_review' | 'needs_fix' | 'approved' | 'rejected';
  submitted_at: string;
  rejection_reason: string | null;
}

export interface MyProviderProfile extends ProviderDetail {
  status: 'draft' | 'pending_review' | 'active' | 'paused' | 'suspended' | 'rejected';
}

export async function setFavorite(providerId: string, value: boolean): Promise<void> {
  await api(`/providers/${providerId}/favorite`, { method: value ? 'PUT' : 'DELETE' });
}

export interface Placement {
  id: string;
  order_id: string;
  provider_user_id: string;
  monthly_rate: string;
  fee_amount: string;
  fee_status: 'pending' | 'paid' | 'waived';
  guarantee_until: string | null;
  replacement_requested_at: string | null;
}

export type DocumentType =
  | 'id_card'
  | 'criminal_record'
  | 'psych_dispensary'
  | 'narco_dispensary'
  | 'education'
  | 'certificate';

export interface VerificationDocument {
  id: string;
  document_type: DocumentType;
  status: 'pending' | 'approved' | 'rejected' | 'expired';
  file_name: string | null;
  valid_until: string | null;
  rejection_reason: string | null;
}

/** Загрузка документа: multipart, поэтому не через api() c JSON-телом. */
export async function uploadDocument(
  documentType: DocumentType,
  file: { uri: string; name: string; mimeType: string },
): Promise<VerificationDocument> {
  const form = new FormData();
  form.append('document_type', documentType);
  if (file.uri.startsWith('data:') || file.uri.startsWith('blob:')) {
    // Web: uri — это blob/data URL, превращаем в Blob.
    const blob = await (await fetch(file.uri)).blob();
    form.append('file', blob, file.name);
  } else {
    // Native: React Native принимает объект {uri, name, type}.
    form.append('file', { uri: file.uri, name: file.name, type: file.mimeType } as unknown as Blob);
  }

  const token = await (async () => {
    // Токен достаём тем же способом, что и api().
    const { Platform } = await import('react-native');
    if (Platform.OS === 'web') return globalThis.localStorage?.getItem('komek_access_token');
    const SecureStore = await import('expo-secure-store');
    return SecureStore.getItemAsync('komek_access_token');
  })();

  const resp = await fetch(`${API_URL}/api/v1/me/documents`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
  });
  if (!resp.ok) {
    let message = `HTTP ${resp.status}`;
    let code = 'unknown';
    try {
      const payload = await resp.json();
      code = payload?.error?.code ?? code;
      message = payload?.error?.message ?? message;
    } catch {
      // не JSON
    }
    throw new ApiError(resp.status, code, message);
  }
  return (await resp.json()) as VerificationDocument;
}
