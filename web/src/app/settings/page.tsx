'use client';

import { useCallback, useEffect, useState } from 'react';

import {
  api,
  ApiError,
  type CancellationRule,
  type CommissionRule,
  type PromoCode,
} from '@/lib/api';

function CommissionSection() {
  const [rules, setRules] = useState<CommissionRule[]>([]);
  const [rate, setRate] = useState('15');
  const [comment, setComment] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRules(await api<CommissionRule[]>('/admin/commission-rules'));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка');
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      await api('/admin/commission-rules', {
        method: 'POST',
        body: {
          // В API ставка — доля, в интерфейсе удобнее проценты.
          rate: (Number(rate) / 100).toFixed(4),
          valid_from: new Date().toISOString().slice(0, 10),
          comment: comment || null,
        },
      });
      setComment('');
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка');
    } finally {
      setBusy(false);
    }
  };

  const remove = async (rule: CommissionRule) => {
    setBusy(true);
    try {
      await api(`/admin/commission-rules/${rule.id}`, { method: 'DELETE' });
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h3>Комиссия платформы</h3>
      <p className="muted">
        Действует для разовых и повторных заказов (типы B/C). Без правил применяется ставка
        по умолчанию — 15%. Подбор постоянных исполнителей (тип A) комиссией не облагается.
      </p>
      <table>
        <tbody>
          {rules.map((rule) => (
            <tr key={rule.id}>
              <td>
                <strong>{(Number(rule.rate) * 100).toFixed(1)}%</strong>
                {rule.category_id ? ' (категория)' : ' (все категории)'}
              </td>
              <td>
                с {rule.valid_from}
                {rule.valid_until ? ` по ${rule.valid_until}` : ''}
              </td>
              <td>{rule.comment ?? ''}</td>
              <td style={{ textAlign: 'right' }}>
                <button className="danger" disabled={busy} onClick={() => remove(rule)}>
                  Удалить
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row" style={{ marginTop: 12 }}>
        <input
          style={{ width: 100 }}
          type="number"
          min={0}
          max={100}
          value={rate}
          onChange={(event) => setRate(event.target.value)}
        />
        <span className="muted">%</span>
        <input
          style={{ flex: 1 }}
          placeholder="Комментарий"
          value={comment}
          onChange={(event) => setComment(event.target.value)}
        />
        <button className="primary" disabled={busy} onClick={create}>
          Добавить ставку
        </button>
      </div>
      {error ? <div className="error">{error}</div> : null}
    </div>
  );
}

function PromoSection() {
  const [promos, setPromos] = useState<PromoCode[]>([]);
  const [code, setCode] = useState('');
  const [percent, setPercent] = useState('10');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setPromos(await api<PromoCode[]>('/admin/promo-codes'));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка');
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      await api('/admin/promo-codes', {
        method: 'POST',
        body: { code, discount_percent: Number(percent) },
      });
      setCode('');
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка');
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (promo: PromoCode) => {
    setBusy(true);
    try {
      await api(`/admin/promo-codes/${promo.id}/toggle`, { method: 'POST' });
      await load();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h3>Промокоды</h3>
      <table>
        <tbody>
          {promos.map((promo) => (
            <tr key={promo.id}>
              <td>
                <strong>{promo.code}</strong>
              </td>
              <td>
                {promo.discount_percent !== null
                  ? `−${promo.discount_percent}%`
                  : `−${Number(promo.discount_amount).toLocaleString('ru-RU')} ₸`}
              </td>
              <td>
                использован: {promo.used_count}
                {promo.max_uses ? ` / ${promo.max_uses}` : ''}
              </td>
              <td>
                <span className={promo.is_active ? 'badge' : 'badge danger'}>
                  {promo.is_active ? 'активен' : 'выключен'}
                </span>
              </td>
              <td style={{ textAlign: 'right' }}>
                <button disabled={busy} onClick={() => toggle(promo)}>
                  {promo.is_active ? 'Выключить' : 'Включить'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row" style={{ marginTop: 12 }}>
        <input
          style={{ flex: 1 }}
          placeholder="КОД"
          value={code}
          onChange={(event) => setCode(event.target.value)}
        />
        <input
          style={{ width: 100 }}
          type="number"
          min={1}
          max={100}
          value={percent}
          onChange={(event) => setPercent(event.target.value)}
        />
        <span className="muted">%</span>
        <button className="primary" disabled={busy || code.length < 3} onClick={create}>
          Создать
        </button>
      </div>
      {error ? <div className="error">{error}</div> : null}
    </div>
  );
}

function CancellationSection() {
  const [rules, setRules] = useState<CancellationRule[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<CancellationRule[]>('/admin/cancellation-rules')
      .then(setRules)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Ошибка'));
  }, []);

  return (
    <div className="card">
      <h3>Штрафы за отмену</h3>
      <p className="muted">Штраф удерживается с заказчика при отмене принятого заказа.</p>
      <table>
        <tbody>
          {rules.map((rule) => (
            <tr key={rule.id}>
              <td>менее {rule.hours_before} ч до начала</td>
              <td style={{ textAlign: 'right' }}>
                <strong>{Number(rule.penalty_percent).toFixed(0)}%</strong>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {error ? <div className="error">{error}</div> : null}
    </div>
  );
}

export default function SettingsPage() {
  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Настройки платформы</h2>
      <CommissionSection />
      <PromoSection />
      <CancellationSection />
    </div>
  );
}
