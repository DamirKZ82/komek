'use client';

import { useCallback, useEffect, useState } from 'react';

import { api, ApiError, type AdminReview, type Page } from '@/lib/api';

function ReviewCard({ review, onDone }: { review: AdminReview; onDone: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const decide = async (publish: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await api(`/admin/reviews/${review.id}/decision`, {
        method: 'POST',
        body: { publish },
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
        <span className="badge warn">{'★'.repeat(review.rating)}{'☆'.repeat(5 - review.rating)}</span>
        <span className="muted">{new Date(review.created_at).toLocaleString('ru-RU')}</span>
      </div>
      <p style={{ marginTop: 8 }}>{review.text ?? <span className="muted">Без текста</span>}</p>
      <div className="row" style={{ marginTop: 12 }}>
        <button className="primary" disabled={busy} onClick={() => decide(true)}>
          Опубликовать
        </button>
        <button className="danger" disabled={busy} onClick={() => decide(false)}>
          Отклонить
        </button>
      </div>
      {error ? <div className="error">{error}</div> : null}
    </div>
  );
}

export default function ReviewsPage() {
  const [reviews, setReviews] = useState<AdminReview[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const page = await api<Page<AdminReview>>('/admin/reviews');
      setReviews(page.items);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 403
          ? 'Нет доступа: требуется роль модератора'
          : 'Не удалось загрузить отзывы',
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
      <h2 style={{ marginBottom: 16 }}>Отзывы на модерации</h2>
      <p className="muted" style={{ marginBottom: 16 }}>
        Сюда попадают отзывы с оценкой 1–2 (п. 5.6 ТЗ). Оценки 3–5 публикуются автоматически.
      </p>
      {error ? <div className="error">{error}</div> : null}
      {loaded && !error && reviews.length === 0 ? (
        <div className="muted">Очередь пуста 🎉</div>
      ) : null}
      {reviews.map((review) => (
        <ReviewCard key={review.id} review={review} onDone={load} />
      ))}
    </div>
  );
}
