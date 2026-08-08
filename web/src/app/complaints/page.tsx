'use client';

import { useCallback, useEffect, useState } from 'react';

import { api, ApiError, COMPLAINT_LABELS, type Complaint, type Page } from '@/lib/api';

function ComplaintCard({ complaint, onDone }: { complaint: Complaint; onDone: () => void }) {
  const [resolution, setResolution] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const resolve = async (dismiss: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await api(`/admin/complaints/${complaint.id}/resolve`, {
        method: 'POST',
        body: {
          resolution: resolution || (dismiss ? 'Жалоба не подтвердилась' : 'Меры приняты'),
          dismiss,
        },
      });
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <div className="row">
        <span className={complaint.category === 'safety' ? 'badge danger' : 'badge warn'}>
          {COMPLAINT_LABELS[complaint.category] ?? complaint.category}
        </span>
        {complaint.auto_suspended ? (
          <span className="badge danger">профиль приостановлен автоматически</span>
        ) : null}
        <span className="muted">{new Date(complaint.created_at).toLocaleString('ru-RU')}</span>
      </div>
      <p style={{ marginTop: 8 }}>{complaint.description}</p>
      <div className="row" style={{ marginTop: 12 }}>
        <input
          style={{ flex: 1 }}
          placeholder="Решение / комментарий"
          value={resolution}
          onChange={(event) => setResolution(event.target.value)}
        />
        <button className="primary" disabled={busy} onClick={() => resolve(false)}>
          Подтвердить (меры приняты)
        </button>
        <button disabled={busy} onClick={() => resolve(true)}>
          Отклонить жалобу
        </button>
      </div>
      {complaint.auto_suspended ? (
        <div className="muted" style={{ marginTop: 6 }}>
          При отклонении жалобы профиль автоматически вернётся в поиск.
        </div>
      ) : null}
      {error ? <div className="error">{error}</div> : null}
    </div>
  );
}

export default function ComplaintsPage() {
  const [complaints, setComplaints] = useState<Complaint[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const page = await api<Page<Complaint>>('/admin/complaints?status=open');
      setComplaints(page.items);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 403
          ? 'Нет доступа: требуется роль модератора'
          : 'Не удалось загрузить жалобы',
      );
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Открытые жалобы</h2>
      {error ? <div className="error">{error}</div> : null}
      {loaded && !error && complaints.length === 0 ? (
        <div className="muted">Открытых жалоб нет 🎉</div>
      ) : null}
      {complaints.map((complaint) => (
        <ComplaintCard key={complaint.id} complaint={complaint} onDone={load} />
      ))}
    </div>
  );
}
