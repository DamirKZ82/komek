'use client';

import { useCallback, useEffect, useState } from 'react';

import { api, ApiError, type Page, type Payout } from '@/lib/api';

const STATUS_LABELS: Record<string, string> = {
  scheduled: 'к выплате',
  processing: 'в обработке',
  paid: 'выплачено',
  failed: 'ошибка',
};

export default function FinancePage() {
  const [payouts, setPayouts] = useState<Payout[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const page = await api<Page<Payout>>('/admin/payouts');
      setPayouts(page.items);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 403
          ? 'Нет доступа: требуется роль модератора'
          : 'Не удалось загрузить выплаты',
      );
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const buildRegistry = async () => {
    setBusy('build');
    setNotice(null);
    try {
      const created = await api<Payout[]>('/admin/payouts/build', { method: 'POST' });
      setNotice(
        created.length > 0
          ? `Создано реестров: ${created.length}`
          : 'Новых оплаченных заказов для выплат нет',
      );
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка');
    } finally {
      setBusy(null);
    }
  };

  const markPaid = async (payout: Payout) => {
    setBusy(payout.id);
    try {
      await api(`/admin/payouts/${payout.id}/mark-paid`, { method: 'POST' });
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <div className="row" style={{ marginBottom: 16, justifyContent: 'space-between' }}>
        <h2>Реестры выплат</h2>
        <button className="primary" disabled={busy !== null} onClick={buildRegistry}>
          Сформировать реестр
        </button>
      </div>
      <p className="muted" style={{ marginBottom: 16 }}>
        Комиссия 15% удерживается при выплате (типы B/C, п. 5.8 ТЗ). Перевод денег — вручную
        до подключения эквайринга.
      </p>
      {notice ? <div className="card">{notice}</div> : null}
      {error ? <div className="error">{error}</div> : null}

      {payouts.map((payout) => (
        <div className="card" key={payout.id}>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <div>
              <h3>{Number(payout.amount).toLocaleString('ru-RU')} ₸</h3>
              <div className="muted">
                {payout.batch_id} · заказов: {payout.items.length}
                {payout.period_start ? ` · ${payout.period_start} — ${payout.period_end}` : ''}
                {payout.executed_at
                  ? ` · выплачено ${new Date(payout.executed_at).toLocaleString('ru-RU')}`
                  : ''}
              </div>
            </div>
            <div className="row">
              <span className={payout.status === 'paid' ? 'badge' : 'badge warn'}>
                {STATUS_LABELS[payout.status]}
              </span>
              {payout.status === 'scheduled' ? (
                <button
                  className="primary"
                  disabled={busy !== null}
                  onClick={() => markPaid(payout)}
                >
                  Отметить выплаченным
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
