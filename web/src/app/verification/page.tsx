'use client';

import { useCallback, useEffect, useState } from 'react';

import {
  api,
  ApiError,
  DOC_TYPE_LABELS,
  fetchDocumentBlobUrl,
  type AdminDocument,
  type Page,
  type ProviderDetail,
  type VerificationRequest,
} from '@/lib/api';

const CHECKLIST = [
  { key: 'identity_confirmed', label: 'Личность подтверждена (удостоверение + селфи/liveness)' },
  { key: 'criminal_record_valid', label: 'Несудимость: QR проверен на eGov, срок действует' },
  { key: 'dispensary_valid', label: 'Диспансерные справки: QR проверены, сроки действуют' },
  { key: 'iin_match', label: 'ИИН совпадает во всех документах' },
  { key: 'interview_passed', label: 'Интервью/видео-представление пройдено' },
];

function RequestCard({ request, onDone }: { request: VerificationRequest; onDone: () => void }) {
  const [provider, setProvider] = useState<ProviderDetail | null>(null);
  const [documents, setDocuments] = useState<AdminDocument[]>([]);
  const [checklist, setChecklist] = useState<Record<string, boolean>>({});
  const [reason, setReason] = useState('');
  const [preview, setPreview] = useState<{ id: string; url: string; mime: string } | null>(null);
  const [docIin, setDocIin] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<ProviderDetail>(`/providers/${request.user_id}`)
      .then(setProvider)
      .catch(() => setProvider(null));
    api<AdminDocument[]>(`/admin/users/${request.user_id}/documents`)
      .then(setDocuments)
      .catch(() => setDocuments([]));
  }, [request.user_id]);

  const showDocument = async (doc: AdminDocument) => {
    try {
      const url = await fetchDocumentBlobUrl(doc.id);
      setPreview({ id: doc.id, url, mime: doc.file_name?.endsWith('.pdf') ? 'pdf' : 'image' });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось открыть файл');
    }
  };

  const decideDocument = async (doc: AdminDocument, approve: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await api(`/admin/documents/${doc.id}/decision`, {
        method: 'POST',
        body: {
          approve,
          iin: docIin[doc.id] || undefined,
          rejection_reason: approve ? undefined : 'Документ не прошёл проверку',
        },
      });
      setDocuments(await api<AdminDocument[]>(`/admin/users/${request.user_id}/documents`));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка');
    } finally {
      setBusy(false);
    }
  };

  const decide = async (approve: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await api(`/admin/verification-requests/${request.id}/decision`, {
        method: 'POST',
        body: {
          approve,
          checklist,
          rejection_reason: approve ? undefined : reason || 'Не пройдена проверка',
        },
      });
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Ошибка');
    } finally {
      setBusy(false);
    }
  };

  const name = provider
    ? [provider.first_name, provider.last_name].filter(Boolean).join(' ') || 'Без имени'
    : '…';

  return (
    <div className="card">
      <h3>
        {name} <span className="badge">{request.target_level}</span>
      </h3>
      <div className="muted">
        Подана: {new Date(request.submitted_at).toLocaleString('ru-RU')}
        {provider?.headline ? ` · ${provider.headline}` : ''}
        {provider ? ` · опыт ${provider.experience_years} лет` : ''}
      </div>
      {provider?.about ? <p style={{ marginTop: 8 }}>{provider.about}</p> : null}

      <h4 style={{ marginTop: 12 }}>Документы</h4>
      {documents.length === 0 ? <div className="muted">Документы не загружены</div> : null}
      <table>
        <tbody>
          {documents.map((doc) => (
            <tr key={doc.id}>
              <td>{DOC_TYPE_LABELS[doc.document_type] ?? doc.document_type}</td>
              <td>
                <span
                  className={
                    doc.status === 'approved'
                      ? 'badge'
                      : doc.status === 'pending'
                        ? 'badge warn'
                        : 'badge danger'
                  }
                >
                  {doc.status}
                </span>
                {doc.valid_until ? <span className="muted"> до {doc.valid_until}</span> : null}
              </td>
              <td>{doc.egov_reference ?? ''}</td>
              <td>
                <div className="row">
                  <button onClick={() => showDocument(doc)}>Открыть</button>
                  {doc.status === 'pending' ? (
                    <>
                      <input
                        style={{ width: 140 }}
                        placeholder="ИИН из документа"
                        maxLength={12}
                        value={docIin[doc.id] ?? ''}
                        onChange={(event) =>
                          setDocIin((current) => ({ ...current, [doc.id]: event.target.value }))
                        }
                      />
                      <button
                        className="primary"
                        disabled={busy}
                        onClick={() => decideDocument(doc, true)}
                      >
                        ✓
                      </button>
                      <button
                        className="danger"
                        disabled={busy}
                        onClick={() => decideDocument(doc, false)}
                      >
                        ✗
                      </button>
                    </>
                  ) : null}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {preview ? (
        preview.mime === 'pdf' ? (
          <iframe className="doc-preview" style={{ width: '100%', height: 480 }} src={preview.url} />
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img className="doc-preview" src={preview.url} alt="Документ" />
        )
      ) : null}

      <h4 style={{ marginTop: 12 }}>Чек-лист модератора</h4>
      {CHECKLIST.map((item) => (
        <label className="check" key={item.key}>
          <input
            type="checkbox"
            checked={checklist[item.key] ?? false}
            onChange={(event) =>
              setChecklist((current) => ({ ...current, [item.key]: event.target.checked }))
            }
          />
          {item.label}
        </label>
      ))}

      <div className="row" style={{ marginTop: 12 }}>
        <button
          className="primary"
          disabled={busy || !CHECKLIST.every((item) => checklist[item.key])}
          onClick={() => decide(true)}
        >
          Одобрить
        </button>
        <input
          style={{ flex: 1 }}
          placeholder="Причина отказа"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
        <button className="danger" disabled={busy} onClick={() => decide(false)}>
          Отклонить
        </button>
      </div>
      {error ? <div className="error">{error}</div> : null}
    </div>
  );
}

export default function VerificationPage() {
  const [requests, setRequests] = useState<VerificationRequest[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const page = await api<Page<VerificationRequest>>(
        '/admin/verification-requests?status=submitted',
      );
      setRequests(page.items);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 403
          ? 'Нет доступа: требуется роль модератора'
          : 'Не удалось загрузить очередь',
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
      <h2 style={{ marginBottom: 16 }}>Очередь верификации</h2>
      {error ? <div className="error">{error}</div> : null}
      {loaded && !error && requests.length === 0 ? (
        <div className="muted">Очередь пуста 🎉</div>
      ) : null}
      {requests.map((request) => (
        <RequestCard key={request.id} request={request} onDone={load} />
      ))}
    </div>
  );
}
