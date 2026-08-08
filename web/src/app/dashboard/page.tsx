'use client';

import { useEffect, useState } from 'react';

import { api, ApiError, type Stats } from '@/lib/api';

const STATUS_LABELS: Record<string, string> = {
  draft: 'Черновики',
  published: 'Опубликованы',
  sent: 'Отправлены',
  accepted: 'Приняты',
  confirmed: 'Подтверждены',
  in_progress: 'В работе',
  completed: 'Завершены',
  paid: 'Оплачены',
  cancelled: 'Отменены',
  expired: 'Истекли',
};

const LEVEL_LABELS: Record<string, string> = {
  level_0: 'Уровень 0 — зарегистрирован',
  level_1: 'Уровень 1 — личность',
  level_2: 'Уровень 2 — проверен',
  level_3: 'Уровень 3 — профессионал',
};

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Stats>('/admin/stats')
      .then(setStats)
      .catch((e) =>
        setError(
          e instanceof ApiError && e.status === 403
            ? 'Нет доступа: требуется роль модератора'
            : 'Не удалось загрузить статистику',
        ),
      );
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!stats) return <div className="muted">Загрузка…</div>;

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Дашборд</h2>

      <div className="row" style={{ alignItems: 'stretch' }}>
        <div className="card" style={{ flex: 1 }}>
          <div className="muted">GMV (оплачено)</div>
          <h3>{Number(stats.gmv_paid).toLocaleString('ru-RU')} ₸</h3>
        </div>
        <div className="card" style={{ flex: 1 }}>
          <div className="muted">Комиссия платформы</div>
          <h3>{Number(stats.commission_earned).toLocaleString('ru-RU')} ₸</h3>
        </div>
        <div className="card" style={{ flex: 1 }}>
          <div className="muted">Пользователей</div>
          <h3>{stats.users_total}</h3>
        </div>
        <div className="card" style={{ flex: 1 }}>
          <div className="muted">Заказов за 30 дней</div>
          <h3>
            {stats.orders_last_30d}
            <span className="muted" style={{ fontSize: 14 }}>
              {' '}
              (срочных: {stats.urgent_orders_last_30d})
            </span>
          </h3>
        </div>
      </div>

      <div className="row" style={{ alignItems: 'flex-start' }}>
        <div className="card" style={{ flex: 1 }}>
          <h3>Воронка заказов</h3>
          <table>
            <tbody>
              {Object.entries(STATUS_LABELS)
                .filter(([status]) => stats.orders_by_status[status])
                .map(([status, label]) => (
                  <tr key={status}>
                    <td>{label}</td>
                    <td style={{ textAlign: 'right' }}>{stats.orders_by_status[status]}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        <div className="card" style={{ flex: 1 }}>
          <h3>Исполнители по уровням</h3>
          <table>
            <tbody>
              {Object.entries(LEVEL_LABELS).map(([level, label]) => (
                <tr key={level}>
                  <td>{label}</td>
                  <td style={{ textAlign: 'right' }}>
                    {stats.providers_by_level[level] ?? 0}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="muted" style={{ marginTop: 8 }}>
            Отзывов на модерации: {stats.reviews_pending_moderation}
          </div>
        </div>
      </div>
    </div>
  );
}
