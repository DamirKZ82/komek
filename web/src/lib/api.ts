/** Клиент Komek API для админки. Токены — в localStorage (веб, только staff). */

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const ACCESS_KEY = 'komek_admin_access';
const REFRESH_KEY = 'komek_admin_refresh';

export function saveTokens(access: string, refresh: string): void {
  localStorage.setItem(ACCESS_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export function hasTokens(): boolean {
  return typeof window !== 'undefined' && localStorage.getItem(ACCESS_KEY) !== null;
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
  const refresh = localStorage.getItem(REFRESH_KEY);
  if (!refresh) return false;
  const resp = await fetch(`${API_URL}/api/v1/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!resp.ok) {
    clearTokens();
    return false;
  }
  const data = await resp.json();
  saveTokens(data.access_token, data.refresh_token);
  return true;
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown; auth?: boolean; retry?: boolean } = {},
): Promise<T> {
  const { method = 'GET', body, auth = true, retry = true } = options;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (auth) {
    const token = localStorage.getItem(ACCESS_KEY);
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
      // не JSON
    }
    throw new ApiError(resp.status, code, message);
  }
  return (await resp.json()) as T;
}

/** Файл документа: приходит бинарником, показываем через blob-URL. */
export async function fetchDocumentBlobUrl(documentId: string): Promise<string> {
  const token = localStorage.getItem(ACCESS_KEY);
  const resp = await fetch(`${API_URL}/api/v1/admin/documents/${documentId}/file`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!resp.ok) throw new ApiError(resp.status, 'file_error', `HTTP ${resp.status}`);
  return URL.createObjectURL(await resp.blob());
}

// --- Типы ---

export interface Page<T> {
  items: T[];
  total: number;
}

export interface VerificationRequest {
  id: string;
  user_id: string;
  target_level: string;
  status: string;
  submitted_at: string;
  rejection_reason: string | null;
}

export interface AdminDocument {
  id: string;
  document_type: string;
  status: string;
  file_name: string | null;
  egov_reference: string | null;
  valid_until: string | null;
  rejection_reason: string | null;
  created_at: string;
}

export interface Complaint {
  id: string;
  reporter_id: string | null;
  target_user_id: string | null;
  order_id: string | null;
  category: string;
  status: string;
  description: string;
  auto_suspended: boolean;
  created_at: string;
}

export interface ProviderDetail {
  user_id: string;
  first_name: string | null;
  last_name: string | null;
  headline: string | null;
  about: string | null;
  experience_years: number;
  verification_level: string;
  status: string;
}

export const DOC_TYPE_LABELS: Record<string, string> = {
  id_card: 'Удостоверение личности',
  selfie: 'Селфи (liveness)',
  criminal_record: 'Справка о несудимости',
  psych_dispensary: 'Психдиспансер',
  narco_dispensary: 'Наркодиспансер',
  medical_book: 'Медкнижка',
  education: 'Образование',
  certificate: 'Сертификат',
};

export interface AdminReview {
  id: string;
  order_id: string;
  rating: number;
  text: string | null;
  direction: string;
  created_at: string;
}

export interface PayoutItem {
  order_id: string;
  amount: string;
  commission_amount: string;
}

export interface Payout {
  id: string;
  provider_user_id: string;
  status: 'scheduled' | 'processing' | 'paid' | 'failed';
  amount: string;
  batch_id: string | null;
  period_start: string | null;
  period_end: string | null;
  executed_at: string | null;
  items: PayoutItem[];
}

export interface Stats {
  orders_by_status: Record<string, number>;
  gmv_paid: string;
  commission_earned: string;
  providers_by_level: Record<string, number>;
  users_total: number;
  orders_last_30d: number;
  urgent_orders_last_30d: number;
  reviews_pending_moderation: number;
}

export interface CommissionRule {
  id: string;
  category_id: string | null;
  rate: string;
  valid_from: string;
  valid_until: string | null;
  comment: string | null;
}

export interface PromoCode {
  id: string;
  code: string;
  discount_percent: number | null;
  discount_amount: string | null;
  max_uses: number | null;
  used_count: number;
  is_active: boolean;
}

export interface CancellationRule {
  id: string;
  hours_before: number;
  penalty_percent: string;
  is_active: boolean;
}

export const COMPLAINT_LABELS: Record<string, string> = {
  safety: 'Безопасность',
  fraud: 'Мошенничество',
  quality: 'Качество',
  no_show: 'Неявка',
  off_platform: 'Увод сделки',
  spam: 'Спам',
  other: 'Другое',
};
